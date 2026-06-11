from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


APIFY_AD_FIRST_CLASS_KEYS = {
    "id",
    "adArchiveID",
    "adArchiveId",
    "adId",
    "pageID",
    "pageId",
    "pageName",
    "live",
    "active",
    "isActive",
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
    "title",
    "link_url",
    "cta_title",
    "languages",
    "thumbnail",
    "categories",
    "description",
    "display_format",
    "video_duration",
    "videoDuration",
    "started_running",
    "startDate",
    "startDateFormatted",
    "endDate",
    "endDateFormatted",
    "product_category",
    "running_duration",
    "publisher_platform",
    "publisherPlatform",
    "totalActiveTime",
}


TOPYAPPERS_FIRST_CLASS_KEYS = {
    "id",
    "iv_id",
    "account_type",
    "age",
    "avatar",
    "bio",
    "brand_mentioned",
    "categories",
    "color_palette",
    "comments",
    "comment_count",
    "commentCount",
    "comments_to_views_ratio",
    "content_category",
    "category",
    "content_format",
    "content_tone",
    "country",
    "cover",
    "thumbnailUrl",
    "thumbnail_url",
    "coverUrl",
    "cover_url",
    "creator_avg_views",
    "creator_engagement_rate",
    "creator_language",
    "creatorUsername",
    "cta_type",
    "date_added",
    "date_created",
    "createdAt",
    "created_at",
    "date_created_timestamp",
    "description",
    "caption",
    "face_count",
    "follower_tier",
    "followers",
    "followerCount",
    "gender",
    "hair_color",
    "handle",
    "has_face",
    "has_product",
    "has_text_overlay",
    "hashtags",
    "hook",
    "is_ai_generated",
    "is_branded",
    "is_promotional",
    "is_trending_format",
    "likes",
    "like_count",
    "likeCount",
    "likes_to_views_ratio",
    "main_category",
    "music",
    "musicTitle",
    "music_title",
    "nickname",
    "primary_emotion",
    "product_category",
    "production_quality",
    "race",
    "setting",
    "shares",
    "share_count",
    "shareCount",
    "shares_to_views_ratio",
    "source",
    "subtitles",
    "target_demographic",
    "user_followers",
    "user_handle",
    "user_id",
    "video_id",
    "videoId",
    "video_url",
    "videoUrl",
    "webVideoUrl",
    "url",
    "video_ranges",
    "video_topic",
    "views",
    "play_count",
    "playCount",
    "views_to_avg_ratio",
    "viralityScore",
    "virality_score",
    "virality_tier",
    "visual_style",
}


def result_items(response: Any) -> list[dict[str, Any]]:
    if isinstance(response, list):
        return [item for item in response if isinstance(item, dict)]
    if not isinstance(response, dict):
        return []

    for key in ("data", "results", "items", "videos", "posts", "content"):
        value = response.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]

    nested = response.get("result") or response.get("response")
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


