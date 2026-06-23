from __future__ import annotations

import base64
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .config import Config
from .http_client import HttpClientError, request_json, ssl_context
from .ingestion import complete_query, log_api_usage, log_failed_query, start_query, utc_now_iso
from .supabase_client import SupabaseClient


logger = logging.getLogger(__name__)

STORAGE_BUCKET = "ad-videos"

OPENROUTER_PROVIDER = "openrouter"
OPENROUTER_BASE_URL = "https://openrouter.ai"
OPENROUTER_CHAT_COMPLETIONS_ENDPOINT = "/api/v1/chat/completions"

GEMINI_PROVIDER = "gemini"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com"
GEMINI_ENDPOINT = "/v1beta/models/{model}:generateContent"
# Vision providers rate-limit aggressively (HTTP 429) under parallel enrichment; retry
# with backoff (honoring Retry-After) so concurrent workers ride out the throttle.
ENRICHMENT_HTTP_RETRIES = 6
# OpenRouter forwards arbitrary video to Gemini only as base64 data URLs, so the
# video bytes are fetched in memory per ad; nothing is written to disk.
INLINE_VIDEO_MAX_BYTES = 100 * 1024 * 1024

# paid_ads columns written by the enrichment response, in addition to
# analysis_model/analyzed_at bookkeeping. Keys absent from the model JSON
# stay untouched; explicit nulls are written as null.
# Trimmed analysis set (see plan): the vision-generated ai_description (the search
# payload) plus 20 high-value fields. Dropped (noisy/low-payoff/optics): race,
# hair_color, gender, age, has_face, face_count, color_palette, creative_targeting,
# market_target, is_ai_generated. Their columns remain in the DB but go unpopulated.
PAID_AD_ANALYSIS_COLUMNS = (
    "ai_description",
    "hook",
    "main_category",
    "content_category",
    "content_format",
    "content_tone",
    "primary_emotion",
    "target_demographic",
    "video_topic",
    "visual_style",
    "production_quality",
    "setting",
    "has_product",
    "has_text_overlay",
    "is_trending_format",
    "brand_mentioned",
    "persona",
    "emotional_drivers",
    "product_category",
    "niches",
    "time_product_was_mentioned",
)

NULLABLE_STRING = {"type": ["string", "null"]}
NULLABLE_BOOLEAN = {"type": ["boolean", "null"]}
NULLABLE_INTEGER = {"type": ["integer", "null"]}
NULLABLE_NUMBER = {"type": ["number", "null"]}
NULLABLE_STRING_ARRAY = {"type": ["array", "null"], "items": {"type": "string"}}

ENRICHMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "transcript_text": NULLABLE_STRING,
        "transcript_segments": {
            "type": ["array", "null"],
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "start": {"type": "number"},
                    "end": {"type": "number"},
                    "text": {"type": "string"},
                },
                "required": ["start", "end", "text"],
            },
        },
        "ai_description": NULLABLE_STRING,
        "hook": NULLABLE_STRING,
        "main_category": NULLABLE_STRING,
        "content_category": NULLABLE_STRING,
        "content_format": NULLABLE_STRING,
        "content_tone": NULLABLE_STRING,
        "primary_emotion": NULLABLE_STRING,
        "target_demographic": NULLABLE_STRING,
        "video_topic": NULLABLE_STRING,
        "visual_style": NULLABLE_STRING,
        "production_quality": NULLABLE_STRING,
        "setting": NULLABLE_STRING,
        "has_product": NULLABLE_BOOLEAN,
        "has_text_overlay": NULLABLE_BOOLEAN,
        "is_trending_format": NULLABLE_BOOLEAN,
        "brand_mentioned": NULLABLE_STRING_ARRAY,
        "persona": NULLABLE_STRING,
        "emotional_drivers": NULLABLE_STRING_ARRAY,
        "product_category": NULLABLE_STRING,
        "niches": NULLABLE_STRING_ARRAY,
        "time_product_was_mentioned": NULLABLE_NUMBER,
    },
    "required": ["transcript_text", "transcript_segments", *PAID_AD_ANALYSIS_COLUMNS],
}

