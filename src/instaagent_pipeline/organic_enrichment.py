"""Organic vision enrichment: candidate loading for ugc_items + the shared video flow."""

from __future__ import annotations

from pathlib import Path

from .config import Config
from .media import is_probable_video_url
from .supabase_client import SupabaseClient
from .video_enrichment import (
    EnrichmentCandidate,
    EnrichmentResult,
    ItemKind,
    enrich_items,
    existing_enriched_ids,
    record_item_status,
)

ORGANIC_KIND = ItemKind(
    label="organic",
    table="ugc_items",
    id_column="id",
    item_type="ugc_item",
    storage_subdir="ugc",
    detail_id_key="organic_item_id",
)


def enrich_organic_items(
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
    return enrich_items(
        config=config,
        supabase=supabase,
        run_id=run_id,
        limit=limit,
        dry_run=dry_run,
        kind=ORGANIC_KIND,
        load_candidates=organic_enrichment_candidates,
        input_json=input_json,
        timeout=timeout,
        concurrency=concurrency,
    )


def organic_enrichment_candidates(
    supabase: SupabaseClient,
    *,
    run_id: str,
    limit: int,
) -> tuple[list[EnrichmentCandidate], int]:
    rows = supabase.select(
        "ugc_items",
        {
            "select": "id,video_url,cover",
            "run_id": f"eq.{run_id}",
            "video_url": "not.is.null",
            "order": "saved_to_supabase_at.asc",
            "limit": str(max(limit * 2, limit)),
        },
    )
    already_enriched = existing_enriched_ids(supabase, run_id, ORGANIC_KIND.item_type)
    candidates: list[EnrichmentCandidate] = []
    skipped = 0
    for row in rows:
        organic_item_id = str(row.get("id") or "")
        video_url = str(row.get("video_url") or "")
        if not organic_item_id:
            continue
        if organic_item_id in already_enriched:
            continue
        if not is_probable_video_url(video_url):
            skipped += 1
            record_item_status(
                supabase,
                table=ORGANIC_KIND.table,
                id_column=ORGANIC_KIND.id_column,
                item_id=organic_item_id,
                status="failed",
                error="unsupported video URL",
            )
            continue
        candidates.append(
            EnrichmentCandidate(
                item_id=organic_item_id,
                video_url=video_url,
                thumbnail_url=str(row.get("cover") or "") or None,
            )
        )
        if len(candidates) >= limit:
            break
    return candidates, skipped
