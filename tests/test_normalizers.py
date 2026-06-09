from __future__ import annotations

import json
from pathlib import Path

from instaagent_pipeline.normalizers import normalize_foreplay_ad, normalize_topyappers_item, result_items


def test_normalize_foreplay_ad_maps_actual_response_fields() -> None:
    body = json.loads(Path("tests/fixtures/foreplay_ads.json").read_text())
    item = result_items(body)[0]

    normalized = normalize_foreplay_ad(item, "run_1", "raw_1")

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
    assert normalized["id"] == "ad_test_1"
    assert normalized["ad_id"] == "1234567890"
    assert normalized["name"] == "QE"
    assert normalized["type"] == "video"
    assert normalized["brand_id"] == "brand_test_1"
    assert normalized["description"] == "A gentle cleanser for sensitive skin"
    assert normalized["link_url"] == "https://example.com/qe-cleanser"
    assert normalized["video"] == "https://example.com/video.mp4"
    assert normalized["avatar"] == "https://example.com/avatar.jpg"
    assert normalized["publisher_platform"] == ["instagram"]
    assert normalized["started_running"] == 1714521600000
    assert normalized["video_duration"] == 15.02
    assert normalized["product_category"] == "face cleanser"
    assert normalized["emotional_drivers"] == {"security": 9, "nurturance": 8}
    assert normalized["creative_targeting"] == "skincare enthusiasts"
    assert normalized["time_product_was_mentioned"] == -1.0
    assert normalized["source_metrics"] == {}


def test_normalize_topyappers_video_maps_video_url_column() -> None:
    body = json.loads(Path("tests/fixtures/topyappers_videos.json").read_text())
    item = result_items(body)[0]

    normalized = normalize_topyappers_item(item, "run_1", "raw_1", endpoint_kind="videos")

    assert normalized["external_id"] == "video_test_1"
    assert normalized["iv_id"] == "video_test_1"
    assert normalized["video_id"] == "7280000000"
    assert normalized["video_url"] == "https://example.com/tiktok.mp4"
    assert normalized["views"] == 250000
    assert normalized["subtitles"] == "Gentle cleanser review with sensitive skin."
    assert normalized["source_metrics"] == {"endpoint_kind": "videos"}


def test_normalize_topyappers_viral_keeps_unmapped_fields_in_source_metrics() -> None:
    body = json.loads(Path("tests/fixtures/topyappers_viral.json").read_text())
    item = result_items(body)[0]

    normalized = normalize_topyappers_item(item, "run_1", "raw_1", endpoint_kind="viral-content")

    assert normalized["external_id"] == "ugc_test_1"
    assert normalized["video_url"] == "https://example.com/reel.mp4"
    assert normalized["source_metrics"]["endpoint_kind"] == "viral-content"
    assert normalized["source_metrics"]["creatorUsername"] == "skincarecreator"
    assert normalized["source_metrics"]["caption"] == "Trying a gentle cleanser for my skin barrier."
    assert normalized["source_metrics"]["musicTitle"] == "Original audio"
