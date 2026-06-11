from __future__ import annotations

import json
from pathlib import Path

from instaagent_pipeline.ingestion import complete_query, log_api_usage
from instaagent_pipeline.keywords import KeywordAllocation, KeywordGenerationResult, claude_provider, log_claude_keyword_usage
from instaagent_pipeline.normalizers import normalize_apify_ad, normalize_topyappers_item, result_items


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
        "niches",
        "persona",
        "brand_id",
        "cta_type",
        "headline",
        "link_url",
        "cta_title",
        "languages",
        "thumbnail",
        "categories",
        "description",
        "market_target",
        "content_filter",
        "display_format",
        "video_duration",
        "started_running",
        "product_category",
        "running_duration",
        "emotional_drivers",
        "creative_targeting",
        "full_transcription",
        "publisher_platform",
        "timestamped_transcription",
        "time_product_was_mentioned",
        "source_metrics",
    }
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
    assert normalized["full_transcription"] is None
    assert normalized["source_metrics"]["inputUrl"].startswith("https://www.facebook.com/ads/library/")
    assert normalized["source_metrics"]["snapshot"]["pageName"] == "QE Skincare"


def test_normalize_topyappers_video_leaves_video_url_empty_when_endpoint_omits_it() -> None:
    body = json.loads(Path("tests/fixtures/topyappers_videos.json").read_text())
    item = result_items(body)[0]

    normalized = normalize_topyappers_item(item, "run_1", "raw_1", endpoint_kind="videos")

    assert normalized["external_id"] == "video_test_1"
    assert normalized["iv_id"] == "video_test_1"
    assert normalized["video_id"] == "7280000000"
    assert normalized["video_url"] is None
    assert normalized["views"] == 250000
    assert normalized["subtitles"] == "Gentle cleanser review with sensitive skin."
    assert normalized["source_metrics"] == {"endpoint_kind": "videos"}


def test_normalize_topyappers_viral_maps_url_backed_fields() -> None:
    body = json.loads(Path("tests/fixtures/topyappers_viral.json").read_text())
    item = result_items(body)[0]

    normalized = normalize_topyappers_item(item, "run_1", "raw_1", endpoint_kind="viral-content")

    assert normalized["external_id"] == "ugc_test_1"
    assert normalized["video_url"] == "https://example.com/reel.mp4"
    assert normalized["cover"] == "https://example.com/reel-thumb.jpg"
    assert normalized["description"] == "Trying a gentle cleanser for my skin barrier."
    assert normalized["handle"] == "skincarecreator"
    assert normalized["user_handle"] == "skincarecreator"
    assert normalized["date_created"] == "2026-06-01T00:00:00Z"
    assert normalized["content_category"] == "beauty"
    assert normalized["main_category"] == "beauty"
    assert normalized["music"] == {"title": "Original audio"}
    assert normalized["source"] is None
    assert normalized["source_metrics"]["endpoint_kind"] == "viral-content"
    assert "creatorUsername" not in normalized["source_metrics"]
    assert "caption" not in normalized["source_metrics"]
    assert "musicTitle" not in normalized["source_metrics"]


def test_normalize_topyappers_viral_derives_video_url_when_provider_omits_url() -> None:
    item = {
        "id": "ugc_live_shape_1",
        "source": "tiktok",
        "handle": "skincarecreator",
        "video_id": "7621528611052408086",
        "views": 419300,
    }

    normalized = normalize_topyappers_item(item, "run_1", "raw_1", endpoint_kind="viral-content")

    assert normalized["video_url"] == "https://www.tiktok.com/@skincarecreator/video/7621528611052408086"
    assert normalized["user_handle"] == "skincarecreator"


def test_normalize_topyappers_viral_derives_instagram_url() -> None:
    item = {
        "id": "ugc_live_shape_2",
        "source": "instagram",
        "handle": "skincarecreator",
        "video_id": "p/DY1ZLysRaPk",
        "views": 958533,
    }

    normalized = normalize_topyappers_item(item, "run_1", "raw_1", endpoint_kind="viral-content")

    assert normalized["video_url"] == "https://www.instagram.com/p/DY1ZLysRaPk/"


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


def test_claude_usage_provider_includes_model() -> None:
    supabase = RecordingSupabase()
    result = KeywordGenerationResult(
        allocations=[
            KeywordAllocation(keyword_text="gentle cleanser", target_paid_count=100, target_ugc_count=250),
        ],
        model="claude-haiku-4-5",
        status=200,
        headers={"anthropic-ratelimit-requests-remaining": "49"},
        usage={"input_tokens": 12, "output_tokens": 8},
    )

    log_claude_keyword_usage(
        supabase=supabase,  # type: ignore[arg-type]
        dry_run=False,
        run_id="run_1",
        result=result,
    )

    assert supabase.inserts == [
        (
            "api_usage",
            {
                "run_id": "run_1",
                "provider": "claude-haiku-4-5",
                "endpoint": "/v1/messages",
                "credits_used": None,
                "rate_limit": {
                    "http_status": 200,
                    "response_count": 1,
                    "keyword_count": 1,
                    "model": "claude-haiku-4-5",
                    "usage": {"input_tokens": 12, "output_tokens": 8},
                    "headers": {
                        "anthropic-ratelimit-requests-remaining": "49",
                    },
                },
            },
        )
    ]


def test_claude_provider_prefixes_non_claude_model_names() -> None:
    assert claude_provider("claude-haiku-4-5") == "claude-haiku-4-5"
    assert claude_provider("haiku45") == "claude-haiku45"
