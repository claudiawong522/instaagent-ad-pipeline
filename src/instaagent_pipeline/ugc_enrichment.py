"""UGC vision enrichment — mirrors ad_enrichment for ugc_items.

One multimodal (Gemini via OpenRouter) call per UGC video: transcript + ai_description
+ the trimmed analysis fields, plus persisting the video/thumbnail to Supabase Storage.
Reuses the paid-ad enrichment schema, prompt, request body, and media-persist helper so
paid + UGC reach column parity and share one embedding space.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .ad_enrichment import (
    GEMINI_ENDPOINT,
    GEMINI_PROVIDER,
    OPENROUTER_CHAT_COMPLETIONS_ENDPOINT,
    OPENROUTER_PROVIDER,
    PAID_AD_ANALYSIS_COLUMNS,
    EnrichmentResult,
    clean_optional_text,
    existing_enriched_ids,
    fetch_video_bytes,
    gemini_usage,
    is_probable_video_url,
    openrouter_usage,
    parse_enrichment_response,
    parse_gemini_response,
    persist_media,
    record_item_status,
    request_enrichment,
)
from .config import Config
from .http_client import HttpClientError
from .ingestion import complete_query, log_api_usage, log_failed_query, start_query, utc_now_iso
from .supabase_client import SupabaseClient

logger = logging.getLogger(__name__)

UGC_SELECT_COLUMNS = "id,video_url,cover,description,handle,user_handle,hashtags"


@dataclass
class UgcEnrichmentCandidate:
    ugc_item_id: str
    video_url: str
    thumbnail_url: str | None = None
    context: dict[str, Any] = field(default_factory=dict)


def enrich_ugc_items(
    *,
    config: Config,
    supabase: SupabaseClient | None,
    run_id: str,
    limit: int,
    dry_run: bool,
    input_json: Path | None = None,
    timeout: int = 300,
    concurrency: int = 32,
) -> EnrichmentResult:
    if supabase is None:
        raise RuntimeError("Supabase credentials are required to load UGC enrichment candidates.")
    if limit < 1:
        raise ValueError("--limit must be greater than 0.")

    candidates, skipped = ugc_enrichment_candidates(supabase, run_id=run_id, limit=limit)
    result = EnrichmentResult(candidates=len(candidates), skipped_unsupported=skipped)

    if dry_run:
        result.details = [
            {"ugc_item_id": c.ugc_item_id, "video_url": c.video_url, "action": "would_enrich"}
            for c in candidates
        ]
        return result

    if input_json is None:
        if config.enrichment_provider == GEMINI_PROVIDER:
            if not config.gemini_api_key:
                raise RuntimeError("GEMINI_API_KEY is required unless --input-json is used.")
        elif not config.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY is required unless --input-json is used.")

    def _enrich_one(candidate: UgcEnrichmentCandidate) -> bool:
        return enrich_ugc_item(
            config=config,
            supabase=supabase,
            run_id=run_id,
            candidate=candidate,
            input_json=input_json,
            timeout=timeout,
        )

    # I/O-bound per item; fan out across threads (SupabaseClient is stateless per request).
    # Futures are aggregated in the main thread as they complete, so no lock is needed.
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
                result.details.append({"ugc_item_id": candidate.ugc_item_id, "status": "failed", "error": str(exc)})
                continue
            if written:
                result.written += 1
                result.details.append({"ugc_item_id": candidate.ugc_item_id, "status": "written"})
            else:
                result.failed += 1
                result.details.append({"ugc_item_id": candidate.ugc_item_id, "status": "no_analysis"})
    return result


def ugc_enrichment_candidates(
    supabase: SupabaseClient,
    *,
    run_id: str,
    limit: int,
) -> tuple[list[UgcEnrichmentCandidate], int]:
    rows = supabase.select(
        "ugc_items",
        {
            "select": UGC_SELECT_COLUMNS,
            "run_id": f"eq.{run_id}",
            "video_url": "not.is.null",
            "order": "saved_to_supabase_at.asc",
            "limit": str(max(limit * 2, limit)),
        },
    )
    already_enriched = existing_enriched_ids(supabase, run_id, "ugc_item")
    candidates: list[UgcEnrichmentCandidate] = []
    skipped = 0
    for row in rows:
        ugc_item_id = str(row.get("id") or "")
        video_url = str(row.get("video_url") or "")
        if not ugc_item_id:
            continue
        if ugc_item_id in already_enriched:
            continue
        if not is_probable_video_url(video_url):
            skipped += 1
            record_item_status(
                supabase,
                table="ugc_items",
                id_column="id",
                item_id=ugc_item_id,
                status="failed",
                error="unsupported video URL",
            )
            continue
        candidates.append(
            UgcEnrichmentCandidate(
                ugc_item_id=ugc_item_id,
                video_url=video_url,
                thumbnail_url=str(row.get("cover") or "") or None,
                context={
                    key: row.get(key)
                    for key in ("description", "handle", "user_handle", "hashtags")
                    if row.get(key) not in (None, "")
                },
            )
        )
        if len(candidates) >= limit:
            break
    return candidates, skipped


def enrich_ugc_item(
    *,
    config: Config,
    supabase: SupabaseClient,
    run_id: str,
    candidate: UgcEnrichmentCandidate,
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
        "ugc_item_id": candidate.ugc_item_id,
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
    # See enrich_paid_ad: 'download' failure → expired URL; later failure → 'failed'.
    stage = "download"
    try:
        if input_json:
            stage = "analysis"
            body = json.loads(input_json.read_text())
            analysis = parse_gemini_response(body) if is_gemini else parse_enrichment_response(body)
            usage = gemini_usage(body) if is_gemini else openrouter_usage(body)
        else:
            video_bytes = fetch_video_bytes(candidate.video_url, timeout=timeout)
            stage = "analysis"
            media = persist_media(
                supabase,
                run_id=run_id,
                item_table="ugc_items",
                id_column="id",
                item_id=candidate.ugc_item_id,
                video_bytes=video_bytes,
                thumbnail_url=candidate.thumbnail_url,
                subdir="ugc",
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
                ad_copy={},
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
        record_item_status(
            supabase,
            table="ugc_items",
            id_column="id",
            item_id=candidate.ugc_item_id,
            status="expired" if stage == "download" else "failed",
            error=str(exc),
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
                "external_id": candidate.ugc_item_id,
                "payload_json": body,
            },
        )
    if analysis is None:
        record_item_status(
            supabase,
            table="ugc_items",
            id_column="id",
            item_id=candidate.ugc_item_id,
            status="failed",
            error="vision returned no analysis",
        )
        return False

    payload = {key: analysis.get(key) for key in PAID_AD_ANALYSIS_COLUMNS if key in analysis}
    payload.update(
        {
            "run_id": run_id,
            "item_type": "ugc_item",
            "item_id": candidate.ugc_item_id,
            "transcript_text": clean_optional_text(analysis.get("transcript_text")),
            "transcript_segments": analysis.get("transcript_segments") or None,
            "analysis_model": model,
            "analyzed_at": utc_now_iso(),
        }
    )
    supabase.upsert("item_enrichments", payload, "item_type,item_id")
    record_item_status(
        supabase,
        table="ugc_items",
        id_column="id",
        item_id=candidate.ugc_item_id,
        status="enriched",
    )
    return True
