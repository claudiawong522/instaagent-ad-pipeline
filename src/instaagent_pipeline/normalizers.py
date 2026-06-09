from __future__ import annotations

from typing import Any


def result_items(response: Any) -> list[dict[str, Any]]:
    if isinstance(response, list):
        return [item for item in response if isinstance(item, dict)]
    if not isinstance(response, dict):
        return []

    for key in ("data", "results", "items", "videos", "posts", "content"):
        value = response.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]

    nested = response.get("result")
    if isinstance(nested, dict):
        return result_items(nested)

    return []


def first_present(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return None


def nested_first(item: dict[str, Any], *paths: str) -> Any:
    for path in paths:
        current: Any = item
        for part in path.split("."):
            if not isinstance(current, dict):
                current = None
                break
            current = current.get(part)
        if current not in (None, ""):
            return current
    return None


def as_number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().lower().replace(",", "")
        for suffix in ("days", "day", "d"):
            cleaned = cleaned.removesuffix(suffix).strip()
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def normalize_foreplay_ad(item: dict[str, Any], run_id: str, raw_payload_id: str | None) -> dict[str, Any]:
    external_id = str(first_present(item, "id", "ad_id", "adId"))
    brand = nested_first(item, "brand.name", "page.name") or first_present(
        item,
        "brand_name",
        "brandName",
        "page_name",
        "pageName",
        "name",
    )
    media_url = first_present(item, "video", "video_url", "videoUrl", "image", "image_url", "imageUrl")
    caption = first_present(item, "headline", "description", "body", "name", "title")
    running_duration_days = as_number(first_present(item, "running_duration_days", "runningDurationDays", "running_duration"))

    return {
        "run_id": run_id,
        "raw_payload_id": raw_payload_id,
        "source_type": "paid_ad",
        "source_provider": "foreplay",
        "external_id": external_id,
        "url": first_present(item, "link_url", "linkUrl", "url", "share_url", "shareUrl"),
        "media_url": media_url,
        "thumbnail_url": first_present(item, "thumbnail", "thumbnail_url", "thumbnailUrl", "avatar"),
        "creator_or_brand": brand,
        "caption": caption,
        "platform": stringify_if_needed(first_present(item, "publisher_platform", "publisherPlatform")),
        "display_format": stringify_if_needed(first_present(item, "display_format", "displayFormat")),
        "posted_at": first_present(item, "created_at", "createdAt"),
        "started_running_at": first_present(item, "started_running", "startedRunning"),
        "running_duration_days": running_duration_days,
        "source_metrics": {
            "running_duration": first_present(item, "running_duration", "runningDuration"),
            "running_duration_days": running_duration_days,
            "live": first_present(item, "live", "is_live", "isLive"),
            "cta_type": first_present(item, "cta_type", "ctaType"),
            "cta_title": first_present(item, "cta_title", "ctaTitle"),
            "video_duration": first_present(item, "video_duration", "videoDuration"),
            "categories": item.get("categories"),
            "niches": item.get("niches"),
            "languages": item.get("languages"),
            "market_target": first_present(item, "market_target", "marketTarget"),
            "full_transcription": item.get("full_transcription"),
            "timestamped_transcription": item.get("timestamped_transcription"),
            "cards": item.get("cards"),
        },
    }


def normalize_topyappers_item(
    item: dict[str, Any],
    run_id: str,
    raw_payload_id: str | None,
    *,
    endpoint_kind: str,
) -> dict[str, Any]:
    external_id = str(first_present(item, "id", "iv_id", "video_id", "videoId"))
    creator = first_present(item, "creatorUsername", "user_handle", "username", "handle", "authorUsername")
    url = first_present(item, "videoUrl", "video_url", "webVideoUrl", "url", "shareUrl")
    caption = first_present(item, "caption", "description", "hook", "title")

    return {
        "run_id": run_id,
        "raw_payload_id": raw_payload_id,
        "source_type": "ugc",
        "source_provider": "topyappers",
        "external_id": external_id,
        "url": url,
        "media_url": url,
        "thumbnail_url": first_present(item, "thumbnailUrl", "thumbnail_url", "coverUrl", "cover_url"),
        "creator_or_brand": creator,
        "caption": caption,
        "platform": first_present(item, "platform") or "tiktok",
        "display_format": "video",
        "posted_at": first_present(item, "createdAt", "date_created_timestamp", "created_at"),
        "started_running_at": None,
        "running_duration_days": None,
        "source_metrics": {
            "endpoint_kind": endpoint_kind,
            "views": first_present(item, "views", "play_count", "playCount"),
            "likes": first_present(item, "likes", "like_count", "likeCount"),
            "comments": first_present(item, "comments", "comment_count", "commentCount"),
            "shares": first_present(item, "shares", "share_count", "shareCount"),
            "followers": first_present(item, "followers", "user_followers", "followerCount"),
            "viralityScore": first_present(item, "viralityScore", "virality_score"),
            "hook": item.get("hook"),
            "category": item.get("category"),
            "country": item.get("country"),
            "musicTitle": first_present(item, "musicTitle", "music_title"),
            "hashtags": item.get("hashtags"),
            "subtitles": item.get("subtitles"),
        },
    }


def stringify_if_needed(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        return value
    return str(value)

