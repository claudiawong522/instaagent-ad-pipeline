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
        "brand_id": stringify_if_needed(first_present(item, "pageID", "pageId") or snapshot.get("pageId")),
        "cta_type": first_present(snapshot, "ctaType") or first_card_value(cards, "ctaType"),
        "headline": apify_text_value(snapshot.get("title")) or first_card_value(cards, "title"),
        "link_url": first_present(snapshot, "linkUrl") or first_card_value(cards, "linkUrl"),
        "cta_title": first_present(snapshot, "ctaText") or first_card_value(cards, "ctaText"),
        "languages": item.get("languages"),
        "thumbnail": apify_thumbnail_url(snapshot, cards),
        "categories": item.get("categories") or snapshot.get("pageCategories"),
        "description": apify_text_value(snapshot.get("body")) or first_card_value(cards, "body"),
        "display_format": stringify_if_needed(snapshot.get("displayFormat")),
        "video_duration": as_number(first_present(item, "videoDuration", "video_duration")),
        "started_running": epoch_millis(start_datetime),
        "running_duration": apify_running_duration_days(start_datetime, end_datetime, live),
        "publisher_platform": first_present(item, "publisherPlatform", "publisher_platform"),
        "source_metrics": source_metrics_from_unmapped(item, APIFY_AD_FIRST_CLASS_KEYS),
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


# ── Organic: Apify TikTok (clockworks) + Instagram (data-slayer) → ugc_items ──
#
# These replace TopYappers as the organic source. The Apify scrapers provide engagement
# + creator metadata only; the analysis columns (hook, content_format, persona, ...)
# are filled later by the organic vision enrichment, so they are left null here. virality
# is recomputed from reach + engagement since these providers do not supply a virality score.


def recompute_virality(
    *,
    views: int | None,
    likes: int | None,
    comments: int | None,
    shares: int | None,
    followers: int | None = None,
) -> tuple[float | None, str | None]:
    """Normalized 0-1 virality blending reach amplification with engagement rate.

    reach = views / followers, squashed via reach/(reach+1) so a post that escapes
    its follower base (reach > 1) scores high while the metric stays bounded in [0, 1).
    engagement = (likes + comments + shares) / views, clamped to 1. Final score is
    0.6*reach + 0.4*engagement. When follower count is unknown the score degrades to
    engagement-only. Stands in for TopYappers' virality_score (TikTok/IG don't supply one).
    """
    if not views or views <= 0:
        return None, None
    engagement = (likes or 0) + (comments or 0) + (shares or 0)
    engagement_norm = min(engagement / views, 1.0)
    if followers and followers > 0:
        reach = views / followers
        reach_norm = reach / (reach + 1)
        score = round(0.6 * reach_norm + 0.4 * engagement_norm, 3)
    else:
        score = round(engagement_norm, 3)
    if score >= 0.6:
        tier = "high"
    elif score >= 0.35:
        tier = "medium"
    elif score > 0:
        tier = "low"
    else:
        tier = None
    return score, tier


def tiktok_download_url(item: dict[str, Any]) -> str | None:
    media = item.get("mediaUrls")
    if isinstance(media, list) and media:
        return str(media[0])
    video_meta = item.get("videoMeta")
    if isinstance(video_meta, dict) and video_meta.get("downloadAddr"):
        return str(video_meta["downloadAddr"])
    return None


def tiktok_hashtags(item: dict[str, Any]) -> list[str] | None:
    tags = item.get("hashtags")
    if isinstance(tags, list):
        names = [t.get("name") if isinstance(t, dict) else t for t in tags]
        cleaned = [str(n) for n in names if n]
        return cleaned or None
    return None


TIKTOK_FIRST_CLASS_KEYS = {
    "id", "authorMeta", "videoMeta", "musicMeta", "playCount", "diggCount",
    "commentCount", "shareCount", "text", "hashtags", "webVideoUrl", "mediaUrls",
    "createTimeISO", "createTime", "covers",
}


