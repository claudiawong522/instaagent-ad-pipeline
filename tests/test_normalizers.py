from __future__ import annotations

import json
from pathlib import Path

from instaagent_pipeline.ingestion import complete_query, log_api_usage
from instaagent_pipeline.keywords import claude_provider
from instaagent_pipeline.normalizers import normalize_apify_ad, result_items


def test_normalize_apify_ad_maps_actual_response_fields() -> None:
    body = json.loads(Path("tests/fixtures/apify_ads.json").read_text())
    item = result_items(body)[0]

    normalized = normalize_apify_ad(item, "run_1", "raw_1")

    assert set(normalized) == {
        "run_id",
        "raw_payload_id",
        "id",
        "live",
        "name",
        "type",
        "ad_id",
        "cards",
        "image",
        "video",
        "avatar",
        "brand_id",
        "cta_type",
        "headline",
        "link_url",
        "cta_title",
        "languages",
        "thumbnail",
        "categories",
        "description",
        "display_format",
        "video_duration",
        "started_running",
        "running_duration",
        "publisher_platform",
        "source_metrics",
    }
    # Keys dropped in the Foreplay→Apify refactor must no longer be emitted.
    for removed_key in (
        "niches",
        "persona",
        "market_target",
        "content_filter",
        "emotional_drivers",
        "creative_targeting",
        "full_transcription",
        "timestamped_transcription",
        "time_product_was_mentioned",
        "product_category",
    ):
        assert removed_key not in normalized
    assert normalized["id"] == "1204694134935316"
    assert normalized["ad_id"] == "1204694134935316"
    assert normalized["name"] == "QE Skincare"
    assert normalized["type"] == "VIDEO"
    assert normalized["brand_id"] == "14226545351"
    assert normalized["description"] == "A gentle cleanser for sensitive skin."
    assert normalized["link_url"] == "https://example.com/qe-cleanser"
    assert normalized["video"] == "https://example.com/qe-cleanser.mp4"
    assert normalized["image"] == "https://example.com/qe-cleanser.jpg"
    assert normalized["thumbnail"] == "https://example.com/qe-cleanser-preview.jpg"
    assert normalized["avatar"] == "https://example.com/avatar.jpg"
    assert normalized["publisher_platform"] == ["FACEBOOK", "INSTAGRAM"]
    assert normalized["started_running"] == 1767600000000
    assert normalized["running_duration"] == 21.0
    assert normalized["source_metrics"]["inputUrl"].startswith("https://www.facebook.com/ads/library/")
    assert normalized["source_metrics"]["snapshot"]["pageName"] == "QE Skincare"


class RecordingSupabase:
    def __init__(self) -> None:
        self.inserts: list[tuple[str, dict]] = []
        self.updates: list[tuple[str, str, dict]] = []

    def insert(self, table: str, payload: dict) -> dict:
        self.inserts.append((table, payload))
        return {"id": "usage_1", **payload}

    def update_by_id(self, table: str, row_id: str, payload: dict) -> dict:
        self.updates.append((table, row_id, payload))
        return {"id": row_id, **payload}


def test_log_api_usage_records_status_counts_and_rate_limit_headers() -> None:
    supabase = RecordingSupabase()

    log_api_usage(
        supabase=supabase,  # type: ignore[arg-type]
        dry_run=False,
        run_id="run_1",
        provider="topyappers",
        endpoint="/api/v1/viral-content",
        status=200,
        response_count=10,
        headers={
            "X-RateLimit-Remaining": "42",
            "X-Credits-Used": "3.5",
            "Content-Type": "application/json",
        },
    )

    assert supabase.inserts == [
        (
            "api_usage",
            {
                "run_id": "run_1",
                "provider": "topyappers",
                "endpoint": "/api/v1/viral-content",
                "credits_used": 3.5,
                "rate_limit": {
                    "http_status": 200,
                    "response_count": 10,
                    "headers": {
                        "X-RateLimit-Remaining": "42",
                        "X-Credits-Used": "3.5",
                    },
                },
            },
        )
    ]


def test_log_api_usage_skips_dry_run_and_fixture_responses() -> None:
    supabase = RecordingSupabase()

    log_api_usage(
        supabase=supabase,  # type: ignore[arg-type]
        dry_run=True,
        run_id="run_1",
        provider="apify:apify/facebook-ads-scraper",
        endpoint="/acts/apify~facebook-ads-scraper/run-sync-get-dataset-items",
        status=200,
        response_count=1,
        headers={},
    )
    log_api_usage(
        supabase=supabase,  # type: ignore[arg-type]
        dry_run=False,
        run_id="run_1",
        provider="apify:apify/facebook-ads-scraper",
        endpoint="/acts/apify~facebook-ads-scraper/run-sync-get-dataset-items",
        status=None,
        response_count=1,
        headers={},
    )

    assert supabase.inserts == []


def test_complete_query_records_success_status_and_http_status() -> None:
    supabase = RecordingSupabase()

    complete_query(
        supabase=supabase,  # type: ignore[arg-type]
        dry_run=False,
        source_query_id="query_1",
        response_count=4,
        http_status=200,
    )

    assert supabase.updates == [
        (
            "source_queries",
            "query_1",
            {
                "status": "completed",
                "response_count": 4,
                "completed_at": supabase.updates[0][2]["completed_at"],
                "http_status": 200,
            },
        )
    ]


def test_claude_provider_uses_provider_model_shape() -> None:
    assert claude_provider("claude-haiku-4-5") == "claude:claude-haiku-4-5"
    assert claude_provider("haiku45") == "claude:haiku45"
