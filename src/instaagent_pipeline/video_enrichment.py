"""Shared multimodal video enrichment: one flow for paid ads and organic items.

One vision call (Gemini directly, or Gemini via OpenRouter) per video: transcript +
ai_description + the trimmed analysis fields, plus persisting the video/thumbnail to
Supabase Storage. Paid and organic differ only in where candidates come from and which
table/columns identify an item — captured by `ItemKind` — so both reach column parity
and share one embedding space by construction. The per-kind candidate loaders live in
`paid_enrichment.py` / `organic_enrichment.py`.
"""

from __future__ import annotations

import base64
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .config import Config
from .http_client import HttpClientError, request_json
from .ingestion import logged_query, utc_now_iso
from .media import fetch_video_bytes, persist_media
from .openrouter import (
    OPENROUTER_BASE_URL,
    OPENROUTER_CHAT_COMPLETIONS_ENDPOINT,
    OPENROUTER_PROVIDER,
    openrouter_json_body,
    openrouter_usage,
    parse_json_response,
)
from .supabase_client import SupabaseClient


logger = logging.getLogger(__name__)

GEMINI_PROVIDER = "gemini"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com"
GEMINI_ENDPOINT = "/v1beta/models/{model}:generateContent"
# Vision providers rate-limit aggressively (HTTP 429) under parallel enrichment; retry
# with backoff (honoring Retry-After) so concurrent workers ride out the throttle.
ENRICHMENT_HTTP_RETRIES = 6

# item_enrichments columns written by the enrichment response, in addition to
# analysis_model/analyzed_at bookkeeping. Keys absent from the model JSON
# stay untouched; explicit nulls are written as null.
# Trimmed analysis set (see plan): the vision-generated ai_description (the search
# payload) plus 17 high-value fields. Dropped (noisy/low-payoff/optics): race,
# hair_color, gender, age, has_face, face_count, color_palette, creative_targeting,
# market_target, is_ai_generated, and (no downstream consumer) has_text_overlay,
# is_trending_format, time_product_was_mentioned. Their columns remain in the DB but
# go unpopulated. Note: production format now comes from the multi-value content_formats
# tag (audience_enrichment.py), superseding the single-value content_format here.
ANALYSIS_COLUMNS = (
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
    "brand_mentioned",
    "persona",
    "emotional_drivers",
    "product_category",
    "niches",
)

NULLABLE_STRING = {"type": ["string", "null"]}
NULLABLE_BOOLEAN = {"type": ["boolean", "null"]}
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
        "brand_mentioned": NULLABLE_STRING_ARRAY,
        "persona": NULLABLE_STRING,
        "emotional_drivers": NULLABLE_STRING_ARRAY,
        "product_category": NULLABLE_STRING,
        "niches": NULLABLE_STRING_ARRAY,
    },
    "required": ["transcript_text", "transcript_segments", *ANALYSIS_COLUMNS],
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
   - brand_mentioned: list of brand names spoken or shown.