def normalize_tiktok_item(item: dict[str, Any], run_id: str, raw_payload_id: str | None) -> dict[str, Any]:
    author = item.get("authorMeta") if isinstance(item.get("authorMeta"), dict) else {}
    video_meta = item.get("videoMeta") if isinstance(item.get("videoMeta"), dict) else {}
    music_meta = item.get("musicMeta") if isinstance(item.get("musicMeta"), dict) else {}
    views = as_int(item.get("playCount"))
    likes = as_int(item.get("diggCount"))
    comments = as_int(item.get("commentCount"))
    shares = as_int(item.get("shareCount"))
    followers = as_int(author.get("fans"))
    score, tier = recompute_virality(
        views=views, likes=likes, comments=comments, shares=shares, followers=followers
    )
    music_name = music_meta.get("musicName") or music_meta.get("musicAuthor")
    return {
        "run_id": run_id,
        "raw_payload_id": raw_payload_id,
        "external_id": str(first_present(item, "id", "webVideoUrl") or ""),
        "source": "tiktok",
        "video_id": stringify_if_needed(item.get("id")),
        "video_url": tiktok_download_url(item),
        "cover": first_present(video_meta, "coverUrl", "originalCoverUrl") or first_present(item, "covers"),
        "description": item.get("text"),
        "hashtags": tiktok_hashtags(item),
        "followers": followers,
        "handle": author.get("name"),
        "user_handle": author.get("name"),
        "user_id": stringify_if_needed(author.get("id")),
        "nickname": author.get("nickName"),
        "avatar": author.get("avatar"),
        "views": views,
        "likes": likes,
        "comments": comments,
        "shares": shares,
        "music": {"title": music_name} if music_name else None,
        "date_created": as_timestamp(first_present(item, "createTimeISO", "createTime")),
        "virality_score": score,
        "virality_tier": tier,
        "source_metrics": source_metrics_from_unmapped(
            item,
            TIKTOK_FIRST_CLASS_KEYS,
            extra={"endpoint_kind": "apify_tiktok", "page_url": item.get("webVideoUrl")},
        ),
    }


INSTAGRAM_FIRST_CLASS_KEYS = {
    "id", "pk", "code", "user", "video_url", "thumbnail_url", "caption", "play_count",
    "ig_play_count", "like_count", "comment_count", "share_count", "taken_at",
    "image_versions",
}


def instagram_caption_text(item: dict[str, Any]) -> str | None:
    caption = item.get("caption")
    if isinstance(caption, dict):
        return caption.get("text")
    if isinstance(caption, str):
        return caption or None
    return None


def normalize_instagram_reel(item: dict[str, Any], run_id: str, raw_payload_id: str | None) -> dict[str, Any]:
    user = item.get("user") if isinstance(item.get("user"), dict) else {}
    code = item.get("code")
    views = as_int(first_present(item, "play_count", "ig_play_count"))
    likes = as_int(item.get("like_count"))
    comments = as_int(item.get("comment_count"))
    shares = as_int(item.get("share_count"))
    followers = as_int(user.get("follower_count"))
    score, tier = recompute_virality(
        views=views, likes=likes, comments=comments, shares=shares, followers=followers
    )
    page_url = f"https://www.instagram.com/reel/{code}/" if code else None
    return {
        "run_id": run_id,
        "raw_payload_id": raw_payload_id,
        "external_id": str(first_present(item, "id", "pk", "code") or ""),
        "source": "instagram",
        "video_id": stringify_if_needed(first_present(item, "code", "id")),
        "video_url": item.get("video_url"),
        "cover": item.get("thumbnail_url"),
        "description": instagram_caption_text(item),
        "handle": user.get("username"),
        "user_handle": user.get("username"),
        "user_id": stringify_if_needed(first_present(user, "pk", "id")),
        "nickname": user.get("full_name"),
        "avatar": user.get("profile_pic_url"),
        "followers": followers,
        "views": views,
        "likes": likes,
        "comments": comments,
        "shares": shares,
        "date_created": as_timestamp(item.get("taken_at")),
        "virality_score": score,
        "virality_tier": tier,
        "source_metrics": source_metrics_from_unmapped(
            item,
            INSTAGRAM_FIRST_CLASS_KEYS,
            extra={"endpoint_kind": "apify_instagram", "page_url": page_url},
        ),
    }
