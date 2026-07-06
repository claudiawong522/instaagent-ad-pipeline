from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from .config import Config
from .embeddings import vector_literal
from .http_client import HttpClientError, request_json
from .ingestion import logged_query
from .openrouter import (
    OPENROUTER_CHAT_COMPLETIONS_ENDPOINT,
    OPENROUTER_CHAT_URL,
    OPENROUTER_PROVIDER,
    openrouter_json_body,
    openrouter_usage,
    parse_json_response,
)
from .supabase_client import SupabaseClient


ICP_SPACE = "icp"
DEFAULT_MIN_CLUSTER_SIZE = 5
EXEMPLAR_COUNT = 5

# item_type per source, ordered so paid ads cluster before organic in "all".
ITEM_TYPES = {
    "paid": ("paid_ad",),
    "ugc": ("ugc_item",),
    "all": ("paid_ad", "ugc_item"),
}

EMBEDDING_SELECT_COLUMNS = "item_id,source_text,embedding"

ICP_LABEL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "persona": {"type": "string"},
        "pains": {"type": "array", "items": {"type": "string"}},
        "scrolls_for": {"type": "array", "items": {"type": "string"}},
        "quote": {"type": "string"},
    },
    "required": ["persona", "pains", "scrolls_for", "quote"],
}

ICP_LABEL_PROMPT = """
You are labeling a cluster of ideal-customer-profile (ICP) descriptions that were
grouped together because they target a similar audience. Below are representative ICP
descriptions pulled from social video ads.

Summarize the shared audience as one persona. Return JSON with:
- persona: one concise sentence naming who this audience is (demographics + their skin/
  health/lifestyle context).
- pains: 2-5 short phrases naming this audience's frustrations or unmet needs.
- scrolls_for: 2-6 short phrases naming the content/topics this audience stops to watch.
- quote: one short first-person line (<= 12 words) this person might say, in their voice.

Representative ICP descriptions:
{exemplars}
""".strip()


@dataclass
class ClusterCandidate:
    item_id: str
    source_text: str
    vector: list[float]


@dataclass
class CellCluster:
    cluster_label: int
    member_indices: list[int]
    centroid: list[float]
    distances: list[float]  # cosine distance per member, aligned to member_indices

    @property
    def member_count(self) -> int:
        return len(self.member_indices)


@dataclass
class CellResult:
    labels: list[int]  # one per candidate, -1 == noise
    silhouette: float | None
    clusters: list[CellCluster]


@dataclass
class ClusterResult:
    cells: int = 0
    items: int = 0
    clusters: int = 0
    noise: int = 0
    labeled: int = 0
    failed: int = 0
    skipped_small: int = 0
    silhouette: dict[str, float | None] = field(default_factory=dict)
    details: list[dict[str, Any]] = field(default_factory=list)


def cluster_items(
    *,
    config: Config,
    supabase: SupabaseClient | None,
    run_id: str,
    source: str = "all",
    min_cluster_size: int = DEFAULT_MIN_CLUSTER_SIZE,
    limit: int = 1000,
    dry_run: bool = False,
    no_label: bool = False,
    model: str | None = None,
    input_json: Path | None = None,
    timeout: int = 120,
) -> ClusterResult:
    if supabase is None:
        raise RuntimeError("Supabase credentials are required to load clustering candidates.")
    if source not in ITEM_TYPES:
        raise ValueError("--source must be one of paid, ugc, all.")
    if limit < 1:
        raise ValueError("--limit must be greater than 0.")
    if min_cluster_size < 2:
        raise ValueError("--min-cluster-size must be at least 2.")

    label_model = model or config.openrouter_model
    clustering_params = f"hdbscan:min_cluster_size={min_cluster_size}"
    result = ClusterResult()

    for item_type in ITEM_TYPES[source]:
        candidates = load_candidates(supabase, run_id=run_id, item_type=item_type, limit=limit)
        cell_key = f"{item_type}:{ICP_SPACE}"
        if len(candidates) < min_cluster_size:
            result.skipped_small += 1
            result.details.append(
                {
                    "cell": cell_key,
                    "action": "skipped_small",
                    "items": len(candidates),
                    "min_cluster_size": min_cluster_size,
                }
            )
            continue

        result.cells += 1
        result.items += len(candidates)
        cell = cluster_cell([candidate.vector for candidate in candidates], min_cluster_size)
        result.silhouette[cell_key] = cell.silhouette
        result.noise += sum(1 for label in cell.labels if label == -1)
        result.clusters += len(cell.clusters)

        cluster_views = [
            build_cluster_view(cluster, candidates, cell.silhouette)
            for cluster in cell.clusters
        ]

        if dry_run:
            for view in cluster_views:
                result.details.append({"cell": cell_key, "action": "would_cluster", **view["summary"]})
            continue

        # Re-clustering can produce fewer clusters than a prior run; clear the cell's
        # old cluster rows so stale labels don't linger. Assignments are overwritten by
        # the item_clusters upsert below, so only the clusters table needs clearing.
        supabase.delete(
            "clusters",
            {
                "run_id": f"eq.{run_id}",
                "item_type": f"eq.{item_type}",
                "space": f"eq.{ICP_SPACE}",
            },
        )

        for view in cluster_views:
            label_json: dict[str, Any] | None = None
            if not no_label:
                try:
                    label_json = label_cluster(
                        config=config,
                        supabase=supabase,
                        run_id=run_id,
                        item_type=item_type,
                        exemplars=view["exemplar_texts"],
                        label_model=label_model,
                        input_json=input_json,
                        timeout=timeout,
                    )
                except (HttpClientError, RuntimeError) as exc:
                    result.failed += 1
                    result.details.append(
                        {
                            "cell": cell_key,
                            "cluster_label": view["cluster"].cluster_label,
                            "status": "label_failed",
                            "error": str(exc),
                        }
                    )
                if label_json is not None:
                    result.labeled += 1

            write_cluster(
                supabase=supabase,
                run_id=run_id,
                item_type=item_type,
                cluster=view["cluster"],
                exemplar_item_ids=view["exemplar_item_ids"],
                silhouette=cell.silhouette,
                label_json=label_json,
                label_model=label_model if (not no_label and label_json is not None) else None,
                clustering_params=clustering_params,
            )

        write_assignments(
            supabase=supabase,
            run_id=run_id,
            item_type=item_type,
            candidates=candidates,
            cell=cell,
            clustering_params=clustering_params,
        )

    return result


