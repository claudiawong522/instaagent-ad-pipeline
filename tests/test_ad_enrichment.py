from __future__ import annotations

from pathlib import Path
from typing import Any

from instaagent_pipeline.ad_enrichment import (
    ENRICHMENT_SCHEMA,
    PaidAdEnrichmentCandidate,
    enrich_paid_ad,
    enrich_paid_ads,
    is_probable_video_url,
    openrouter_request_body,
    paid_ad_enrichment_candidates,
    parse_enrichment_response,
)
from instaagent_pipeline.config import Config
from instaagent_pipeline.http_client import HttpClientError


FIXTURE = Path("tests/fixtures/openrouter_enrichment_success.json")
FBCDN_URL = "https://video-iad3-1.xx.fbcdn.net/v/t42.1790-2/ad_video.mp4?_nc_oc=abc&oe=12345"


def make_config(**overrides: Any) -> Config:
    defaults: dict[str, Any] = {
        "supabase_url": None,
        "supabase_key": None,
        "topyappers_api_key": None,
        "topyappers_base_url": "https://api.topyappers.com",
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


def test_parse_enrichment_response_rejects_invalid_json() -> None:
    body = {"choices": [{"message": {"content": "not json"}}]}
    try:
        parse_enrichment_response(body)
    except RuntimeError as exc:
        assert "invalid JSON" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_parse_enrichment_response_handles_content_part_lists() -> None:
    body = {"choices": [{"message": {"content": [{"type": "text", "text": "{\"transcript_text\": null}"}]}}]}

    assert parse_enrichment_response(body) == {"transcript_text": None}


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
    assert [candidate.paid_ad_row_id for candidate in candidates] == ["row_1"]
    assert candidates[0].ad_copy == {"headline": "Gentle cleanser"}


def test_enrich_paid_ad_writes_transcript_then_updates_paid_ads() -> None:
    supabase = FakeSupabase()

    written = enrich_paid_ad(
        config=make_config(),
        supabase=supabase,  # type: ignore[arg-type]
        run_id="run_1",
        candidate=PaidAdEnrichmentCandidate(
            paid_ad_row_id="row_1",
            ad_archive_id="ad_1",
            video_url=FBCDN_URL,
            ad_copy={"headline": "Gentle cleanser"},
        ),
        input_json=FIXTURE,
        timeout=300,
    )

    assert written is True
    assert [insert[0] for insert in supabase.inserts] == ["source_queries", "raw_payloads"]

    assert len(supabase.upserts) == 1
    table, payload, conflict = supabase.upserts[0]
    assert table == "paid_ad_transcripts"
    assert conflict == "paid_ad_row_id,transcript_source"
    assert payload["paid_ad_row_id"] == "row_1"
    assert payload["transcript_source"] == "openrouter:google/gemini-3-flash"
    assert payload["transcript_text"].startswith("I switched to this gentle cleanser")
    assert payload["transcript_segments"][0] == {
        "start": 0.0,
        "end": 3.2,
        "text": "I switched to this gentle cleanser",
    }

    assert len(supabase.column_updates) == 1
    table, column, value, update = supabase.column_updates[0]
    assert (table, column, value) == ("paid_ads", "paid_ad_row_id", "row_1")
    assert update["hook"] == "I switched to this gentle cleanser"
    assert update["persona"] == "sensitive-skin skincare beginner"
    assert update["target_demographic"] == "women 25-34 with sensitive skin"
    assert update["has_face"] is True
    assert update["emotional_drivers"] == ["relief", "social proof"]
    assert update["analysis_model"] == "google/gemini-3-flash"
    assert update["analyzed_at"]
    assert "transcript_text" not in update
    assert "transcript_segments" not in update


def test_enrich_paid_ad_falls_back_to_insert_when_unique_index_is_missing() -> None:
    supabase = FakeSupabase(
        upsert_error=HttpClientError(
            "HTTP 400",
            status=400,
            body={"message": "there is no unique or exclusion constraint matching the ON CONFLICT specification"},
        )
    )

    written = enrich_paid_ad(
        config=make_config(),
        supabase=supabase,  # type: ignore[arg-type]
        run_id="run_1",
        candidate=PaidAdEnrichmentCandidate(
            paid_ad_row_id="row_1",
            ad_archive_id="ad_1",
            video_url=FBCDN_URL,
        ),
        input_json=FIXTURE,
        timeout=300,
    )

    assert written is True
    assert [insert[0] for insert in supabase.inserts] == [
        "source_queries",
        "raw_payloads",
        "paid_ad_transcripts",
    ]
    assert len(supabase.column_updates) == 1


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
        fail_update_for={"row_1"},
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
    ) -> None:
        self.select_rows = select_rows or {}
        self.upsert_error = upsert_error
        self.fail_update_for = fail_update_for or set()
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
        self.upserts.append((table, payload, conflict_columns))
        return {"id": f"{table}_id", **payload}