def normalize_apify_ad(item: dict[str, Any], run_id: str, raw_payload_id: str | None) -> dict[str, Any]:
    snapshot = item.get("snapshot") if isinstance(item.get("snapshot"), dict) else {}
    cards = snapshot.get("cards") if isinstance(snapshot.get("cards"), list) else None
    external_id_value = first_present(item, "adArchiveID", "adArchiveId", "id", "adId")
    start_datetime = apify_datetime(first_present(item, "startDateFormatted", "startDate"))
    end_datetime = apify_datetime(first_present(item, "endDateFormatted", "endDate"))
    live = apify_live_status(item, end_datetime)

    return {
        "run_id": run_id,
        "raw_payload_id": raw_payload_id,
        "id": str(external_id_value) if external_id_value is not None else "",
        "live": live,
        "name": first_present(item, "pageName") or snapshot.get("pageName") or nested_first(item, "pageInfo.page.name"),
        "type": stringify_if_needed(snapshot.get("displayFormat")) or "ad",
        "ad_id": stringify_if_needed(first_present(item, "adArchiveID", "adArchiveId", "adId")),
        "cards": cards,
        "image": apify_image_url(snapshot, cards),
        "video": apify_video_url(snapshot, cards),
        "avatar": snapshot.get("pageProfilePictureUrl"),
        "niches": None,
        "persona": None,
        "brand_id": stringify_if_needed(first_present(item, "pageID", "pageId") or snapshot.get("pageId")),
        "cta_type": first_present(snapshot, "ctaType") or first_card_value(cards, "ctaType"),
        "headline": apify_text_value(snapshot.get("title")) or first_card_value(cards, "title"),
        "link_url": first_present(snapshot, "linkUrl") or first_card_value(cards, "linkUrl"),
        "cta_title": first_present(snapshot, "ctaText") or first_card_value(cards, "ctaText"),
        "languages": item.get("languages"),
        "thumbnail": apify_thumbnail_url(snapshot, cards),
        "categories": item.get("categories") or snapshot.get("pageCategories"),
        "description": apify_text_value(snapshot.get("body")) or first_card_value(cards, "body"),
        "market_target": None,
        "content_filter": None,
        "display_format": stringify_if_needed(snapshot.get("displayFormat")),
        "video_duration": as_number(first_present(item, "videoDuration", "video_duration")),
        "started_running": epoch_millis(start_datetime),
        "product_category": None,
        "running_duration": apify_running_duration_days(start_datetime, end_datetime, live),
        "emotional_drivers": None,
        "creative_targeting": None,
        "full_transcription": None,
        "publisher_platform": first_present(item, "publisherPlatform", "publisher_platform"),
        "timestamped_transcription": None,
        "time_product_was_mentioned": None,
        "source_metrics": source_metrics_from_unmapped(item, APIFY_AD_FIRST_CLASS_KEYS),
    }