ENRICHMENT_PROMPT = """
You analyze a social video ad/clip for a creative-intelligence + search pipeline.
Watch the video and use the copy below for context.

Tasks:
1. Transcribe all spoken audio verbatim into transcript_text. Provide
   transcript_segments with start/end seconds per spoken sentence. If there
   is no speech, set transcript_text to null and transcript_segments to null.

2. Write ai_description: a detailed, concrete, present-tense visual description of
   the whole video, optimized for semantic search. Use a consistent structure:
   - Narrate the video chronologically, scene by scene ("The video opens with... then... next...").
   - Note camera work / framing when notable (angles, zoom, close-ups, orientation).
   - Identify the subject: apparent age range, gender, ethnicity/region, and any visible condition.
   - Describe every product/tool and how it is applied, in order (motions, textures, foam, pads, devices, steam).
   - Explicitly call out scroll-stopping / visceral moments (e.g. a close-up of sebum on cotton pads).
   - Note on-screen text/overlays, setting, and tone when relevant.
   - End with a 1-2 sentence summary of the overall arc (problem -> result / before -> after)
     and the single most eye-catching element.
   Write specific visual prose, no marketing fluff.

3. Extract creative metadata. Use null for anything not inferable.
   - hook: the attention-grabbing opening line or visual device, quoted or described in one sentence.
   - persona: the ICP (ideal customer profile) this content targets, one concise phrase.
   - target_demographic: audience descriptor such as "women 25-34 with sensitive skin".
   - content_format: e.g. talking_head, ugc_testimonial, demo, before_after, voiceover_broll, skit, unboxing, tutorial, asmr, grwm.
   - content_tone, content_category, main_category, video_topic, visual_style, setting: short lowercase phrases.
   - primary_emotion: dominant emotion the video evokes.
   - emotional_drivers: list of persuasion levers, e.g. ["fear of missing out", "social proof"].
   - product_category: e.g. skincare, supplements, apparel.
   - niches: list of niche descriptors.
   - production_quality: one of low, medium, high, professional.
   - has_product: whether a product is shown on screen.
   - has_text_overlay: whether burned-in captions or text overlays appear.
   - is_trending_format: whether the video uses a recognizable trending social format.
   - time_product_was_mentioned: seconds into the video when the product is first mentioned or shown, null if never.
   - brand_mentioned: list of brand names spoken or shown.

Copy context:
{ad_copy}
""".strip()


@dataclass
class PaidAdEnrichmentCandidate:
    paid_ad_row_id: str
    ad_archive_id: str
    video_url: str
    thumbnail_url: str | None = None
    ad_copy: dict[str, Any] = field(default_factory=dict)


@dataclass
class EnrichmentResult:
    candidates: int
    attempted: int = 0
    written: int = 0
    skipped_unsupported: int = 0
    failed: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)


def enrich_paid_ads(
    *,
    config: Config,
    supabase: SupabaseClient | None,
    run_id: str,
    limit: int,
    dry_run: bool,
    input_json: Path | None = None,
    timeout: int = 300,
    concurrency: int = 1,
) -> EnrichmentResult:
    if supabase is None:
        raise RuntimeError("Supabase credentials are required to load paid ad enrichment candidates.")
    if limit < 1:
        raise ValueError("--limit must be greater than 0.")

    candidates, skipped_unsupported = paid_ad_enrichment_candidates(
        supabase,
        run_id=run_id,
        limit=limit,
    )
    result = EnrichmentResult(
        candidates=len(candidates),
        skipped_unsupported=skipped_unsupported,
    )

    if dry_run:
        result.details = [
            {
                "paid_ad_row_id": candidate.paid_ad_row_id,
                "ad_archive_id": candidate.ad_archive_id,
                "video_url": candidate.video_url,
                "action": "would_enrich",
            }
            for candidate in candidates
        ]
        return result

    if input_json is None:
        if config.enrichment_provider == GEMINI_PROVIDER:
            if not config.gemini_api_key:
                raise RuntimeError("GEMINI_API_KEY is required unless --input-json is used.")
        elif not config.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY is required unless --input-json is used.")

    def _enrich_one(candidate: PaidAdEnrichmentCandidate) -> bool:
        return enrich_paid_ad(
            config=config,
            supabase=supabase,
            run_id=run_id,
            candidate=candidate,
            input_json=input_json,
            timeout=timeout,
        )

    # I/O-bound (video download + Gemini/OpenRouter call per item); fan out across threads.
    # SupabaseClient is stateless per request, so concurrent writes are safe. Results are
    # aggregated here in the main thread as futures complete, so no lock is needed.
    workers = max(1, concurrency)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_enrich_one, candidate): candidate for candidate in candidates}
        for future in as_completed(futures):
            candidate = futures[future]
            result.attempted += 1
            try:
                written = future.result()
            except (HttpClientError, RuntimeError) as exc:
                result.failed += 1
                result.details.append(
                    {
                        "paid_ad_row_id": candidate.paid_ad_row_id,
                        "ad_archive_id": candidate.ad_archive_id,
                        "status": "failed",
                        "error": str(exc),
                    }
                )
                continue

            if written:
                result.written += 1
                status = "written"
            else:
                result.failed += 1
                status = "no_analysis"
            result.details.append(
                {
                    "paid_ad_row_id": candidate.paid_ad_row_id,
                    "ad_archive_id": candidate.ad_archive_id,
                    "status": status,
                }
            )

    return result


