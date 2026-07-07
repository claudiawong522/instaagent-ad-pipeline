"""Paid-ad vision enrichment: candidate loading for paid_ads + the shared video flow."""

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

PAID_AD_KIND = ItemKind(
    label="paid ad",
    table="paid_ads",
    id_column="paid_ad_row_id",
    item_type="paid_ad",
    storage_subdir="paid",
    detail_id_key="paid_ad_row_id",
)

# Copy fields sent to the LLM as context alongside the video.
AD_COPY_COLUMNS = ("headline", "description", "cta_title", "cta_type", "name", "link_url", "display_format")


def enrich_paid_ads(
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
        kind=PAID_AD_KIND,
        load_candidates=paid_ad_enrichment_candidates,
        input_json=input_json,
        timeout=timeout,
        concurrency=concurrency,
    )


def paid_ad_enrichment_candidates(
    supabase: SupabaseClient,
    *,
    run_id: str,
    limit: int,
) -> tuple[list[EnrichmentCandidate], int]:
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

    already_enriched = existing_enriched_ids(supabase, run_id, PAID_AD_KIND.item_type)
    candidates: list[EnrichmentCandidate] = []
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
            record_item_status(
                supabase,
                table=PAID_AD_KIND.table,
                id_column=PAID_AD_KIND.id_column,
                item_id=paid_ad_row_id,
                status="failed",
                error="unsupported video URL",
            )
            continue

        ad_archive_id = str(row.get("id") or "")
        candidates.append(
            EnrichmentCandidate(
                item_id=paid_ad_row_id,
                video_url=video_url,
                thumbnail_url=str(row.get("thumbnail") or row.get("image") or "") or None,
                external_id=ad_archive_id,
                ad_copy={key: row.get(key) for key in AD_COPY_COLUMNS if row.get(key) not in (None, "")},
                extra_ids={"ad_archive_id": ad_archive_id},
            )
        )
        if len(candidates) >= limit:
            break

    return candidates, skipped_unsupported