def normalize_topyappers_item(
    item: dict[str, Any],
    run_id: str,
    raw_payload_id: str | None,
    *,
    endpoint_kind: str,
) -> dict[str, Any]:
    external_id = str(first_present(item, "id", "iv_id", "video_id", "videoId"))
    date_created_timestamp = as_number(item.get("date_created_timestamp"))

    return {
        "run_id": run_id,
        "raw_payload_id": raw_payload_id,
        "external_id": external_id,
        "topyappers_id": item.get("id"),
        "iv_id": item.get("iv_id"),
        "account_type": item.get("account_type"),
        "age": as_int(item.get("age")),
        "avatar": item.get("avatar"),
        "bio": item.get("bio"),
        "brand_mentioned": item.get("brand_mentioned"),
        "categories": item.get("categories"),
        "color_palette": item.get("color_palette"),
        "comments": as_int(first_present(item, "comments", "comment_count", "commentCount")),
        "comments_to_views_ratio": as_number(item.get("comments_to_views_ratio")),
        "content_category": first_present(item, "content_category", "category"),
        "content_format": item.get("content_format"),
        "content_tone": item.get("content_tone"),
        "country": item.get("country"),
        "cover": first_present(item, "cover", "thumbnailUrl", "thumbnail_url", "coverUrl", "cover_url"),
        "creator_avg_views": as_number(item.get("creator_avg_views")),
        "creator_engagement_rate": as_number(item.get("creator_engagement_rate")),
        "creator_language": item.get("creator_language"),
        "cta_type": item.get("cta_type"),
        "date_added": as_timestamp(item.get("date_added")),
        "date_created": as_timestamp(first_present(item, "date_created", "createdAt", "created_at")),
        "date_created_timestamp": date_created_timestamp,
        "description": first_present(item, "description", "caption"),
        "face_count": as_int(item.get("face_count")),
        "follower_tier": item.get("follower_tier"),
        "followers": as_int(first_present(item, "followers", "followerCount")),
        "gender": item.get("gender"),
        "hair_color": item.get("hair_color"),
        "handle": first_present(item, "handle", "creatorUsername"),
        "has_face": as_bool(item.get("has_face")),
        "has_product": as_bool(item.get("has_product")),
        "has_text_overlay": as_bool(item.get("has_text_overlay")),
        "hashtags": item.get("hashtags"),
        "hook": item.get("hook"),
        "is_ai_generated": as_bool(item.get("is_ai_generated")),
        "is_branded": as_bool(item.get("is_branded")),
        "is_promotional": as_bool(item.get("is_promotional")),
        "is_trending_format": as_bool(item.get("is_trending_format")),
        "likes": as_int(first_present(item, "likes", "like_count", "likeCount")),
        "likes_to_views_ratio": as_number(item.get("likes_to_views_ratio")),
        "main_category": first_present(item, "main_category", "category"),
        "music": music_value(item),
        "nickname": item.get("nickname"),
        "primary_emotion": item.get("primary_emotion"),
        "product_category": item.get("product_category"),
        "production_quality": item.get("production_quality"),
        "race": item.get("race"),
        "setting": item.get("setting"),
        "shares": as_int(first_present(item, "shares", "share_count", "shareCount")),
        "shares_to_views_ratio": as_number(item.get("shares_to_views_ratio")),
        "source": item.get("source"),
        "subtitles": item.get("subtitles"),
        "target_demographic": item.get("target_demographic"),
        "user_followers": as_int(item.get("user_followers")),
        "user_handle": first_present(item, "user_handle", "handle", "creatorUsername"),
        "user_id": item.get("user_id"),
        "video_id": first_present(item, "video_id", "videoId"),
        "video_url": first_present(item, "video_url", "videoUrl", "webVideoUrl", "url") or derived_video_url(item),
        "video_ranges": item.get("video_ranges"),
        "video_topic": item.get("video_topic"),
        "views": as_int(first_present(item, "views", "play_count", "playCount")),
        "views_to_avg_ratio": as_number(item.get("views_to_avg_ratio")),
        "virality_score": as_number(first_present(item, "viralityScore", "virality_score")),
        "virality_tier": item.get("virality_tier"),
        "visual_style": item.get("visual_style"),
        "source_metrics": source_metrics_from_unmapped(
            item,
            TOPYAPPERS_FIRST_CLASS_KEYS,
            extra={"endpoint_kind": endpoint_kind},
        ),
    }