def existing_enriched_ids(supabase: SupabaseClient, run_id: str, item_type: str) -> set[str]:
    """Return the set of item_ids already enriched (present in item_enrichments) for
    this run and item_type. Used to skip candidates instead of the old analyzed_at filter."""
    rows = supabase.select(
        "item_enrichments",
        {
            "select": "item_id",
            "item_type": f"eq.{item_type}",
            "run_id": f"eq.{run_id}",
        },
    )
    return {str(row.get("item_id")) for row in rows if row.get("item_id")}


def paid_ad_enrichment_candidates(
    supabase: SupabaseClient,
    *,
    run_id: str,
    limit: int,
) -> tuple[list[PaidAdEnrichmentCandidate], int]:
    rows = supabase.select(
        "paid_ads",
        {
            "select": (
                "paid_ad_row_id,id,video,thumbnail,image,headline,description,cta_title,cta_type,"
                "name,link_url,display_format"
            ),
            "run_id": f"eq.{run_id}",
            "video": "not.is.null",
            "order": "saved_to_supabase_at.asc",
            "limit": str(max(limit * 5, limit)),
        },
    )

    already_enriched = existing_enriched_ids(supabase, run_id, "paid_ad")
    candidates: list[PaidAdEnrichmentCandidate] = []
    skipped_unsupported = 0
    for row in rows:
        paid_ad_row_id = str(row.get("paid_ad_row_id") or "")
        video_url = str(row.get("video") or "")
        if not paid_ad_row_id:
            continue
        if paid_ad_row_id in already_enriched:
            continue
        if not is_probable_video_url(video_url):
            skipped_unsupported += 1
            continue

        candidates.append(
            PaidAdEnrichmentCandidate(
                paid_ad_row_id=paid_ad_row_id,
                ad_archive_id=str(row.get("id") or ""),
                video_url=video_url,
                thumbnail_url=str(row.get("thumbnail") or row.get("image") or "") or None,
                ad_copy={
                    key: row.get(key)
                    for key in ("headline", "description", "cta_title", "cta_type", "name", "link_url", "display_format")
                    if row.get(key) not in (None, "")
                },
            )
        )
        if len(candidates) >= limit:
            break

    return candidates, skipped_unsupported


