"""UGC vision enrichment — mirrors ad_enrichment for ugc_items.

One multimodal (Gemini via OpenRouter) call per UGC video: transcript + ai_description
+ the trimmed analysis fields, plus persisting the video/thumbnail to Supabase Storage.
Reuses the paid-ad enrichment schema, prompt, request body, and media-persist helper so
paid + UGC reach column parity and share one embedding space.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .ad_enrichment import (
    OPENROUTER_BASE_URL,
    OPENROUTER_CHAT_COMPLETIONS_ENDPOINT,
    OPENROUTER_PROVIDER,
    PAID_AD_ANALYSIS_COLUMNS,
    EnrichmentResult,
    fetch_video_bytes,
    is_probable_video_url,
    openrouter_request_body,
    openrouter_usage,
    parse_enrichment_response,
    persist_media,
)
from .apify_transcripts import upsert_or_insert
from .config import Config
from .http_client import HttpClientError, request_json
from .ingestion import complete_query, log_api_usage, log_failed_query, start_query, utc_now_iso
from .supabase_client import SupabaseClient

logger = logging.getLogger(__name__)

UGC_SELECT_COLUMNS = "id,video_url,cover,description,handle,user_handle,hashtags,video_topic"


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

    if not config.openrouter_api_key and input_json is None:
        raise RuntimeError("OPENROUTER_API_KEY is required unless --input-json is used.")

    for candidate in candidates:
        result.attempted += 1
        try:
            written = enrich_ugc_item(
                config=config,
                supabase=supabase,
                run_id=run_id,
                candidate=candidate,
                input_json=input_json,
                timeout=timeout,
            )
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
            "analyzed_at": "is.null",
            "order": "saved_to_supabase_at.asc",
            "limit": str(max(limit * 2, limit)),
        },
    )
    candidates: list[UgcEnrichmentCandidate] = []
    skipped = 0
    for row in rows:
        ugc_item_id = str(row.get("id") or "")
        video_url = str(row.get("video_url") or "")
        if not ugc_item_id:
            continue
        if not is_probable_video_url(video_url):
            skipped += 1
            continue
        candidates.append(
            UgcEnrichmentCandidate(
                ugc_item_id=ugc_item_id,
                video_url=video_url,
                thumbnail_url=str(row.get("cover") or "") or None,
                context={
                    key: row.get(key)
                    for key in ("description", "handle", "user_handle", "hashtags", "video_topic")
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
    endpoint = OPENROUTER_CHAT_COMPLETIONS_ENDPOINT
    provider = f"{OPENROUTER_PROVIDER}:{config.openrouter_model}"
    request_params = {
        "model": config.openrouter_model,
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
    try:
        if input_json:
            body = json.loads(input_json.read_text())
        else:
            video_bytes = fetch_video_bytes(candidate.video_url, timeout=timeout)
            persist_media(
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
            response = request_json(
                "POST",
                f"{OPENROUTER_BASE_URL}{endpoint}",
                headers={"Authorization": f"Bearer {config.openrouter_api_key}"},
                body=openrouter_request_body(
                    model=config.openrouter_model,
                    video_bytes=video_bytes,
                    ad_copy=candidate.context,
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
                "external_id": candidate.ugc_item_id,
                "payload_json": body,
            },
        )
    if analysis is None:
        return False

    transcript_text = analysis.get("transcript_text")
    if isinstance(transcript_text, str) and transcript_text.strip():
        upsert_or_insert(
            supabase,
            "ugc_transcripts",
            {
                "ugc_item_id": candidate.ugc_item_id,
                "transcript_text": transcript_text.strip(),
                "transcript_segments": analysis.get("transcript_segments") or None,
                "transcript_source": f"{OPENROUTER_PROVIDER}:{config.openrouter_model}",
            },
            "ugc_item_id,transcript_source",
        )

    payload = {key: analysis.get(key) for key in PAID_AD_ANALYSIS_COLUMNS if key in analysis}
    payload["analysis_model"] = config.openrouter_model
    payload["analyzed_at"] = utc_now_iso()
    supabase.update_by_id("ugc_items", candidate.ugc_item_id, payload)
    return True