def stringify_if_needed(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    if isinstance(value, str):
        return value
    return str(value)


def source_metrics_from_unmapped(
    item: dict[str, Any],
    first_class_keys: set[str],
    *,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metrics = {key: value for key, value in item.items() if key not in first_class_keys}
    if extra:
        metrics.update({key: value for key, value in extra.items() if value is not None})
    return metrics


def apify_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(epoch_seconds(float(value)), tz=UTC)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return datetime.fromtimestamp(epoch_seconds(float(stripped)), tz=UTC)
        except ValueError:
            pass
        try:
            parsed = datetime.fromisoformat(stripped.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    return None


def epoch_seconds(value: float) -> float:
    return value / 1000 if value > 100_000_000_000 else value


def epoch_millis(value: datetime | None) -> float | None:
    if value is None:
        return None
    return value.timestamp() * 1000


def apify_live_status(item: dict[str, Any], end_datetime: datetime | None) -> bool | None:
    explicit = as_bool(first_present(item, "isActive", "active", "live"))
    if explicit is not None:
        return explicit
    if end_datetime is None:
        return True
    return end_datetime > datetime.now(UTC)


def apify_running_duration_days(
    start_datetime: datetime | None,
    end_datetime: datetime | None,
    live: bool | None,
) -> float | None:
    if start_datetime is None:
        return None
    effective_end = end_datetime
    if effective_end is None and live:
        effective_end = datetime.now(UTC)
    if effective_end is None:
        return None
    seconds = max((effective_end - start_datetime).total_seconds(), 0)
    return round(seconds / 86_400, 2)


def apify_text_value(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, dict):
        return stringify_if_needed(first_present(value, "text", "value"))
    return stringify_if_needed(value)


def first_card_value(cards: Any, *keys: str) -> Any:
    if not isinstance(cards, list):
        return None
    for card in cards:
        if not isinstance(card, dict):
            continue
        value = first_present(card, *keys)
        if value not in (None, ""):
            return value
    return None


def first_nested_media_url(items: Any, *keys: str) -> str | None:
    if not isinstance(items, list):
        return None
    for item in items:
        if isinstance(item, str) and item:
            return item
        if not isinstance(item, dict):
            continue
        value = first_present(item, *keys)
        if value not in (None, ""):
            return stringify_if_needed(value)
    return None


def apify_video_url(snapshot: dict[str, Any], cards: Any) -> str | None:
    return (
        first_nested_media_url(snapshot.get("videos"), "videoHdUrl", "videoSdUrl", "url")
        or first_card_value(cards, "videoHdUrl", "videoSdUrl", "watermarkedVideoHdUrl", "watermarkedVideoSdUrl")
        or first_nested_media_url(snapshot.get("extraVideos"), "videoHdUrl", "videoSdUrl", "url")
    )


def apify_image_url(snapshot: dict[str, Any], cards: Any) -> str | None:
    return (
        first_nested_media_url(snapshot.get("images"), "originalImageUrl", "resizedImageUrl", "url")
        or first_card_value(cards, "originalImageUrl", "resizedImageUrl", "watermarkedResizedImageUrl")
        or first_nested_media_url(snapshot.get("extraImages"), "originalImageUrl", "resizedImageUrl", "url")
    )


def apify_thumbnail_url(snapshot: dict[str, Any], cards: Any) -> str | None:
    return (
        first_nested_media_url(snapshot.get("videos"), "videoPreviewImageUrl", "previewImageUrl", "thumbnailUrl")
        or first_card_value(cards, "videoPreviewImageUrl", "resizedImageUrl", "originalImageUrl")
        or apify_image_url(snapshot, cards)
    )


def music_value(item: dict[str, Any]) -> Any:
    music = item.get("music")
    if music not in (None, ""):
        return music
    title = first_present(item, "musicTitle", "music_title")
    if title is None:
        return None
    return {"title": title}


def derived_video_url(item: dict[str, Any]) -> str | None:
    source = stringify_if_needed(item.get("source"))
    video_id = stringify_if_needed(first_present(item, "video_id", "videoId"))
    if not source or not video_id:
        return None

    source = source.lower()
    if source == "youtube":
        return f"https://www.youtube.com/watch?v={video_id}"

    if source == "instagram":
        normalized_id = video_id.strip("/")
        if normalized_id.startswith(("p/", "reel/", "tv/")):
            return f"https://www.instagram.com/{normalized_id}/"
        return f"https://www.instagram.com/reel/{normalized_id}/"

    if source == "tiktok":
        handle = stringify_if_needed(first_present(item, "user_handle", "handle", "creatorUsername"))
        if not handle:
            return None
        return f"https://www.tiktok.com/@{handle.lstrip('@')}/video/{video_id}"

    return None


def as_int(value: Any) -> int | None:
    number = as_number(value)
    if number is None:
        return None
    return int(number)


def as_bool(value: Any) -> bool | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "t", "1", "yes", "y"}:
            return True
        if lowered in {"false", "f", "0", "no", "n"}:
            return False
    return None


def as_timestamp(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return epoch_to_iso(float(value))
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return epoch_to_iso(float(stripped))
        except ValueError:
            return stripped
    return None


def epoch_to_iso(value: float) -> str:
    # Values above 10^11 are millisecond epochs; smaller epoch values are seconds.
    seconds = value / 1000 if value > 100_000_000_000 else value
    return datetime.fromtimestamp(seconds, tz=UTC).isoformat()


def days_since_timestamp(value: str | None) -> int | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return max((datetime.now(UTC) - parsed).days, 0)