def enrich_paid_ad(
    *,
    config: Config,
    supabase: SupabaseClient,
    run_id: str,
    candidate: PaidAdEnrichmentCandidate,
    input_json: Path | None,
    timeout: int,
) -> bool:
    is_gemini = config.enrichment_provider == GEMINI_PROVIDER
    model = config.gemini_model if is_gemini else config.openrouter_model
    raw_provider = GEMINI_PROVIDER if is_gemini else OPENROUTER_PROVIDER
    endpoint = GEMINI_ENDPOINT.format(model=model) if is_gemini else OPENROUTER_CHAT_COMPLETIONS_ENDPOINT
    provider = f"{raw_provider}:{model}"
    request_params = {
        "model": model,
        "paid_ad_row_id": candidate.paid_ad_row_id,
        "ad_archive_id": candidate.ad_archive_id,
        "video_url": candidate.video_url,
    }
    source_query_id = start_query(
        supabase=supabase,
        dry_run=False,
        run_id=run_id,
        provider=provider,
        endpoint=endpoint,
        method="POST",
        request_params=request_params,
    )
    response_headers: dict[str, str] = {}
    response_status: int | None = None
    usage: dict[str, Any] = {}
    try:
        if input_json:
            body = json.loads(input_json.read_text())
            analysis = parse_gemini_response(body) if is_gemini else parse_enrichment_response(body)
            usage = gemini_usage(body) if is_gemini else openrouter_usage(body)
        else:
            video_bytes = fetch_video_bytes(candidate.video_url, timeout=timeout)
            media = persist_media(
                supabase,
                run_id=run_id,
                item_table="paid_ads",
                id_column="paid_ad_row_id",
                item_id=candidate.paid_ad_row_id,
                video_bytes=video_bytes,
                thumbnail_url=candidate.thumbnail_url,
                subdir="paid",
                timeout=timeout,
            )
            # OpenRouter fetches the video from its public Storage URL server-side, so
            # we can drop our copy of the bytes before the (slow) LLM call — keeping
            # peak memory low and letting concurrency scale. Gemini still needs bytes.
            storage_video_url = media.get("storage_video_url")
            if not is_gemini and storage_video_url:
                video_bytes = None
            (
                body,
                analysis,
                provider,
                endpoint,
                response_headers,
                response_status,
                usage,
                model,
            ) = request_enrichment(
                config=config,
                video_bytes=video_bytes,
                video_url=None if is_gemini else storage_video_url,
                ad_copy=candidate.ad_copy,
                timeout=timeout,
            )

        log_api_usage(
            supabase=supabase,
            dry_run=False,
            run_id=run_id,
            provider=provider,
            endpoint=endpoint,
            status=response_status,
            response_count=1 if analysis is not None else 0,
            headers=response_headers,
            metadata={"model": model, "usage": usage},
        )
        complete_query(
            supabase=supabase,
            dry_run=False,
            source_query_id=source_query_id,
            response_count=1 if analysis is not None else 0,
            http_status=response_status,
        )
    except (HttpClientError, RuntimeError) as exc:
        if isinstance(exc, HttpClientError) and response_status is None:
            log_api_usage(
                supabase=supabase,
                dry_run=False,
                run_id=run_id,
                provider=provider,
                endpoint=endpoint,
                status=exc.status,
                response_count=None,
                headers={},
                metadata={"model": model},
            )
        log_failed_query(
            supabase=supabase,
            dry_run=False,
            run_id=run_id,
            provider=provider,
            endpoint=endpoint,
            method="POST",
            request_params=request_params,
            source_query_id=source_query_id,
            http_status=getattr(exc, "status", None),
            error_message=str(exc),
        )
        raise

    if analysis is not None:
        supabase.insert(
            "raw_payloads",
            {
                "run_id": run_id,
                "source_query_id": source_query_id,
                "provider": raw_provider,
                "endpoint": endpoint,
                "external_id": candidate.ad_archive_id or candidate.paid_ad_row_id,
                "payload_json": body,
            },
        )
    if analysis is None:
        return False

    payload = {key: analysis.get(key) for key in PAID_AD_ANALYSIS_COLUMNS if key in analysis}
    payload.update(
        {
            "run_id": run_id,
            "item_type": "paid_ad",
            "item_id": candidate.paid_ad_row_id,
            "transcript_text": clean_optional_text(analysis.get("transcript_text")),
            "transcript_segments": analysis.get("transcript_segments") or None,
            "analysis_model": model,
            "analyzed_at": utc_now_iso(),
        }
    )
    supabase.upsert("item_enrichments", payload, "item_type,item_id")
    return True


def openrouter_request_body(
    *,
    model: str,
    ad_copy: dict[str, Any],
    video_url: str | None = None,
    video_bytes: bytes | None = None,
) -> dict[str, Any]:
    # Prefer a remote URL: the provider fetches the video server-side, so we never
    # inline (and hold in memory) the bytes. Fall back to a base64 data URL when no
    # remote URL is available (e.g. the Storage upload failed).
    if video_url:
        url = video_url
    elif video_bytes is not None:
        url = "data:video/mp4;base64," + base64.b64encode(video_bytes).decode("ascii")
    else:
        raise ValueError("openrouter_request_body requires video_url or video_bytes")
    prompt = ENRICHMENT_PROMPT.format(ad_copy=json.dumps(ad_copy, indent=2, sort_keys=True))
    return {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "video_url", "video_url": {"url": url}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "paid_ad_enrichment",
                "strict": True,
                "schema": ENRICHMENT_SCHEMA,
            },
        },
    }


