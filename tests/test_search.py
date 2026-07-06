from __future__ import annotations

from typing import Any

import pytest

from instaagent_pipeline.api import search as search_module
from instaagent_pipeline.config import Config


def make_config() -> Config:
    return Config(
        supabase_url=None,
        supabase_key=None,
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


    def select_by_ids(self, table, id_column, ids, columns):
        if not ids:
            return {}
        rows = self.select(table, {"select": columns, id_column: f"in.({','.join(ids)})", "limit": str(len(ids))})
        return {str(row.get(id_column)): row for row in rows if row.get(id_column)}

    def select(self, table: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        if table == "paid_ads":
            return [
                {
                    "paid_ad_row_id": "p1",
                    "run_id": "r1",
                    "name": "BrandX",
                    "publisher_platform": ["facebook"],
                    "storage_video_url": "https://store/p1.mp4",
                    "storage_thumb_url": "https://store/p1.jpg",
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
                    "storage_video_url": "https://store/u1.mp4",
                    "storage_thumb_url": "https://store/u1.jpg",
                }
            ]
        if table == "item_enrichments":
            # Enrichment fields + transcript now come from item_enrichments,
            # keyed by item_type/item_id.
            if params.get("item_type") == "eq.paid_ad":
                return [
                    {
                        "item_id": "p1",
                        "ai_description": "A clean demo of a cleanser.",
                        "hook": "Stop using harsh soap",
                        "content_format": "demo",
                        "content_formats": ["talking_head", "testimonial"],
                        "product_category": "skincare",
                        "video_topic": "cleanser demo",
                        "transcript_text": "paid transcript",
                    }
                ]
            if params.get("item_type") == "eq.ugc_item":
                return [
                    {
                        "item_id": "u1",
                        "ai_description": "ASMR cleanser pump.",
                        "hook": "Watch this pump",
                        "content_format": "asmr",
                        "content_formats": ["ugc", "asmr"],
                        "product_category": "skincare",
                        "video_topic": "cleanser asmr",
                        "transcript_text": "ugc transcript",
                    }
                ]
            return []
        return []


@pytest.fixture(autouse=True)
def _no_voyage(monkeypatch):
    monkeypatch.setattr(search_module, "embed_query", lambda *a, **k: [0.1, 0.2, 0.3, 0.4])
    # Rerank deterministically: preserve recall order with descending scores above the
    # default 0.5 gate, so tests exercise the gate/pool logic without a network call.
    monkeypatch.setattr(
        search_module,
        "rerank",
        lambda config, query, documents, **k: [(i, 0.9 - 0.05 * i) for i in range(len(documents))],
    )


def test_search_ranks_hydrates_and_attaches_transcripts() -> None:
    supabase = FakeSupabase()
    results = search_module.search_ads(make_config(), supabase, query="cleanser")

    # RPC was called with the pgvector text literal + search space.
    fn, params = supabase.rpc_calls[0]
    assert fn == "match_item_embeddings"
    assert params["p_space"] == "search"
    assert isinstance(params["p_query"], str) and params["p_query"].startswith("[")

    assert [r["item_id"] for r in results] == ["u1", "p1"]  # preserves rank order
    organic, paid = results
    assert organic["platform"] == "tiktok"
    assert organic["video_url"] == "https://store/u1.mp4"
    assert organic["views"] == 321200
    assert organic["similarity"] == 0.9  # now the rerank score, not cosine
    # Enrichment fields + transcript hydrate from item_enrichments (same output keys).
    assert organic["ai_description"] == "ASMR cleanser pump."
    assert organic["hook"] == "Watch this pump"
    assert organic["content_format"] == "asmr"
    assert organic["product_category"] == "skincare"
    assert organic["video_topic"] == "cleanser asmr"
    assert organic["transcript"] == "ugc transcript"
    assert paid["platform"] == "facebook"
    assert paid["ai_description"] == "A clean demo of a cleanser."
    assert paid["hook"] == "Stop using harsh soap"
    assert paid["content_format"] == "demo"
    assert paid["product_category"] == "skincare"
    assert paid["video_topic"] == "cleanser demo"
    assert paid["transcript"] == "paid transcript"
    assert paid["views"] is None
    # Multi-value content_formats hydrates as a list on each result.
    assert organic["content_formats"] == ["ugc", "asmr"]
    assert paid["content_formats"] == ["talking_head", "testimonial"]


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


def test_content_formats_filter_matches_by_overlap() -> None:
    # u1 = [ugc, asmr], p1 = [talking_head, testimonial]. "asmr" overlaps only u1.
    results = search_module.search_ads(
        make_config(), FakeSupabase(), query="x", content_formats=["asmr"]
    )
    assert [r["item_id"] for r in results] == ["u1"]


def test_content_formats_filter_drops_rows_without_match() -> None:
    results = search_module.search_ads(
        make_config(), FakeSupabase(), query="x", content_formats=["meme"]
    )
    assert results == []
