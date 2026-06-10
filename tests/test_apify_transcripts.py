from __future__ import annotations

from pathlib import Path
from typing import Any

from instaagent_pipeline.apify_transcripts import (
    ANOXVANZI_TRANSCRIPT_SOURCE,
    TOPYAPPERS_TRANSCRIPT_SOURCE,
    UGCTranscriptCandidate,
    apify_dataset_items,
    backfill_ugc_transcripts_from_provider_subtitles,
    is_supported_social_video_url,
    parse_timestamped_transcript,
    transcribe_candidate,
    transcript_text_and_segments,
    ugc_transcript_candidates,
)
from instaagent_pipeline.config import Config
from instaagent_pipeline.http_client import HttpClientError


def test_parse_timestamped_transcript_returns_segments() -> None:
    segments = parse_timestamped_transcript(
        "[0.00s - 2.50s] Welcome to my channel! [2.50s - 8.10s] Today I'm testing this cleanser."
    )

    assert segments == [
        {"start": 0.0, "end": 2.5, "text": "Welcome to my channel!"},
        {"start": 2.5, "end": 8.1, "text": "Today I'm testing this cleanser."},
    ]


def test_transcript_text_and_segments_returns_clean_text() -> None:
    text, segments = transcript_text_and_segments(
        {
            "transcript": (
                "[0.00s - 2.50s] Welcome to my channel! "
                "[2.50s - 8.10s] Today I'm testing this cleanser."
            )
        }
    )

    assert text == "Welcome to my channel! Today I'm testing this cleanser."
    assert segments == [
        {"start": 0.0, "end": 2.5, "text": "Welcome to my channel!"},
        {"start": 2.5, "end": 8.1, "text": "Today I'm testing this cleanser."},
    ]


def test_supported_social_video_url_matches_current_missing_platforms() -> None:
    assert is_supported_social_video_url("https://www.instagram.com/reel/abc/")
    assert is_supported_social_video_url("https://www.tiktok.com/@creator/video/123")
    assert is_supported_social_video_url("https://youtube.com/shorts/abc")
    assert not is_supported_social_video_url("https://cdn.example.com/video.mp4")


def test_apify_dataset_items_accepts_list_and_wrapped_items() -> None:
    assert apify_dataset_items([{"status": "success"}]) == [{"status": "success"}]
    assert apify_dataset_items({"items": [{"status": "success"}]}) == [{"status": "success"}]


def test_ugc_transcript_candidates_skip_existing_and_unsupported() -> None:
    supabase = FakeSupabase(
        select_rows={
            "ugc_items": [
                {
                    "id": "ugc_1",
                    "external_id": "ext_1",
                    "source": "instagram",
                    "video_url": "https://www.instagram.com/reel/abc/",
                    "subtitles": None,
                },
                {
                    "id": "ugc_2",
                    "external_id": "ext_2",
                    "source": "tiktok",
                    "video_url": "https://www.tiktok.com/@creator/video/123",
                    "subtitles": None,
                },
                {
                    "id": "ugc_3",
                    "external_id": "ext_3",
                    "source": "unknown",
                    "video_url": "https://cdn.example.com/video.mp4",
                    "subtitles": None,
                },
            ],
            "ugc_transcripts": [{"ugc_item_id": "ugc_1"}],
        }
    )

    candidates, skipped_existing, skipped_unsupported = ugc_transcript_candidates(
        supabase,  # type: ignore[arg-type]
        run_id="run_1",
        limit=10,
    )

    assert candidates == [
        UGCTranscriptCandidate(
            ugc_item_id="ugc_2",
            external_id="ext_2",
            source="tiktok",
            video_url="https://www.tiktok.com/@creator/video/123",
        )
    ]
    assert skipped_existing == 1
    assert skipped_unsupported == 1


def test_backfill_provider_subtitles_copies_topyappers_subtitles() -> None:
    supabase = FakeSupabase(
        select_rows={
            "ugc_items": [
                {
                    "id": "ugc_1",
                    "external_id": "ext_1",
                    "subtitles": "Provider subtitle text.",
                },
                {
                    "id": "ugc_2",
                    "external_id": "ext_2",
                    "subtitles": "Already copied.",
                },
            ],
            "ugc_transcripts": [{"ugc_item_id": "ugc_2"}],
        }
    )

    result = backfill_ugc_transcripts_from_provider_subtitles(
        supabase=supabase,  # type: ignore[arg-type]
        run_id="run_1",
        limit=10,
        dry_run=False,
    )

    assert result.candidates == 1
    assert result.written == 1
    assert result.skipped_existing == 1
    assert supabase.upserts == [
        (
            "ugc_transcripts",
            {
                "ugc_item_id": "ugc_1",
                "transcript_text": "Provider subtitle text.",
                "transcript_segments": None,
                "transcript_source": TOPYAPPERS_TRANSCRIPT_SOURCE,
            },
            "ugc_item_id,transcript_source",
        )
    ]


