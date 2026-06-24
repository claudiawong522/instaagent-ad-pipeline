from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from instaagent_pipeline.embeddings import (
    ALL_SPACES,
    EMBEDDING_SPACES,
    EmbedResult,
    EmbeddingCandidate,
    batched,
    build_icp_text,
    build_search_text,
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
    assert build_icp_text(row) == "persona: busy mom with sensitive skin; audience: women 25-34"


def test_build_icp_text_flattens_jsonb_persona() -> None:
    row = {
        "persona": {"segment": "skincare beginners", "pain": ["redness", "dryness"]},
        "target_demographic": None,
    }
    assert build_icp_text(row) == "persona: pain: redness, dryness; segment: skincare beginners"


def test_build_icp_text_returns_none_without_signal() -> None:
    assert build_icp_text({"persona": None, "target_demographic": "  "}) is None


def test_embedding_spaces_are_icp_and_search_only() -> None:
    assert EMBEDDING_SPACES == ("icp", "search")
    assert ALL_SPACES == ("icp", "search")


def test_build_search_text_returns_none_without_description() -> None:
    assert build_search_text({"ai_description": "", "content_format": "demo"}) is None
    assert build_search_text({"ai_description": None}) is None


def test_build_search_text_combines_description_tags_and_transcript() -> None:
    row = {
        "ai_description": "A creator demos a gentle cleanser before/after.",
        "content_format": "talking_head",
        "main_category": "beauty",
        "content_category": "skincare",
        "product_category": "cleanser",
        "video_topic": "skin barrier",
        "niches": ["sensitive skin", "redness"],
        "hook": "Stop washing your face wrong",
        "setting": "bathroom",
        "primary_emotion": "trust",
        "brand_mentioned": "QE Skincare",
        "transcript_text": "Hi, today I am trying this cleanser and my skin feels great.",
    }
    expected = (
        "A creator demos a gentle cleanser before/after."
        "\n\n"
        "format: talking_head; category: beauty; subcategory: skincare; "
        "product: cleanser; topic: skin barrier; niches: sensitive skin, redness; "
        "hook: Stop washing your face wrong; setting: bathroom; emotion: trust; "
        "brands: QE Skincare"
        "\n\n"
        "Hi, today I am trying this cleanser and my skin feels great."
    )
    assert build_search_text(row) == expected


def test_build_search_text_description_only_when_no_tags_or_transcript() -> None:
    assert build_search_text({"ai_description": "Just a description."}) == "Just a description."


def test_flatten_jsonish_handles_nested_values() -> None:
    assert flatten_jsonish(["a", "", None, "b"]) == "a, b"
    assert flatten_jsonish({"b": "two", "a": "one"}) == "a: one; b: two"
    assert flatten_jsonish(True) is None
    assert flatten_jsonish(27) == "27"


def test_collect_candidates_skips_existing_and_empty_spaces() -> None:
    # icp is already embedded (skipped_existing); search has no ai_description
    # (skipped_no_text), so this row yields zero new candidates.
    rows: list[dict[str, Any]] = [
        {
            "item_id": "ad-1",
            "persona": "gym goers",
            "target_demographic": None,
            "ai_description": None,
            "content_format": "demo",
        }
    ]
    result = EmbedResult()
    out: list[EmbeddingCandidate] = []
    collect_candidates(
        rows,
        item_type="paid_ad",
        id_column="item_id",
        spaces=("icp", "search"),
        existing={("paid_ad", "ad-1", "icp")},
        result=result,
        out=out,
    )

    assert out == []
    assert result.skipped_existing == 1
    assert result.skipped_no_text == 1


def test_collect_candidates_yields_icp_and_search_for_complete_row() -> None:
    rows: list[dict[str, Any]] = [
        {
            "item_id": "ad-2",
            "persona": "gym goers",
            "target_demographic": "men 18-34",
            "ai_description": "A short demo of a protein shake.",
            "content_format": "demo",
        }
    ]
    result = EmbedResult()
    out: list[EmbeddingCandidate] = []
    collect_candidates(
        rows,
        item_type="paid_ad",
        id_column="item_id",
        spaces=("icp", "search"),
        existing=set(),
        result=result,
        out=out,
    )

    # An item now yields up to 2 candidates: icp and search.
    assert [candidate.space for candidate in out] == ["icp", "search"]
    assert out[0].source_text == "persona: gym goers; audience: men 18-34"
    assert out[1].source_text.startswith("A short demo of a protein shake.")
    assert "format: demo" in out[1].source_text
    assert result.skipped_existing == 0
    assert result.skipped_no_text == 0


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
