"""Video/thumbnail fetching and Supabase Storage persistence, shared by all enrichment."""

from __future__ import annotations

import logging
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .http_client import HttpClientError, ssl_context
from .supabase_client import SupabaseClient

logger = logging.getLogger(__name__)

STORAGE_BUCKET = "ad-videos"

# OpenRouter forwards arbitrary video to Gemini only as base64 data URLs, so the
# video bytes are fetched in memory per ad; nothing is written to disk.
INLINE_VIDEO_MAX_BYTES = 100 * 1024 * 1024


# Provider cover images aren't always browser-renderable: TikTok in particular serves some
# covers as HEIC (an ISO-BMFF container that shares MP4's `ftyp` signature, so it slips past the
# video-bytes check and lands in Storage as a `.jpg` that Chrome/Firefox draw as a black frame).
# We transcode every cover through Pillow to a real JPEG so the stored poster always displays.
try:
    from PIL import Image as _PILImage
    import pillow_heif as _pillow_heif

    _pillow_heif.register_heif_opener()  # lets Pillow decode HEIC/HEIF
    _IMAGE_DECODE_OK = True
except Exception:  # pragma: no cover - optional image deps absent
    _IMAGE_DECODE_OK = False


def is_probable_video_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname)


def thumbnail_to_web_jpeg(data: bytes) -> bytes | None:
    """Transcode arbitrary cover bytes (HEIC/WebP/PNG/JPEG) to a browser-safe JPEG. Returns None
    if the bytes can't be decoded, so the caller skips the thumbnail instead of storing a broken
    one. Falls back to the original bytes if the optional image deps are unavailable."""
    if not _IMAGE_DECODE_OK:
        return data
    from io import BytesIO

    try:
        with _PILImage.open(BytesIO(data)) as img:
            out = BytesIO()
            img.convert("RGB").save(out, "JPEG", quality=85)
            return out.getvalue()
    except Exception as exc:  # unreadable/corrupt cover
        logger.warning("Thumbnail transcode failed (%s); skipping poster", exc)
        return None


def persist_media(
    supabase: SupabaseClient,
    *,
    run_id: str,
    item_table: str,
    id_column: str,
    item_id: str,
    video_bytes: bytes,
    thumbnail_url: str | None,
    subdir: str,
    timeout: int,
) -> dict[str, str]:
    """Persist the video (and provider thumbnail) to Supabase Storage and record the
    public URLs on the item row. Resilient: upload failures are logged, not raised, so
    enrichment still proceeds. Shared by paid + organic enrichment."""
    updates: dict[str, str] = {}
    try:
        updates["storage_video_url"] = supabase.upload_object(
            STORAGE_BUCKET, f"{run_id}/{subdir}/{item_id}.mp4", video_bytes, "video/mp4", timeout=timeout
        )
    except (HttpClientError, RuntimeError) as exc:
        logger.warning("Video persist failed for %s %s: %s", item_table, item_id, exc)
    if thumbnail_url:
        try:
            thumb_bytes = fetch_video_bytes(thumbnail_url, timeout=timeout)
            jpeg_bytes = thumbnail_to_web_jpeg(thumb_bytes)
            if jpeg_bytes:
                updates["storage_thumb_url"] = supabase.upload_object(
                    STORAGE_BUCKET, f"{run_id}/{subdir}/{item_id}.jpg", jpeg_bytes, "image/jpeg", timeout=timeout
                )
        except (HttpClientError, RuntimeError) as exc:
            logger.warning("Thumbnail persist failed for %s %s: %s", item_table, item_id, exc)
    if updates:
        try:
            supabase.update_by_column(item_table, id_column, item_id, updates)
        except (HttpClientError, RuntimeError) as exc:
            logger.warning("Storage URL update failed for %s %s: %s", item_table, item_id, exc)
    return updates


def fetch_video_bytes(url: str, *, timeout: int) -> bytes:
    request = Request(url, headers={"User-Agent": "instaagent-ad-pipeline/0.1"})
    try:
        with urlopen(request, timeout=timeout, context=ssl_context()) as response:
            content_type = (response.headers.get("Content-Type") or "").lower()
            data = response.read(INLINE_VIDEO_MAX_BYTES + 1)
    except HTTPError as exc:
        raise HttpClientError(f"HTTP {exc.code} fetching video {url}", status=exc.code) from exc
    except (URLError, OSError) as exc:
        raise HttpClientError(f"Network error fetching video {url}: {getattr(exc, 'reason', exc)}") from exc
    if len(data) > INLINE_VIDEO_MAX_BYTES:
        raise RuntimeError(f"Video at {url} exceeds the {INLINE_VIDEO_MAX_BYTES} byte inline limit.")
    # Expiring provider URLs often return an HTML error/login page with HTTP 200.
    # Reject non-video payloads loudly so they are skipped, not base64-encoded and
    # sent to the LLM as bogus "video/mp4" (which the model rejects as INVALID_ARGUMENT).
    if not is_probable_video_bytes(data, content_type):
        raise HttpClientError(
            f"URL {url} did not return video bytes (content-type {content_type or 'unknown'!r}); "
            "the link is likely expired."
        )
    return data


def is_probable_video_bytes(data: bytes, content_type: str) -> bool:
    if content_type.startswith(("text/", "application/json")) or "html" in content_type:
        return False
    head = data[:64].lstrip()[:16].lower()
    if head.startswith((b"<!doctype", b"<html", b"<?xml", b"{", b"[")):
        return False
    return True