def parse_enrichment_response(body: Any) -> dict[str, Any] | None:
    if not isinstance(body, dict):
        return None
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, list):
        content = "".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
    if not isinstance(content, str) or not content.strip():
        return None
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"OpenRouter returned invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        return None
    return parsed


def openrouter_usage(body: Any) -> dict[str, Any]:
    if isinstance(body, dict) and isinstance(body.get("usage"), dict):
        return body["usage"]
    return {}


def gemini_request_body(
    *,
    video_bytes: bytes,
    ad_copy: dict[str, Any],
) -> dict[str, Any]:
    encoded = base64.b64encode(video_bytes).decode("ascii")
    prompt = ENRICHMENT_PROMPT.format(ad_copy=json.dumps(ad_copy, indent=2, sort_keys=True))
    return {
        "contents": [
            {
                "parts": [
                    {"inline_data": {"mime_type": "video/mp4", "data": encoded}},
                    {"text": prompt},
                ]
            }
        ],
        "generationConfig": {"response_mime_type": "application/json"},
    }


def parse_gemini_response(body: Any) -> dict[str, Any] | None:
    if not isinstance(body, dict):
        return None
    candidates = body.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return None
    content = candidates[0].get("content") if isinstance(candidates[0], dict) else None
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        return None
    text = "".join(
        str(part.get("text", ""))
        for part in parts
        if isinstance(part, dict) and isinstance(part.get("text"), str)
    ).strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Gemini returned invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        return None
    return parsed


def gemini_usage(body: Any) -> dict[str, Any]:
    if isinstance(body, dict) and isinstance(body.get("usageMetadata"), dict):
        return body["usageMetadata"]
    return {}


def request_enrichment(
    *,
    config: Config,
    ad_copy: dict[str, Any],
    timeout: int,
    video_bytes: bytes | None = None,
    video_url: str | None = None,
) -> tuple[Any, dict[str, Any] | None, str, str, dict[str, str], int | None, dict[str, Any], str]:
    """Dispatch a video-enrichment request to the configured provider.

    Pass `video_url` (a remote URL the provider can fetch) to keep the video out of
    our memory; OpenRouter uses it directly. Gemini has no remote-URL path, so it
    always needs `video_bytes`. OpenRouter falls back to `video_bytes` when no URL.

    Returns (body, analysis, provider, endpoint, response_headers, response_status,
    usage, model). The provider string is "<provider>:<model>"; model is the bare
    model name.
    """
    if config.enrichment_provider == GEMINI_PROVIDER:
        if video_bytes is None:
            raise ValueError("Gemini enrichment requires video_bytes")
        model = config.gemini_model
        endpoint = GEMINI_ENDPOINT.format(model=model)
        response = request_json(
            "POST",
            f"{GEMINI_BASE_URL}{endpoint}",
            headers={"x-goog-api-key": config.gemini_api_key},
            body=gemini_request_body(video_bytes=video_bytes, ad_copy=ad_copy),
            timeout=timeout,
            retries=ENRICHMENT_HTTP_RETRIES,
        )
        body = response.body
        analysis = parse_gemini_response(body)
        usage = gemini_usage(body)
        provider = f"{GEMINI_PROVIDER}:{model}"
    else:
        model = config.openrouter_model
        endpoint = OPENROUTER_CHAT_COMPLETIONS_ENDPOINT
        response = request_json(
            "POST",
            f"{OPENROUTER_BASE_URL}{endpoint}",
            headers={"Authorization": f"Bearer {config.openrouter_api_key}"},
            body=openrouter_request_body(
                model=model,
                ad_copy=ad_copy,
                video_url=video_url,
                video_bytes=video_bytes,
            ),
            timeout=timeout,
            retries=ENRICHMENT_HTTP_RETRIES,
        )
        body = response.body
        analysis = parse_enrichment_response(body)
        usage = openrouter_usage(body)
        provider = f"{OPENROUTER_PROVIDER}:{model}"
    return body, analysis, provider, endpoint, response.headers, response.status, usage, model


def is_probable_video_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname)


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
    enrichment still proceeds. Shared by paid + UGC enrichment."""
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
            updates["storage_thumb_url"] = supabase.upload_object(
                STORAGE_BUCKET, f"{run_id}/{subdir}/{item_id}.jpg", thumb_bytes, "image/jpeg", timeout=timeout
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


def clean_optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None
