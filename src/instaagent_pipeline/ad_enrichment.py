from __future__ import annotations

import base64
import json
import ssl
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .apify_transcripts import upsert_or_insert
from .config import Config
from .http_client import HttpClientError, request_json
from .ingestion import complete_query, log_api_usage, log_failed_query, start_query, utc_now_iso
from .supabase_client import SupabaseClient


OPENROUTER_PROVIDER = "openrouter"
OPENROUTER_BASE_URL = "https://openrouter.ai"
OPENROUTER_CHAT_COMPLETIONS_ENDPOINT = "/api/v1/chat/completions"
# OpenRouter forwards arbitrary video to Gemini only as base64 data URLs, so the
# video bytes are fetched in memory per ad; nothing is written to disk.
INLINE_VIDEO_MAX_BYTES = 100 * 1024 * 1024

# paid_ads columns written by the enrichment response, in addition to
# analysis_model/analyzed_at bookkeeping. Keys absent from the model JSON
# stay untouched; explicit nulls are written as null.
PAID_AD_ANALYSIS_COLUMNS = (
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
    "color_palette",
    "has_face",
    "face_count",
    "gender",
    "age",
    "race",
    "hair_color",
    "has_product",
    "has_text_overlay",
    "is_ai_generated",
    "is_trending_format",
    "brand_mentioned",
    "persona",
    "emotional_drivers",
    "market_target",
    "product_category",
    "creative_targeting",
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
        "color_palette": NULLABLE_STRING_ARRAY,
        "has_face": NULLABLE_BOOLEAN,
        "face_count": NULLABLE_INTEGER,
        "gender": NULLABLE_STRING,
        "age": NULLABLE_INTEGER,
        "race": NULLABLE_STRING,
        "hair_color": NULLABLE_STRING,
        "has_product": NULLABLE_BOOLEAN,
        "has_text_overlay": NULLABLE_BOOLEAN,
        "is_ai_generated": NULLABLE_BOOLEAN,
        "is_trending_format": NULLABLE_BOOLEAN,
        "brand_mentioned": NULLABLE_STRING_ARRAY,
        "persona": NULLABLE_STRING,
        "emotional_drivers": NULLABLE_STRING_ARRAY,
        "market_target": NULLABLE_STRING,
        "product_category": NULLABLE_STRING,
        "creative_targeting": NULLABLE_STRING,
        "niches": NULLABLE_STRING_ARRAY,
        "time_product_was_mentioned": NULLABLE_NUMBER,
    },
    "required": ["transcript_text", "transcript_segments", *PAID_AD_ANALYSIS_COLUMNS],
}

ENRICHMENT_PROMPT = """
You analyze a paid social video ad for a creative-intelligence pipeline.
Watch the video and use the ad copy below for context.

Tasks:
1. Transcribe all spoken audio verbatim into transcript_text. Provide
   transcript_segments with start/end seconds per spoken sentence. If there
   is no speech, set transcript_text to null and transcript_segments to null.
2. Extract creative metadata. Use null for anything not inferable.
   - hook: the attention-grabbing opening line or visual device, quoted or described in one sentence.
   - persona: the ICP (ideal customer profile) this ad targets, one concise phrase.
   - target_demographic: audience descriptor such as "women 25-34 with sensitive skin".
   - content_format: e.g. talking_head, ugc_testimonial, demo, before_after, voiceover_broll, skit, unboxing, tutorial.
   - content_tone, content_category, main_category, video_topic, visual_style, setting: short lowercase phrases.
   - primary_emotion: dominant emotion the ad evokes.
   - emotional_drivers: list of persuasion levers, e.g. ["fear of missing out", "social proof"].
   - market_target: market/region/segment if inferable.
   - product_category: e.g. skincare, supplements, apparel.
   - creative_targeting: who the creative itself addresses and how.
   - niches: list of niche descriptors.
   - color_palette: list of dominant colors as lowercase names or hex.
   - production_quality: one of low, medium, high, professional.
   - has_face/face_count/gender/age/race/hair_color: about the primary on-screen person; gender is one of female, male, mixed, none; age is the approximate age of the primary person.
   - has_product: whether the product is shown on screen.
   - has_text_overlay: whether burned-in captions or text overlays appear.
   - is_ai_generated: whether the footage or voice appears AI-generated.
   - is_trending_format: whether the ad uses a recognizable trending social format.
   - time_product_was_mentioned: seconds into the video when the product is first mentioned or shown, null if never.
   - brand_mentioned: list of brand names spoken or shown.

Ad copy context:
{ad_copy}
""".strip()


