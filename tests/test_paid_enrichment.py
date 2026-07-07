from __future__ import annotations

from pathlib import Path
from typing import Any

from instaagent_pipeline.config import Config
from instaagent_pipeline.http_client import HttpClientError
from instaagent_pipeline.media import is_probable_video_url
from instaagent_pipeline.paid_enrichment import (
    PAID_AD_KIND,
    enrich_paid_ads,
    paid_ad_enrichment_candidates,
)
from instaagent_pipeline.video_enrichment import (
    ENRICHMENT_SCHEMA,
    EnrichmentCandidate,
    enrich_item,
    openrouter_request_body,
)


FIXTURE = Path("tests/fixtures/openrouter_enrichment_success.json")
FBCDN_URL = "https://video-iad3-1.xx.fbcdn.net/v/t42.1790-2/ad_video.mp4?_nc_oc=abc&oe=12345"


def make_config(**overrides: Any) -> Config:
    defaults: dict[str, Any] = {
        "supabase_url": None,
        "supabase_key": None,
        "apify_api_key": None,
        "claude_api_key": None,
        "claude_model": "claude-haiku-4-5",
        "openrouter_api_key": None,
        "openrouter_model": "google/gemini-3-flash",
    }
    defaults.update(overrides)
    return Config(**defaults)


def test_is_probable_video_url() -> None:
    assert is_probable_video_url(FBCDN_URL) is True
    assert is_probable_video_url("https://example.com/clip.mp4") is True
    assert is_probable_video_url("") is False
    assert is_probable_video_url("not-a-url") is False
    assert is_probable_video_url("ftp://example.com/clip.mp4") is False


