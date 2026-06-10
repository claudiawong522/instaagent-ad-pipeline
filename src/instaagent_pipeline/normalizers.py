from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


FOREPLAY_FIRST_CLASS_KEYS = {
    "id",
    "live",
    "is_live",
    "isLive",
    "name",
    "brand_name",
    "brandName",
    "type",
    "ad_type",
    "adType",
    "ad_id",
    "adId",
    "cards",
    "image",
    "image_url",
    "imageUrl",
    "video",
    "video_url",
    "videoUrl",
    "avatar",
    "avatar_url",
    "avatarUrl",
    "niches",
    "persona",
    "brand",
    "brand_id",
    "brandId",
    "cta_type",
    "ctaType",
    "headline",
    "title",
    "link_url",
    "linkUrl",
    "cta_title",
    "ctaTitle",
    "languages",
    "thumbnail",
    "thumbnail_url",
    "thumbnailUrl",
    "categories",
    "description",
    "market_target",
    "marketTarget",
    "content_filter",
    "display_format",
    "displayFormat",
    "video_duration",
    "videoDuration",
    "started_running",
    "startedRunning",
    "product_category",
    "productCategory",
    "running_duration",
    "runningDuration",
    "emotional_drivers",
    "creative_targeting",
    "creativeTargeting",
    "full_transcription",
    "publisher_platform",
    "publisherPlatform",
    "timestamped_transcription",
    "time_product_was_mentioned",
    "timeProductWasMentioned",
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


def normalize_foreplay_ad(item: dict[str, Any], run_id: str, raw_payload_id: str | None) -> dict[str, Any]:
    external_id_value = first_present(item, "id", "ad_id", "adId")
    started_running = first_present(item, "started_running", "startedRunning")
    running_duration = first_present(item, "running_duration", "runningDuration")

    return {
        "run_id": run_id,
        "raw_payload_id": raw_payload_id,
        "id": str(external_id_value) if external_id_value is not None else "",
        "live": as_bool(first_present(item, "live", "is_live", "isLive")),
        "name": first_present(item, "name", "brand_name", "brandName"),
        "type": first_present(item, "type", "ad_type", "adType"),
        "ad_id": first_present(item, "ad_id", "adId"),
        "cards": item.get("cards"),
        "image": first_present(item, "image", "image_url", "imageUrl"),
        "video": first_present(item, "video", "video_url", "videoUrl"),
        "avatar": first_present(item, "avatar", "avatar_url", "avatarUrl"),
        "niches": item.get("niches"),
        "persona": item.get("persona"),
        "brand_id": first_present(item, "brand_id", "brandId") or nested_first(item, "brand.id"),
        "cta_type": first_present(item, "cta_type", "ctaType"),
        "headline": first_present(item, "headline", "title"),
        "link_url": first_present(item, "link_url", "linkUrl"),
        "cta_title": first_present(item, "cta_title", "ctaTitle"),
        "languages": item.get("languages"),
        "thumbnail": first_present(item, "thumbnail", "thumbnail_url", "thumbnailUrl"),
        "categories": item.get("categories"),
        "description": item.get("description"),
        "market_target": first_present(item, "market_target", "marketTarget"),
        "content_filter": item.get("content_filter"),
        "display_format": stringify_if_needed(first_present(item, "display_format", "displayFormat")),
        "video_duration": as_number(first_present(item, "video_duration", "videoDuration")),
        "started_running": as_number(started_running),
        "product_category": first_present(item, "product_category", "productCategory"),
        "running_duration": as_number(running_duration),
        "emotional_drivers": item.get("emotional_drivers"),
        "creative_targeting": first_present(item, "creative_targeting", "creativeTargeting"),
        "full_transcription": item.get("full_transcription"),
        "publisher_platform": first_present(item, "publisher_platform", "publisherPlatform"),
        "timestamped_transcription": item.get("timestamped_transcription"),
        "time_product_was_mentioned": as_number(
            first_present(item, "time_product_was_mentioned", "timeProductWasMentioned")
        ),
        "source_metrics": source_metrics_from_unmapped(item, FOREPLAY_FIRST_CLASS_KEYS),
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
