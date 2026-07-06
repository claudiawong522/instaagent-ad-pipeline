from __future__ import annotations

import pytest

from instaagent_pipeline.keywords import allocate_manual_keywords, parse_keyword_allocations


def test_parse_keyword_allocations_requires_totals_to_match() -> None:
    text = """
    {
      "keywords": [
        {"keyword_text": "cleanser", "target_paid_count": 4, "target_organic_count": 10, "target_tiktok_count": 7},
        {"keyword_text": "gentle cleanser", "target_paid_count": 3, "target_organic_count": 10, "target_tiktok_count": 7},
        {"keyword_text": "sensitive skin cleanser", "target_paid_count": 3, "target_organic_count": 10, "target_tiktok_count": 6}
      ]
    }
    """

    allocations = parse_keyword_allocations(
        text, expected_paid_total=10, expected_organic_total=30, expected_tiktok_total=20
    )

    assert [allocation.keyword_text for allocation in allocations] == [
        "cleanser",
        "gentle cleanser",
        "sensitive skin cleanser",
    ]
    assert sum(allocation.target_paid_count for allocation in allocations) == 10
    assert sum(allocation.target_organic_count for allocation in allocations) == 30
    assert sum(allocation.target_tiktok_count for allocation in allocations) == 20


def test_parse_keyword_allocations_rejects_wrong_totals() -> None:
    text = """
    {
      "keywords": [
        {"keyword_text": "cleanser", "target_paid_count": 1, "target_organic_count": 10, "target_tiktok_count": 10},
        {"keyword_text": "gentle cleanser", "target_paid_count": 1, "target_organic_count": 10, "target_tiktok_count": 10},
        {"keyword_text": "sensitive skin cleanser", "target_paid_count": 1, "target_organic_count": 10, "target_tiktok_count": 10}
      ]
    }
    """

    with pytest.raises(RuntimeError, match="paid allocation total"):
        parse_keyword_allocations(
            text, expected_paid_total=10, expected_organic_total=30, expected_tiktok_total=30
        )


def test_allocate_manual_keywords_splits_targets_exactly() -> None:
    allocations = allocate_manual_keywords(
        ["cleanser", "gentle cleanser", "skincare routine"],
        target_paid_count=10,
        target_organic_count=31,
        keyword_type="seed",
    )

    assert [allocation.target_paid_count for allocation in allocations] == [4, 3, 3]
    assert [allocation.target_organic_count for allocation in allocations] == [11, 10, 10]
    assert sum(allocation.target_paid_count for allocation in allocations) == 10
    assert sum(allocation.target_organic_count for allocation in allocations) == 31
    assert all(allocation.source == "manual" for allocation in allocations)
