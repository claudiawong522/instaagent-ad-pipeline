from __future__ import annotations

import json
from typing import Any

from instaagent_pipeline import openrouter as openrouter_module
from instaagent_pipeline.api import match as match_module
from instaagent_pipeline.config import Config


def make_config() -> Config:
    return Config(
        supabase_url=None,
        supabase_key=None,
        apify_api_key=None,
        claude_api_key=None,
        claude_model="claude-haiku-4-5",
        openrouter_api_key="or-key",
        voyage_api_key=None,  # small corpus → no embedding/recall call
    )


class FakeSupabase:
    def __init__(self, formats: list[dict[str, Any]]) -> None:
        self._formats = formats
        self.rpc_calls: list[tuple[str, dict[str, Any]]] = []

    def rpc(self, fn: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        self.rpc_calls.append((fn, params))
        return []

    def select(self, table: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        if table == "viral_formats":
            return self._formats
        if table == "ugc_items":
            return [
                {
                    "id": "v1",
                    "format_id": "f1",
                    "storage_video_url": "https://store/v1.mp4",
                    "views": 500_000,
                    "likes": 12_000,
                    "handle": "creator1",
                    "enrichment_status": "done",
                    "source_metrics": {"page_url": "https://tiktok.com/@creator1/video/1"},
                }
            ]
        return []


FORMATS = [
    {
        "id": "f1",
        "format_name": "ASMR unboxing",
        "format_description": "Slow close-mic reveal.",
        "versatility": "broad",
        "fit_niches": ["beauty", "food"],
        "product_requirements": ["a satisfying physical action"],
        "niche_constraint": "Any tactile product.",
    },
    {
        "id": "f2",
        "format_name": "Before/after glow",
        "format_description": "Split-screen transformation.",
        "versatility": "niche",
        "fit_niches": ["skincare"],
        "product_requirements": ["a visible before/after"],
        "niche_constraint": "Skincare only.",
    },
]


def _judge_body(matches: list[dict[str, Any]]) -> dict[str, Any]:
    return {"choices": [{"message": {"content": json.dumps({"matches": matches})}}]}


def test_match_product_ranks_by_score_and_hydrates(monkeypatch):
    captured: dict[str, Any] = {}

    def fake_request_json(method, url, *, headers=None, body=None, timeout=60, **kwargs):
        captured["body"] = body
        return type("R", (), {"body": _judge_body([
            {"format_id": "f1", "fit": "great", "score": 88, "idea": "Pop one gummy, mic close."},
            {"format_id": "f2", "fit": "no", "score": 10, "idea": ""},
        ])})()

    monkeypatch.setattr(openrouter_module, "request_json", fake_request_json)
    supabase = FakeSupabase(FORMATS)

    out = match_module.match_product(make_config(), supabase, product="magnesium sleep gummy")

    # Ranked by score: the great fit first, the "no" fit last.
    assert [f["id"] for f in out] == ["f1", "f2"]
    assert out[0]["fit"] == "great" and out[0]["score"] == 88
    assert out[0]["idea"] == "Pop one gummy, mic close."
    assert out[0]["versatility"] == "broad"
    # Example videos hydrated onto the matched format.
    assert out[0]["video_count"] == 1 and out[0]["videos"][0]["id"] == "v1"
    assert out[1]["fit"] == "no"
    # Small corpus → no vector recall RPC was needed.
    assert supabase.rpc_calls == []
    # The judge prompt fed the structured requirement, not raw prose.
    assert "a satisfying physical action" in captured["body"]["messages"][0]["content"]


def test_match_product_defaults_missing_verdict_to_no(monkeypatch):
    def fake_request_json(method, url, *, headers=None, body=None, timeout=60, **kwargs):
        # Judge only scored f1; f2 omitted entirely.
        return type("R", (), {"body": _judge_body([
            {"format_id": "f1", "fit": "workable", "score": 55, "idea": "Show the texture."},
        ])})()

    monkeypatch.setattr(openrouter_module, "request_json", fake_request_json)
    out = match_module.match_product(make_config(), FakeSupabase(FORMATS), product="a phone case")

    by_id = {f["id"]: f for f in out}
    assert by_id["f1"]["fit"] == "workable"
    assert by_id["f2"]["fit"] == "no" and by_id["f2"]["score"] == 0


def test_match_product_empty_query_returns_empty():
    out = match_module.match_product(make_config(), FakeSupabase(FORMATS), product="   ")
    assert out == []


def test_candidates_blend_reserves_universals_but_recall_fills_majority(monkeypatch):
    # Above the pool: 35 universal + 5 niche formats. Recall surfaces the 5 niche ones.
    by_id = {}
    for i in range(35):
        by_id[f"u{i}"] = {"id": f"u{i}", "versatility": "universal"}
    for i in range(5):
        by_id[f"n{i}"] = {"id": f"n{i}", "versatility": "niche"}
    assert len(by_id) > match_module.JUDGE_POOL

    cfg = Config(supabase_url=None, supabase_key=None, apify_api_key=None,
                 claude_api_key=None, claude_model="claude-haiku-4-5",
                 openrouter_api_key="or-key", voyage_api_key="voyage-key")
    monkeypatch.setattr(match_module, "embed_query", lambda config, q: [0.0])

    class RecallSupabase:
        def rpc(self, fn, params):
            return [{"item_id": f"n{i}"} for i in range(5)]  # niche formats are the relevant ones

    picks = match_module._candidates(cfg, RecallSupabase(), "a niche product", by_id)

    assert len(picks) == match_module.JUDGE_POOL
    # Every recalled (relevant) niche format is judged — universals must not crowd them out.
    assert {"n0", "n1", "n2", "n3", "n4"}.issubset(set(picks))
    # Universals are present too, but capped near the reserve + backfill, not the whole pool.
    universal_picked = sum(1 for p in picks if p.startswith("u"))
    assert universal_picked == match_module.JUDGE_POOL - 5