def test_transcribe_candidate_writes_raw_payload_then_upserts_transcript() -> None:
    supabase = FakeSupabase()

    written = transcribe_candidate(
        config=Config(
            supabase_url=None,
            supabase_key=None,
            foreplay_api_key=None,
            foreplay_base_url="https://public.api.foreplay.co",
            topyappers_api_key=None,
            topyappers_base_url="https://api.topyappers.com",
            apify_api_key=None,
            claude_api_key=None,
            claude_model="claude-haiku-4-5",
        ),
        supabase=supabase,  # type: ignore[arg-type]
        run_id="run_1",
        candidate=UGCTranscriptCandidate(
            ugc_item_id="ugc_1",
            external_id="ext_1",
            source="tiktok",
            video_url="https://www.tiktok.com/@creator/video/123",
        ),
        input_json=Path("tests/fixtures/apify_anoxvanzi_success.json"),
        timeout=300,
    )

    assert written is True
    assert [insert[0] for insert in supabase.inserts] == ["source_queries", "raw_payloads"]
    assert supabase.upserts == [
        (
            "ugc_transcripts",
            {
                "ugc_item_id": "ugc_1",
                "transcript_text": "Welcome to my channel! Today I'm testing this cleanser.",
                "transcript_segments": [
                    {"start": 0.0, "end": 2.5, "text": "Welcome to my channel!"},
                    {"start": 2.5, "end": 8.1, "text": "Today I'm testing this cleanser."},
                ],
                "transcript_source": ANOXVANZI_TRANSCRIPT_SOURCE,
            },
            "ugc_item_id,transcript_source",
        )
    ]


def test_transcribe_candidate_falls_back_to_insert_when_unique_index_is_missing() -> None:
    supabase = FakeSupabase(
        upsert_error=HttpClientError(
            "HTTP 400",
            status=400,
            body={"message": "there is no unique or exclusion constraint matching the ON CONFLICT specification"},
        )
    )

    written = transcribe_candidate(
        config=Config(
            supabase_url=None,
            supabase_key=None,
            foreplay_api_key=None,
            foreplay_base_url="https://public.api.foreplay.co",
            topyappers_api_key=None,
            topyappers_base_url="https://api.topyappers.com",
            apify_api_key=None,
            claude_api_key=None,
            claude_model="claude-haiku-4-5",
        ),
        supabase=supabase,  # type: ignore[arg-type]
        run_id="run_1",
        candidate=UGCTranscriptCandidate(
            ugc_item_id="ugc_1",
            external_id="ext_1",
            source="tiktok",
            video_url="https://www.tiktok.com/@creator/video/123",
        ),
        input_json=Path("tests/fixtures/apify_anoxvanzi_success.json"),
        timeout=300,
    )

    assert written is True
    assert [insert[0] for insert in supabase.inserts] == [
        "source_queries",
        "raw_payloads",
        "ugc_transcripts",
    ]


class FakeSupabase:
    def __init__(
        self,
        select_rows: dict[str, list[dict[str, Any]]] | None = None,
        upsert_error: HttpClientError | None = None,
    ) -> None:
        self.select_rows = select_rows or {}
        self.upsert_error = upsert_error
        self.inserts: list[tuple[str, dict[str, Any]]] = []
        self.updates: list[tuple[str, str, dict[str, Any]]] = []
        self.upserts: list[tuple[str, dict[str, Any], str]] = []

    def select(self, table: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        return self.select_rows.get(table, [])

    def insert(self, table: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.inserts.append((table, payload))
        return {"id": f"{table}_id", **payload}

    def update_by_id(self, table: str, row_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.updates.append((table, row_id, payload))
        return {"id": row_id, **payload}

    def upsert(self, table: str, payload: dict[str, Any], conflict_columns: str) -> dict[str, Any]:
        if self.upsert_error:
            raise self.upsert_error
        self.upserts.append((table, payload, conflict_columns))
        return {"id": f"{table}_id", **payload}