Copy context:
{ad_copy}
""".strip()


@dataclass(frozen=True)
class ItemKind:
    """Where one kind of enrichable item lives and how it is identified."""

    label: str  # human label for error messages, e.g. "paid ad"
    table: str  # source table the item row lives in
    id_column: str  # that table's id column
    item_type: str  # polymorphic item_type used in item_enrichments etc.
    storage_subdir: str  # Storage folder under <run_id>/ for the persisted media
    detail_id_key: str  # key naming the item id in result details / request params


@dataclass
class EnrichmentCandidate:
    item_id: str
    video_url: str
    thumbnail_url: str | None = None
    # raw_payloads external id; falls back to item_id when the provider has no own id.
    external_id: str = ""
    # Copy/context JSON given to the LLM prompt ({} when there is none).
    ad_copy: dict[str, Any] = field(default_factory=dict)
    # Extra identifying keys echoed into details/request params (e.g. ad_archive_id).
    extra_ids: dict[str, str] = field(default_factory=dict)


@dataclass
class EnrichmentResult:
    candidates: int
    attempted: int = 0
    written: int = 0
    skipped_unsupported: int = 0
    failed: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)


def _detail_ids(kind: ItemKind, candidate: EnrichmentCandidate) -> dict[str, str]:
    return {kind.detail_id_key: candidate.item_id, **candidate.extra_ids}


def enrich_items(
    *,
    config: Config,
    supabase: SupabaseClient | None,
    run_id: str,
    limit: int,
    dry_run: bool,
    kind: ItemKind,
    load_candidates: Callable[..., tuple[list[EnrichmentCandidate], int]],
    input_json: Path | None = None,
    timeout: int = 300,
    concurrency: int = 32,
) -> EnrichmentResult:
    if supabase is None:
        raise RuntimeError(f"Supabase credentials are required to load {kind.label} enrichment candidates.")
    if limit < 1:
        raise ValueError("--limit must be greater than 0.")

    candidates, skipped_unsupported = load_candidates(supabase, run_id=run_id, limit=limit)
    result = EnrichmentResult(candidates=len(candidates), skipped_unsupported=skipped_unsupported)

    if dry_run:
        result.details = [
            {**_detail_ids(kind, c), "video_url": c.video_url, "action": "would_enrich"}
            for c in candidates
        ]
        return result

    if input_json is None:
        if config.enrichment_provider == GEMINI_PROVIDER:
            if not config.gemini_api_key:
                raise RuntimeError("GEMINI_API_KEY is required unless --input-json is used.")
        elif not config.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY is required unless --input-json is used.")

    def _enrich_one(candidate: EnrichmentCandidate) -> bool:
        return enrich_item(
            config=config,
            supabase=supabase,
            run_id=run_id,
            kind=kind,
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
                    {**_detail_ids(kind, candidate), "status": "failed", "error": str(exc)}
                )
                continue

            if written:
                result.written += 1
                status = "written"
            else:
                result.failed += 1
                status = "no_analysis"
            result.details.append({**_detail_ids(kind, candidate), "status": status})

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


def enrich_item(
    *,
    config: Config,
    supabase: SupabaseClient,
    run_id: str,
    kind: ItemKind,
    candidate: EnrichmentCandidate,
    input_json: Path | None,
    timeout: int,
) -> bool:
    is_gemini = config.enrichment_provider == GEMINI_PROVIDER
    model = config.gemini_model if is_gemini else config.openrouter_model
    raw_provider = GEMINI_PROVIDER if is_gemini else OPENROUTER_PROVIDER
    endpoint = GEMINI_ENDPOINT.format(model=model) if is_gemini else OPENROUTER_CHAT_COMPLETIONS_ENDPOINT
    # Which step we're in, so a failure is classified as 'expired' (URL didn't yield
    # video bytes) vs 'failed' (download ok, but the vision/analysis step failed).
    stage = "download"
    try:
        with logged_query(
            supabase=supabase,
            run_id=run_id,
            provider=f"{raw_provider}:{model}",
            endpoint=endpoint,
            request_params={"model": model, **_detail_ids(kind, candidate), "video_url": candidate.video_url},
        ) as log:
            log.metadata = {"model": model}
            if input_json:
                stage = "analysis"
                body = json.loads(input_json.read_text())
                analysis = parse_gemini_response(body) if is_gemini else parse_json_response(body)
                usage = gemini_usage(body) if is_gemini else openrouter_usage(body)
            else:
                video_bytes = fetch_video_bytes(candidate.video_url, timeout=timeout)
                stage = "analysis"
                media = persist_media(
                    supabase,
                    run_id=run_id,
                    item_table=kind.table,
                    id_column=kind.id_column,
                    item_id=candidate.item_id,
                    video_bytes=video_bytes,
                    thumbnail_url=candidate.thumbnail_url,
                    subdir=kind.storage_subdir,
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
                    log.provider,
                    endpoint,
                    log.headers,
                    log.status,
                    usage,
                    model,
                ) = request_enrichment(
                    config=config,
                    video_bytes=video_bytes,
                    video_url=None if is_gemini else storage_video_url,
                    ad_copy=candidate.ad_copy,
                    timeout=timeout,
                )
                log.endpoint = endpoint
                log.metadata["model"] = model
            log.response_count = 1 if analysis is not None else 0
            log.metadata["usage"] = usage
    except (HttpClientError, RuntimeError) as exc:
        record_item_status(
            supabase,
            table=kind.table,
            id_column=kind.id_column,
            item_id=candidate.item_id,
            status="expired" if stage == "download" else "failed",
            error=str(exc),
        )
        raise

    if analysis is None:
        record_item_status(
            supabase,
            table=kind.table,
            id_column=kind.id_column,
            item_id=candidate.item_id,
            status="failed",
            error="vision returned no analysis",
        )
        return False

    supabase.insert(
        "raw_payloads",
        {
            "run_id": run_id,
            "source_query_id": log.source_query_id,
            "provider": raw_provider,
            "endpoint": endpoint,
            "external_id": candidate.external_id or candidate.item_id,
            "payload_json": body,
        },
    )
    payload = {key: analysis.get(key) for key in ANALYSIS_COLUMNS if key in analysis}
    payload.update(
        {
            "run_id": run_id,
            "item_type": kind.item_type,
            "item_id": candidate.item_id,
            "transcript_text": clean_optional_text(analysis.get("transcript_text")),
            "transcript_segments": analysis.get("transcript_segments") or None,
            "analysis_model": model,
            "analyzed_at": utc_now_iso(),
        }
    )
    supabase.upsert("item_enrichments", payload, "item_type,item_id")
    record_item_status(
        supabase,
        table=kind.table,
        id_column=kind.id_column,
        item_id=candidate.item_id,
        status="enriched",
    )
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
    return openrouter_json_body(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "video_url", "video_url": {"url": url}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        schema=ENRICHMENT_SCHEMA,
        schema_name="video_enrichment",
    )


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
        analysis = parse_json_response(body)
        usage = openrouter_usage(body)
        provider = f"{OPENROUTER_PROVIDER}:{model}"
    return body, analysis, provider, endpoint, response.headers, response.status, usage, model


def record_item_status(
    supabase: SupabaseClient,
    *,
    table: str,
    id_column: str,
    item_id: str,
    status: str,
    error: str | None = None,
) -> None:
    """Persist a per-video enrichment outcome on the source row so the UI can show how
    many scraped videos became searchable vs expired/failed. Status is one of
    'enriched' | 'expired' | 'failed'. Best-effort: a status write must never break
    enrichment, so failures are logged, not raised."""
    try:
        supabase.update_by_column(
            table, id_column, item_id, {"enrichment_status": status, "enrichment_error": error}
        )
    except (HttpClientError, RuntimeError) as exc:
        logger.warning("Status write failed for %s %s: %s", table, item_id, exc)


def clean_optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None