def load_candidates(
    supabase: SupabaseClient,
    *,
    run_id: str,
    item_type: str,
    limit: int,
) -> list[ClusterCandidate]:
    rows = supabase.select(
        "item_embeddings",
        {
            "select": EMBEDDING_SELECT_COLUMNS,
            "run_id": f"eq.{run_id}",
            "item_type": f"eq.{item_type}",
            "space": f"eq.{ICP_SPACE}",
            "order": "item_id.asc",
            "limit": str(limit),
        },
    )
    candidates: list[ClusterCandidate] = []
    for row in rows:
        item_id = str(row.get("item_id") or "")
        vector = parse_embedding(row.get("embedding"))
        if not item_id or vector is None:
            continue
        candidates.append(
            ClusterCandidate(
                item_id=item_id,
                source_text=str(row.get("source_text") or ""),
                vector=vector,
            )
        )
    return candidates


def cluster_cell(vectors: list[list[float]], min_cluster_size: int) -> CellResult:
    # Imported here so unrelated CLI commands don't pay sklearn's import cost.
    from sklearn.cluster import HDBSCAN

    normalized = normalize(np.asarray(vectors, dtype=float))
    labels = HDBSCAN(min_cluster_size=min_cluster_size).fit_predict(normalized)
    labels_list = [int(label) for label in labels]

    clusters: list[CellCluster] = []
    for cluster_label in sorted({label for label in labels_list if label != -1}):
        member_indices = [i for i, label in enumerate(labels_list) if label == cluster_label]
        members = normalized[member_indices]
        centroid = unit_centroid(members)
        distances = cosine_distances_to_centroid(members, centroid)
        clusters.append(
            CellCluster(
                cluster_label=cluster_label,
                member_indices=member_indices,
                centroid=[float(value) for value in centroid],
                distances=[float(value) for value in distances],
            )
        )

    return CellResult(
        labels=labels_list,
        silhouette=cell_silhouette(normalized, labels_list),
        clusters=clusters,
    )


def normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    # Guard against zero-length vectors so we never divide by zero.
    norms = np.where(norms == 0, 1.0, norms)
    return matrix / norms


def unit_centroid(members: np.ndarray) -> np.ndarray:
    centroid = members.mean(axis=0)
    norm = float(np.linalg.norm(centroid))
    if norm == 0:
        return centroid
    return centroid / norm


def cosine_distances_to_centroid(members: np.ndarray, centroid: np.ndarray) -> np.ndarray:
    # members and centroid are unit vectors, so cosine distance = 1 - dot product.
    return 1.0 - members @ centroid


def cell_silhouette(normalized: np.ndarray, labels: list[int]) -> float | None:
    from sklearn.metrics import silhouette_score

    mask = np.array([label != -1 for label in labels])
    if int(mask.sum()) < 2:
        return None
    sub_labels = [label for label in labels if label != -1]
    if len(set(sub_labels)) < 2:
        return None
    return float(silhouette_score(normalized[mask], sub_labels, metric="cosine"))


