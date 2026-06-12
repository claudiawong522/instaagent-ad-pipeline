from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from instaagent_pipeline.clustering import (
    ClusterCandidate,
    build_cluster_view,
    cluster_cell,
    cosine_distances_to_centroid,
    normalize,
    openrouter_label_body,
    parse_embedding,
    parse_label_response,
    render_label_text,
    unit_centroid,
)


LABEL_FIXTURE = Path("tests/fixtures/openrouter_icp_label_success.json")


def test_normalize_makes_unit_vectors() -> None:
    matrix = np.array([[3.0, 4.0], [0.0, 0.0]])
    normalized = normalize(matrix)
    assert np.isclose(np.linalg.norm(normalized[0]), 1.0)
    # Zero vector is left untouched rather than producing NaNs.
    assert np.allclose(normalized[1], [0.0, 0.0])


def test_unit_centroid_and_distances() -> None:
    members = normalize(np.array([[1.0, 0.0], [0.0, 1.0]]))
    centroid = unit_centroid(members)
    assert np.isclose(np.linalg.norm(centroid), 1.0)
    distances = cosine_distances_to_centroid(members, centroid)
    # Both members are equidistant from the bisecting centroid.
    assert np.isclose(distances[0], distances[1])
    assert (distances >= 0).all()


def test_cluster_cell_separates_two_blobs() -> None:
    # Two tight, well-separated directions -> two clusters, no noise, high silhouette.
    blob_a = [[1.0, 0.0, 0.0], [0.99, 0.01, 0.0], [0.98, 0.0, 0.02], [0.97, 0.02, 0.01]]
    blob_b = [[0.0, 0.0, 1.0], [0.01, 0.0, 0.99], [0.0, 0.02, 0.98], [0.02, 0.01, 0.97]]
    cell = cluster_cell(blob_a + blob_b, min_cluster_size=3)

    assert len(cell.clusters) == 2
    assert set(cell.labels) == {0, 1}
    assert cell.silhouette is not None and cell.silhouette > 0.5
    # Every member is accounted for across the two clusters.
    assert sum(cluster.member_count for cluster in cell.clusters) == 8


def test_cluster_cell_silhouette_none_for_single_cluster() -> None:
    points = [[1.0, 0.0], [0.99, 0.01], [0.98, 0.02], [0.99, 0.0]]
    cell = cluster_cell(points, min_cluster_size=3)
    # Fewer than two non-noise clusters -> silhouette is undefined.
    assert cell.silhouette is None


def test_build_cluster_view_picks_closest_exemplars() -> None:
    candidates = [
        ClusterCandidate(item_id=f"id-{i}", source_text=f"text-{i}", vector=[0.0])
        for i in range(3)
    ]
    from instaagent_pipeline.clustering import CellCluster

    cluster = CellCluster(
        cluster_label=0,
        member_indices=[0, 1, 2],
        centroid=[0.0],
        distances=[0.5, 0.1, 0.9],
    )
    view = build_cluster_view(cluster, candidates, silhouette=0.6)
    # Ordered by ascending distance: id-1 (0.1), id-0 (0.5), id-2 (0.9).
    assert view["exemplar_item_ids"] == ["id-1", "id-0", "id-2"]
    assert view["summary"]["member_count"] == 3
    assert view["summary"]["silhouette"] == 0.6


def test_parse_label_response_reads_icp_json() -> None:
    body = json.loads(LABEL_FIXTURE.read_text())
    label = parse_label_response(body)
    assert label is not None
    assert label["persona"].startswith("APAC women")
    assert "skin feels tight or stripped after washing" in label["pains"]


def test_parse_label_response_rejects_missing_persona() -> None:
    body = {"choices": [{"message": {"content": json.dumps({"pains": ["x"]})}}]}
    assert parse_label_response(body) is None


def test_parse_label_response_rejects_non_chat_body() -> None:
    assert parse_label_response({"data": []}) is None


def test_render_label_text_matches_block_format() -> None:
    label = {
        "persona": "APAC women 18-30 with reactive skin",
        "pains": ["tight after washing", "burned by actives"],
        "scrolls_for": ["derm explainers", "pharmacy finds"],
        "quote": "if it has fragrance, my face will react.",
    }
    assert render_label_text(label) == (
        "PERSONA\n"
        "APAC women 18-30 with reactive skin\n"
        "PAINS\n"
        "tight after washing\n"
        "burned by actives\n"
        "SCROLLS FOR\n"
        "derm explainers, pharmacy finds\n"
        '"if it has fragrance, my face will react."'
    )


def test_render_label_text_omits_empty_quote() -> None:
    text = render_label_text({"persona": "p", "pains": [], "scrolls_for": [], "quote": ""})
    assert text == "PERSONA\np\nPAINS\nSCROLLS FOR\n"


def test_openrouter_label_body_requests_strict_json_schema() -> None:
    body = openrouter_label_body(model="m", exemplars=["a", "", "b"])
    assert body["model"] == "m"
    # Blank exemplars are dropped from the prompt bullet list.
    assert "- a\n- b" in body["messages"][0]["content"]
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["response_format"]["json_schema"]["schema"]["required"] == [
        "persona",
        "pains",
        "scrolls_for",
        "quote",
    ]


def test_parse_embedding_handles_pgvector_string_and_list() -> None:
    assert parse_embedding("[0.1, 0.2, -0.3]") == [0.1, 0.2, -0.3]
    assert parse_embedding([1, 2, 3]) == [1.0, 2.0, 3.0]
    assert parse_embedding("not-json") is None
    assert parse_embedding(None) is None