def test_openrouter_request_body_sends_base64_data_url_and_schema() -> None:
    body = openrouter_request_body(
        model="google/gemini-3-flash",
        video_bytes=b"abc",
        ad_copy={"headline": "Gentle cleanser"},
    )

    assert body["model"] == "google/gemini-3-flash"
    parts = body["messages"][0]["content"]
    assert parts[0] == {"type": "video_url", "video_url": {"url": "data:video/mp4;base64,YWJj"}}
    assert "Gentle cleanser" in parts[1]["text"]
    response_format = body["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    assert response_format["json_schema"]["schema"] is ENRICHMENT_SCHEMA


def test_openrouter_request_body_prefers_remote_video_url() -> None:
    # A remote URL is passed through verbatim so the provider fetches the video
    # server-side, instead of inlining a base64 data URL.
    body = openrouter_request_body(
        model="google/gemini-3-flash",
        ad_copy={"headline": "Gentle cleanser"},
        video_url="https://storage.example/run/paid/abc.mp4",
        video_bytes=b"abc",
    )
    parts = body["messages"][0]["content"]
    assert parts[0] == {
        "type": "video_url",
        "video_url": {"url": "https://storage.example/run/paid/abc.mp4"},
    }


def test_openrouter_request_body_requires_a_video_source() -> None:
    try:
        openrouter_request_body(model="m", ad_copy={})
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError when neither video_url nor video_bytes given")


def test_paid_ad_enrichment_candidates_skips_bad_urls() -> None:
    supabase = FakeSupabase(
        select_rows={
            "paid_ads": [
                {
                    "paid_ad_row_id": "row_1",
                    "id": "ad_1",
                    "video": FBCDN_URL,
                    "headline": "Gentle cleanser",
                    "description": None,
                },
                {"paid_ad_row_id": "row_2", "id": "ad_2", "video": ""},
                {"paid_ad_row_id": "row_3", "id": "ad_3", "video": "not-a-url"},
            ]
        }
    )

    candidates, skipped_unsupported = paid_ad_enrichment_candidates(
        supabase,  # type: ignore[arg-type]
        run_id="run_1",
        limit=10,
    )

    assert skipped_unsupported == 2
    assert [candidate.item_id for candidate in candidates] == ["row_1"]
    assert candidates[0].ad_copy == {"headline": "Gentle cleanser"}


def test_paid_ad_enrichment_candidates_skips_already_enriched() -> None:
    # Already-enriched rows are now detected via item_enrichments (item_type/item_id/run_id),
    # not a paid_ads.analyzed_at filter.
    supabase = FakeSupabase(
        select_rows={
            "paid_ads": [
                {"paid_ad_row_id": "row_1", "id": "ad_1", "video": FBCDN_URL},
                {"paid_ad_row_id": "row_2", "id": "ad_2", "video": FBCDN_URL},
            ],
            "item_enrichments": [{"item_id": "row_1"}],
        }
    )

    candidates, skipped_unsupported = paid_ad_enrichment_candidates(
        supabase,  # type: ignore[arg-type]
        run_id="run_1",
        limit=10,
    )

    assert skipped_unsupported == 0
    assert [candidate.item_id for candidate in candidates] == ["row_2"]


def test_enrich_paid_ad_writes_single_item_enrichment_upsert() -> None:
    supabase = FakeSupabase()

    written = enrich_item(
        config=make_config(),
        supabase=supabase,  # type: ignore[arg-type]
        run_id="run_1",
        kind=PAID_AD_KIND,
        candidate=EnrichmentCandidate(
            item_id="row_1",
            external_id="ad_1",
            extra_ids={"ad_archive_id": "ad_1"},
            video_url=FBCDN_URL,
            ad_copy={"headline": "Gentle cleanser"},
        ),
        input_json=FIXTURE,
        timeout=300,
    )

    assert written is True
    assert [insert[0] for insert in supabase.inserts] == ["source_queries", "raw_payloads"]

    # Analysis + transcript now land in a single polymorphic item_enrichments upsert.
    assert len(supabase.upserts) == 1
    table, payload, conflict = supabase.upserts[0]
    assert table == "item_enrichments"
    assert conflict == "item_type,item_id"

    # Polymorphic identity + bookkeeping.
    assert payload["item_type"] == "paid_ad"
    assert payload["item_id"] == "row_1"
    assert payload["run_id"] == "run_1"
    assert payload["analysis_model"] == "google/gemini-3-flash"
    assert payload["analyzed_at"]

    # Transcript now lives on the enrichment row, not a separate table.
    assert payload["transcript_text"].startswith("I switched to this gentle cleanser")
    assert payload["transcript_segments"][0] == {
        "start": 0.0,
        "end": 3.2,
        "text": "I switched to this gentle cleanser",
    }

    # Analysis fields from the trimmed schema.
    assert payload["hook"] == "I switched to this gentle cleanser"
    assert payload["persona"] == "sensitive-skin skincare beginner"
    assert payload["target_demographic"] == "women 25-34 with sensitive skin"
    assert payload["emotional_drivers"] == ["relief", "social proof"]
    assert "has_face" not in payload  # dropped from the trimmed schema
    assert "race" not in payload  # dropped from the trimmed schema

    # The only row-column write is the per-video enrichment outcome (searchable), so the
    # UI can show how many scraped videos became searchable vs expired/failed.
    assert supabase.column_updates == [
        ("paid_ads", "paid_ad_row_id", "row_1", {"enrichment_status": "enriched", "enrichment_error": None})
    ]
    assert all(insert[0] != "paid_ad_transcripts" for insert in supabase.inserts)


def test_enrich_paid_ads_dry_run_lists_candidates_without_writing() -> None:
    supabase = FakeSupabase(
        select_rows={
            "paid_ads": [
                {"paid_ad_row_id": "row_1", "id": "ad_1", "video": FBCDN_URL},
            ]
        }
    )

    result = enrich_paid_ads(
        config=make_config(),
        supabase=supabase,  # type: ignore[arg-type]
        run_id="run_1",
        limit=5,
        dry_run=True,
    )

    assert result.candidates == 1
    assert result.details == [
        {
            "paid_ad_row_id": "row_1",
            "ad_archive_id": "ad_1",
            "video_url": FBCDN_URL,
            "action": "would_enrich",
        }
    ]
    assert supabase.inserts == []
    assert supabase.upserts == []
    assert supabase.column_updates == []


def test_enrich_paid_ads_continues_after_single_failure() -> None:
    supabase = FakeSupabase(
        select_rows={
            "paid_ads": [
                {"paid_ad_row_id": "row_1", "id": "ad_1", "video": FBCDN_URL},
                {"paid_ad_row_id": "row_2", "id": "ad_2", "video": FBCDN_URL},
            ]
        },
        fail_upsert_for={"row_1"},
    )

    result = enrich_paid_ads(
        config=make_config(),
        supabase=supabase,  # type: ignore[arg-type]
        run_id="run_1",
        limit=5,
        dry_run=False,
        input_json=FIXTURE,
    )

    assert result.attempted == 2
    assert result.written == 1
    assert result.failed == 1
    statuses = {detail["paid_ad_row_id"]: detail["status"] for detail in result.details}
    assert statuses == {"row_1": "failed", "row_2": "written"}


class FakeSupabase:
    def __init__(
        self,
        select_rows: dict[str, list[dict[str, Any]]] | None = None,
        upsert_error: HttpClientError | None = None,
        fail_update_for: set[str] | None = None,
        fail_upsert_for: set[str] | None = None,
    ) -> None:
        self.select_rows = select_rows or {}
        self.upsert_error = upsert_error
        self.fail_update_for = fail_update_for or set()
        self.fail_upsert_for = fail_upsert_for or set()
        self.inserts: list[tuple[str, dict[str, Any]]] = []
        self.upserts: list[tuple[str, dict[str, Any], str]] = []
        self.updates: list[tuple[str, str, dict[str, Any]]] = []
        self.column_updates: list[tuple[str, str, str, dict[str, Any]]] = []

    def select(self, table: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        return self.select_rows.get(table, [])

    def insert(self, table: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.inserts.append((table, payload))
        return {"id": f"{table}_id", **payload}

    def update_by_id(self, table: str, row_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.updates.append((table, row_id, payload))
        return {"id": row_id, **payload}

    def update_by_column(self, table: str, column: str, value: str, payload: dict[str, Any]) -> dict[str, Any]:
        if value in self.fail_update_for:
            raise HttpClientError("HTTP 500", status=500, body={"message": "boom"})
        self.column_updates.append((table, column, value, payload))
        return {column: value, **payload}

    def upsert(self, table: str, payload: dict[str, Any], conflict_columns: str) -> dict[str, Any]:
        if self.upsert_error:
            raise self.upsert_error
        if str(payload.get("item_id")) in self.fail_upsert_for:
            raise HttpClientError("HTTP 500", status=500, body={"message": "boom"})
        self.upserts.append((table, payload, conflict_columns))
        return {"id": f"{table}_id", **payload}