@dataclass
class PaidAdEnrichmentCandidate:
    paid_ad_row_id: str
    ad_archive_id: str
    video_url: str
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

    if not config.openrouter_api_key and input_json is None:
        raise RuntimeError("OPENROUTER_API_KEY is required unless --input-json is used.")

    for candidate in candidates:
        result.attempted += 1
        try:
            written = enrich_paid_ad(
                config=config,
                supabase=supabase,
                run_id=run_id,
                candidate=candidate,
                input_json=input_json,
                timeout=timeout,
            )
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
                "paid_ad_row_id,id,video,headline,description,cta_title,cta_type,"
                "name,link_url,display_format"
            ),
            "run_id": f"eq.{run_id}",
            "video": "not.is.null",
            "analyzed_at": "is.null",
            "order": "saved_to_supabase_at.asc",
            "limit": str(max(limit * 5, limit)),
        },
    )

    candidates: list[PaidAdEnrichmentCandidate] = []
    skipped_unsupported = 0
    for row in rows:
        paid_ad_row_id = str(row.get("paid_ad_row_id") or "")
        video_url = str(row.get("video") or "")
        if not paid_ad_row_id:
            continue
        if not is_probable_video_url(video_url):
            skipped_unsupported += 1
            continue

        candidates.append(
            PaidAdEnrichmentCandidate(
                paid_ad_row_id=paid_ad_row_id,
                ad_archive_id=str(row.get("id") or ""),
                video_url=video_url,
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
    endpoint = OPENROUTER_CHAT_COMPLETIONS_ENDPOINT
    provider = f"{OPENROUTER_PROVIDER}:{config.openrouter_model}"
    request_params = {
        "model": config.openrouter_model,
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
    try:
        if input_json:
            body = json.loads(input_json.read_text())
        else:
            video_bytes = fetch_video_bytes(candidate.video_url, timeout=timeout)
            response = request_json(
                "POST",
                f"{OPENROUTER_BASE_URL}{endpoint}",
                headers={"Authorization": f"Bearer {config.openrouter_api_key}"},
                body=openrouter_request_body(
                    model=config.openrouter_model,
                    video_bytes=video_bytes,
                    ad_copy=candidate.ad_copy,
                ),
                timeout=timeout,
            )
            body = response.body
            response_headers = response.headers
            response_status = response.status

        analysis = parse_enrichment_response(body)
        log_api_usage(
            supabase=supabase,
            dry_run=False,
            run_id=run_id,
            provider=provider,
            endpoint=endpoint,
            status=response_status,
            response_count=1 if analysis is not None else 0,
            headers=response_headers,
            metadata={"model": config.openrouter_model, "usage": openrouter_usage(body)},
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
                metadata={"model": config.openrouter_model},
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
                "provider": OPENROUTER_PROVIDER,
                "endpoint": endpoint,
                "external_id": candidate.ad_archive_id or candidate.paid_ad_row_id,
                "payload_json": body,
            },
        )
    if analysis is None:
        return False

    transcript_text = clean_optional_text(analysis.get("transcript_text"))
    if transcript_text:
        upsert_or_insert(
            supabase,
            "paid_ad_transcripts",
            {
                "paid_ad_row_id": candidate.paid_ad_row_id,
                "transcript_text": transcript_text,
                "transcript_segments": analysis.get("transcript_segments") or None,
                "transcript_source": f"{OPENROUTER_PROVIDER}:{config.openrouter_model}",
            },
            "paid_ad_row_id,transcript_source",
        )

    payload = {key: analysis.get(key) for key in PAID_AD_ANALYSIS_COLUMNS if key in analysis}
    payload["analysis_model"] = config.openrouter_model
    payload["analyzed_at"] = utc_now_iso()
    supabase.update_by_column("paid_ads", "paid_ad_row_id", candidate.paid_ad_row_id, payload)
    return True


def openrouter_request_body(
    *,
    model: str,
    video_bytes: bytes,
    ad_copy: dict[str, Any],
) -> dict[str, Any]:
    data_url = "data:video/mp4;base64," + base64.b64encode(video_bytes).decode("ascii")
    prompt = ENRICHMENT_PROMPT.format(ad_copy=json.dumps(ad_copy, indent=2, sort_keys=True))
    return {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "video_url", "video_url": {"url": data_url}},
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


def is_probable_video_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname)


def fetch_video_bytes(url: str, *, timeout: int) -> bytes:
    request = Request(url, headers={"User-Agent": "instaagent-ad-pipeline/0.1"})
    try:
        with urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
            data = response.read(INLINE_VIDEO_MAX_BYTES + 1)
    except HTTPError as exc:
        raise HttpClientError(f"HTTP {exc.code} fetching video {url}", status=exc.code) from exc
    except (URLError, OSError) as exc:
        raise HttpClientError(f"Network error fetching video {url}: {getattr(exc, 'reason', exc)}") from exc
    if len(data) > INLINE_VIDEO_MAX_BYTES:
        raise RuntimeError(f"Video at {url} exceeds the {INLINE_VIDEO_MAX_BYTES} byte inline limit.")
    return data


def clean_optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None
