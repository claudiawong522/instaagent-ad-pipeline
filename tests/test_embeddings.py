from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from instaagent_pipeline.embeddings import (
    EmbedResult,
    EmbeddingCandidate,
    batched,
    build_format_text,
    build_hook_text,
    build_icp_text,
    collect_candidates,
    flatten_jsonish,
    parse_voyage_response,
    vector_literal,
    voyage_usage,
)


FIXTURE = Path("tests/fixtures/voyage_embeddings_success.json")


def test_build_icp_text_combines_persona_and_target_demographic() -> None:
    row = {
        "persona": "busy mom with sensitive skin",
        "target_demographic": "women 25-34",
    }
    assert build_icp_text(row) == "busy mom with sensitive skin; women 25-34"


def test_build_icp_text_flattens_jsonb_persona() -> None:
    row = {
        "persona": {"segment": "skincare beginners", "pain": ["redness", "dryness"]},
        "target_demographic": None,
    }
    assert build_icp_text(row) == "pain: redness, dryness; segment: skincare beginners"


def test_build_icp_text_returns_none_without_signal() -> None:
    assert build_icp_text({"persona": None, "target_demographic": "  "}) is None


def test_build_format_text_labels_present_fields() -> None:
    row = {
        "content_format": "talking_head",
        "content_category": "skincare",
        "visual_style": None,
        "setting": "bathroom",
    }
    assert build_format_text(row) == "format: talking_head; category: skincare; setting: bathroom"


def test_build_hook_text_strips_and_rejects_empty() -> None:
    assert build_hook_text({"hook": "  Stop washing your face wrong  "}) == "Stop washing your face wrong"
    assert build_hook_text({"hook": ""}) is None
    assert build_hook_text({}) is None


def test_flatten_jsonish_handles_nested_values() -> None:
    assert flatten_jsonish(["a", "", None, "b"]) == "a, b"
    assert flatten_jsonish({"b": "two", "a": "one"}) == "a: one; b: two"
    assert flatten_jsonish(True) is None
    assert flatten_jsonish(27) == "27"


def test_collect_candidates_skips_existing_and_empty_spaces() -> None:
    rows: list[dict[str, Any]] = [
        {
            "paid_ad_row_id": "ad-1",
            "persona": "gym goers",
            "target_demographic": None,
            "content_format": "demo",
            "content_category": None,
            "visual_style": None,
            "setting": None,
            "hook": None,
        }
    ]
    result = EmbedResult()
    out: list[EmbeddingCandidate] = []
    collect_candidates(
        rows,
        item_type="paid_ad",
        id_column="paid_ad_row_id",
        existing={("paid_ad", "ad-1", "icp")},
        result=result,
        out=out,
    )

    assert [(candidate.space, candidate.source_text) for candidate in out] == [("format", "format: demo")]
    assert result.skipped_existing == 1
    assert result.skipped_no_text == 1


def test_parse_voyage_response_orders_by_index() -> None:
    body = json.loads(FIXTURE.read_text())
    body["data"].reverse()

    embeddings = parse_voyage_response(body, expected_count=2)

    assert embeddings[0] == [0.013, -0.024, 0.051, 0.007]
    assert embeddings[1] == [-0.041, 0.018, -0.002, 0.033]
    assert voyage_usage(body) == {"total_tokens": 21}


def test_parse_voyage_response_rejects_count_mismatch() -> None:
    body = json.loads(FIXTURE.read_text())
    try:
        parse_voyage_response(body, expected_count=3)
    except RuntimeError as exc:
        assert "2 embeddings for 3 inputs" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_vector_literal_is_pgvector_text_format() -> None:
    assert vector_literal([0.013, -0.024]) == "[0.013,-0.024]"


def test_batched_splits_preserving_order() -> None:
    items = [
        EmbeddingCandidate(item_type="paid_ad", item_id=str(i), space="hook", source_text="t")
        for i in range(5)
    ]
    chunks = batched(items, 2)
    assert [len(chunk) for chunk in chunks] == [2, 2, 1]
    assert chunks[2][0].item_id == "4"
