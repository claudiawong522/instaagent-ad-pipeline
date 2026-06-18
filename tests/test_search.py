from __future__ import annotations

from typing import Any

import pytest

from instaagent_pipeline.api import search as search_module
from instaagent_pipeline.config import Config


def make_config() -> Config:
    return Config(
        supabase_url=None,
        supabase_key=None,
        topyappers_api_key=None,
        topyappers_base_url="https://x",
        apify_api_key=None,
        claude_api_key=None,
        claude_model="claude-haiku-4-5",
        voyage_api_key="voyage-key",
        embedding_model="voyage-4-lite",
    )


class FakeSupabase:
    def __init__(self) -> None:
        self.rpc_calls: list[tuple[str, dict[str, Any]]] = []

    def rpc(self, fn: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        self.rpc_calls.append((fn, params))
        return [
            {"item_type": "ugc_item", "item_id": "u1", "source_text": "...", "similarity": 0.91},
            {"item_type": "paid_ad", "item_id": "p1", "source_text": "...", "similarity": 0.80},
        ]

    def select(self, table: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        if table == "paid_ads":
            return [
                {
                    "paid_ad_row_id": "p1",
                    "run_id": "r1",
                    "name": "BrandX",
                    "ai_description": "A clean demo of a cleanser.",
                    "publisher_platform": ["facebook"],
                    "storage_video_url": "https://store/p1.mp4",
                    "storage_thumb_url": "https://store/p1.jpg",
                    "hook": "Stop using harsh soap",
                }
            ]
        if table == "ugc_items":
            return [
                {
                    "id": "u1",
                    "run_id": "r1",
                    "handle": "creator1",
                    "source": "tiktok",
                    "followers": 15600,
                    "views": 321200,
                    "likes": 8307,
                    "virality_score": 42.0,
                    "ai_description": "ASMR cleanser pump.",
                    "storage_video_url": "https://store/u1.mp4",
                    "storage_thumb_url": "https://store/u1.jpg",
                    "hook": "Watch this pump",
                }
            ]
        if table == "paid_ad_transcripts":
            return [{"paid_ad_row_id": "p1", "transcript_text": "paid transcript"}]
        if table == "ugc_transcripts":
            return [{"ugc_item_id": "u1", "transcript_text": "ugc transcript"}]
        return []


@pytest.fixture(autouse=True)
def _no_voyage(monkeypatch):
    monkeypatch.setattr(search_module, "embed_query", lambda *a, **k: [0.1, 0.2, 0.3, 0.4])


def test_search_ranks_hydrates_and_attaches_transcripts() -> None:
    supabase = FakeSupabase()
    results = search_module.search_ads(make_config(), supabase, query="cleanser")

    # RPC was called with the pgvector text literal + search space.
    fn, params = supabase.rpc_calls[0]
    assert fn == "match_item_embeddings"
    assert params["p_space"] == "search"
    assert isinstance(params["p_query"], str) and params["p_query"].startswith("[")

    assert [r["item_id"] for r in results] == ["u1", "p1"]  # preserves rank order
    ugc, paid = results
    assert ugc["platform"] == "tiktok"
    assert ugc["video_url"] == "https://store/u1.mp4"
    assert ugc["views"] == 321200
    assert ugc["transcript"] == "ugc transcript"
    assert ugc["similarity"] == 0.91
    assert paid["platform"] == "facebook"
    assert paid["transcript"] == "paid transcript"
    assert paid["views"] is None


def test_platform_filter() -> None:
    results = search_module.search_ads(make_config(), FakeSupabase(), query="x", platform="tiktok")
    assert [r["item_id"] for r in results] == ["u1"]


def test_min_views_filter_drops_paid_without_views() -> None:
    results = search_module.search_ads(make_config(), FakeSupabase(), query="x", min_views=400000)
    assert results == []


def test_item_type_forwarded_to_rpc() -> None:
    supabase = FakeSupabase()
    search_module.search_ads(make_config(), supabase, query="x", item_type="ugc_item")
    assert supabase.rpc_calls[0][1]["p_item_type"] == "ugc_item"