def build_cluster_view(
    cluster: CellCluster,
    candidates: list[ClusterCandidate],
    silhouette: float | None,
) -> dict[str, Any]:
    order = sorted(range(cluster.member_count), key=lambda i: cluster.distances[i])
    exemplar_order = order[:EXEMPLAR_COUNT]
    exemplar_candidates = [candidates[cluster.member_indices[i]] for i in exemplar_order]
    return {
        "cluster": cluster,
        "exemplar_item_ids": [candidate.item_id for candidate in exemplar_candidates],
        "exemplar_texts": [candidate.source_text for candidate in exemplar_candidates],
        "summary": {
            "cluster_label": cluster.cluster_label,
            "member_count": cluster.member_count,
            "silhouette": silhouette,
            "exemplars": [candidate.source_text for candidate in exemplar_candidates],
        },
    }


def label_cluster(
    *,
    config: Config,
    supabase: SupabaseClient,
    run_id: str,
    item_type: str,
    exemplars: list[str],
    label_model: str,
    input_json: Path | None,
    timeout: int,
) -> dict[str, Any] | None:
    with logged_query(
        supabase=supabase,
        run_id=run_id,
        provider=f"{OPENROUTER_PROVIDER}:{label_model}",
        endpoint=OPENROUTER_CHAT_COMPLETIONS_ENDPOINT,
        request_params={"model": label_model, "item_type": item_type, "exemplar_count": len(exemplars)},
    ) as log:
        log.metadata = {"model": label_model}
        if input_json:
            body = json.loads(input_json.read_text())
        else:
            response = request_json(
                "POST",
                OPENROUTER_CHAT_URL,
                headers={"Authorization": f"Bearer {config.openrouter_api_key}"},
                body=openrouter_label_body(model=label_model, exemplars=exemplars),
                timeout=timeout,
            )
            body = response.body
            log.headers = response.headers
            log.status = response.status

        label = parse_label_response(body)
        log.response_count = 1 if label is not None else 0
        log.metadata["usage"] = openrouter_usage(body)

    return label


def openrouter_label_body(*, model: str, exemplars: list[str]) -> dict[str, Any]:
    rendered = "\n".join(f"- {text}" for text in exemplars if text)
    prompt = ICP_LABEL_PROMPT.format(exemplars=rendered)
    return openrouter_json_body(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        schema=ICP_LABEL_SCHEMA,
        schema_name="icp_cluster_label",
    )


def parse_label_response(body: Any) -> dict[str, Any] | None:
    parsed = parse_json_response(body)  # shared choices[0].message.content JSON extraction
    if parsed is None:
        return None
    if not isinstance(parsed.get("persona"), str) or not parsed["persona"].strip():
        return None
    return parsed


def render_label_text(label: dict[str, Any]) -> str:
    persona = str(label.get("persona") or "").strip()
    pains = [str(item).strip() for item in (label.get("pains") or []) if str(item).strip()]
    scrolls = [str(item).strip() for item in (label.get("scrolls_for") or []) if str(item).strip()]
    quote = str(label.get("quote") or "").strip()

    lines = ["PERSONA", persona, "PAINS", *pains, "SCROLLS FOR", ", ".join(scrolls)]
    if quote:
        lines.append(f'"{quote}"')
    return "\n".join(lines)


def write_cluster(
    *,
    supabase: SupabaseClient,
    run_id: str,
    item_type: str,
    cluster: CellCluster,
    exemplar_item_ids: list[str],
    silhouette: float | None,
    label_json: dict[str, Any] | None,
    label_model: str | None,
    clustering_params: str,
) -> None:
    name = str(label_json.get("persona")).strip() if label_json else None
    label_text = render_label_text(label_json) if label_json else None
    supabase.upsert(
        "clusters",
        {
            "run_id": run_id,
            "item_type": item_type,
            "space": ICP_SPACE,
            "cluster_label": cluster.cluster_label,
            "name": name,
            "label_json": label_json,
            "label_text": label_text,
            "centroid": vector_literal(cluster.centroid),
            "member_count": cluster.member_count,
            "exemplar_item_ids": exemplar_item_ids,
            "silhouette": silhouette,
            "label_model": label_model,
            "clustering_params": clustering_params,
        },
        "run_id,item_type,space,cluster_label",
    )


def write_assignments(
    *,
    supabase: SupabaseClient,
    run_id: str,
    item_type: str,
    candidates: list[ClusterCandidate],
    cell: CellResult,
    clustering_params: str,
) -> None:
    distance_by_index: dict[int, float] = {}
    for cluster in cell.clusters:
        for position, index in enumerate(cluster.member_indices):
            distance_by_index[index] = cluster.distances[position]

    payload = [
        {
            "run_id": run_id,
            "item_type": item_type,
            "item_id": candidate.item_id,
            "space": ICP_SPACE,
            "cluster_label": cell.labels[index],
            "distance_to_centroid": distance_by_index.get(index),
            "clustering_params": clustering_params,
        }
        for index, candidate in enumerate(candidates)
    ]
    supabase.upsert("item_clusters", payload, "item_type,item_id,space")


def parse_embedding(value: Any) -> list[float] | None:
    if isinstance(value, list):
        try:
            return [float(item) for item in value]
        except (TypeError, ValueError):
            return None
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, list):
            return [float(item) for item in parsed]
    return None
