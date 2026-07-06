"""Endpoint-level tests for the FastAPI app: routing, validation, and response shaping
against a stub Supabase (no network)."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from instaagent_pipeline.api.app import create_app


class StubSupabase:
    """Returns canned rows per table; records nothing. Enough for the read endpoints."""

    def __init__(self, rows: dict[str, list[dict[str, Any]]] | None = None) -> None:
        self.rows = rows or {}

    def select(self, table: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        return self.rows.get(table, [])

    def select_by_ids(self, table: str, id_column: str, ids: list[str], columns: str) -> dict[str, dict[str, Any]]:
        if not ids:
            return {}
        return {
            str(row.get(id_column)): row
            for row in self.rows.get(table, [])
            if str(row.get(id_column)) in ids
        }

    def rpc(self, fn: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        return []


def make_client(supabase: StubSupabase | None) -> TestClient:
    app = create_app()
    app.state.supabase = supabase
    return TestClient(app)


def test_health() -> None:
    client = make_client(None)
    assert client.get("/health").json() == {"status": "ok"}


def test_endpoints_return_503_when_supabase_unconfigured() -> None:
    client = make_client(None)
    for method, path, body in [
        ("get", "/runs", None),
        ("get", "/campaigns", None),
        ("get", "/trends/formats", None),
        ("post", "/search", {"query": "x"}),
    ]:
        response = getattr(client, method)(path, json=body) if body else getattr(client, method)(path)
        assert response.status_code == 503, path


def test_search_rejects_unknown_item_type() -> None:
    client = make_client(StubSupabase())
    response = client.post("/search", json={"query": "x", "item_type": "banana"})
    assert response.status_code == 400
    assert "item_type" in response.json()["detail"]


def test_runs_and_campaigns_share_run_listing_but_shape_differently() -> None:
    rows = {
        "pipeline_runs": [
            {
                "id": "r1",
                "status": "created",
                "config": {"campaign_name": "Camp", "marketing_goals": ["Sales"]},
                "product_id": "p1",
                "target_paid_count": 10,
                "target_organic_count": 20,
                "target_tiktok_count": 30,
                "created_at": "2026-07-01T00:00:00Z",
            },
            {
                "id": "r2",
                "status": "created",
                "config": {"discovery": True, "campaign_name": "Viral Discovery"},
                "product_id": "p2",
                "created_at": "2026-07-02T00:00:00Z",
            },
        ],
        "products": [
            {"id": "p1", "name": "Cleanser", "category": "skincare"},
            {"id": "p2", "name": "Viral Discovery", "category": None},
        ],
    }
    client = make_client(StubSupabase(rows))

    runs = client.get("/runs").json()["runs"]
    assert [r["run_id"] for r in runs] == ["r1", "r2"]
    assert runs[0]["campaign_name"] == "Camp"
    assert runs[1]["discovery"] is True  # search filter flags the discovery run

    campaigns = client.get("/campaigns").json()["campaigns"]
    # ...while the campaigns page hides it entirely.
    assert [c["run_id"] for c in campaigns] == ["r1"]
    assert campaigns[0]["product_name"] == "Cleanser"
    assert campaigns[0]["target_organic_count"] == 20


def test_trends_formats_groups_videos_and_ranks_by_views() -> None:
    rows = {
        "viral_formats": [
            {"id": "f1", "format_name": "Quiet fmt", "created_at": "2026-07-01"},
            {"id": "f2", "format_name": "Loud fmt", "created_at": "2026-07-02"},
        ],
        "organic_items": [
            {"id": "v1", "format_id": "f1", "views": 100, "video_url": "u1", "source_metrics": {}},
            {"id": "v2", "format_id": "f2", "views": 900, "video_url": "u2", "source_metrics": {}},
        ],
    }
    client = make_client(StubSupabase(rows))
    formats = client.get("/trends/formats").json()["formats"]
    assert [f["id"] for f in formats] == ["f2", "f1"]  # aggregate views, descending
    assert formats[0]["video_count"] == 1
    assert formats[0]["videos"][0]["video_url"] == "u2"

    # min_views drops formats whose example videos don't clear the bar.
    filtered = client.get("/trends/formats", params={"min_views": 500}).json()["formats"]
    assert [f["id"] for f in filtered] == ["f2"]


def test_trends_match_empty_product_short_circuits() -> None:
    client = make_client(StubSupabase())
    assert client.post("/trends/match", json={"product": "  "}).json() == {"formats": []}


def test_scrape_rejects_unknown_platform() -> None:
    client = make_client(StubSupabase())
    response = client.post("/campaigns/r1/scrape", json={"platform": "myspace"})
    assert response.status_code == 400
    assert "unknown platform" in response.json()["detail"]


def test_discover_scrape_validates_region() -> None:
    client = make_client(StubSupabase())
    assert client.post("/discover/scrape", json={"region": "USA"}).status_code == 422
