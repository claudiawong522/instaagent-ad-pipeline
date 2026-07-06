"""Run-level orchestration behind the CLI: create a run + seed its keywords, and ingest
across a run's stored keyword allocations. Kept out of cli.py so the CLI stays argument
parsing + dispatch (the API layer has its own campaign-flavored variant of run creation
in api/campaigns.create_campaign, which never hard-fails on a keyword-generation blip)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .config import Config
from .ingestion import utc_now_iso
from .keywords import (
    active_keyword_allocations,
    allocate_manual_keywords,
    generate_keyword_allocations,
    insert_keyword_allocations,
)
from .supabase_client import SupabaseClient


def init_run(
    *,
    config: Config,
    supabase: SupabaseClient | None,
    product_name: str,
    category: str | None,
    target_market: str | None,
    notes: str | None,
    campaign_guidelines: str | None,
    keywords: list[str] | None,
    keyword_type: str,
    target_paid_count: int,
    target_ugc_count: int,
    target_tiktok_count: int,
    top_k: int,
    run_config: dict[str, Any],
    dry_run: bool,
) -> dict[str, Any]:
    """Create the product + pipeline_run and seed keywords (manual or Claude-generated).
    A keyword failure after the run row exists marks the run failed rather than leaving a
    half-initialized run behind."""
    if campaign_guidelines:
        run_config["campaign_guidelines"] = campaign_guidelines
    product_payload = {
        "name": product_name,
        "category": category,
        "target_market": target_market,
        "notes": notes,
    }
    run_payload: dict[str, Any] = {
        "status": "created",
        "config": run_config,
        "target_paid_count": target_paid_count,
        "target_ugc_count": target_ugc_count,
        "target_tiktok_count": target_tiktok_count,
        "top_k": top_k,
    }

    def _allocations(run_id: str | None = None):
        if keywords:
            return allocate_manual_keywords(
                keywords,
                target_paid_count=target_paid_count,
                target_ugc_count=target_ugc_count,
                target_tiktok_count=target_tiktok_count,
                keyword_type=keyword_type,
            )
        return generate_keyword_allocations(
            config=config,
            supabase=supabase if run_id else None,
            dry_run=dry_run,
            run_id=run_id,
            product_name=product_name,
            category=category,
            target_market=target_market,
            notes=notes,
            campaign_guidelines=campaign_guidelines,
            target_paid_count=target_paid_count,
            target_ugc_count=target_ugc_count,
            target_tiktok_count=target_tiktok_count,
        ).allocations

    if dry_run:
        return {
            "product": product_payload,
            "pipeline_run": run_payload,
            "keywords": [allocation.__dict__ for allocation in _allocations()],
        }

    if supabase is None:
        raise RuntimeError("Supabase credentials are required unless --dry-run is used.")

    product = supabase.insert("products", product_payload)
    run_payload["product_id"] = product["id"]
    run = supabase.insert("pipeline_runs", run_payload)
    try:
        inserted = insert_keyword_allocations(
            supabase, run_id=run["id"], allocations=_allocations(run["id"])
        )
    except Exception:
        supabase.update_by_id(
            "pipeline_runs",
            run["id"],
            {"status": "failed", "updated_at": utc_now_iso()},
        )
        raise
    return {"product": product, "pipeline_run": run, "keywords": inserted}


def ingest_allocated_keywords(
    *,
    config: Config,
    supabase: SupabaseClient | None,
    run_id: str,
    target_field: str,
    ingest_func: Callable[..., Any],
    page_size: int | None = None,
    input_json: Path | None = None,
    extra_params: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run one ingest function per stored active keyword, sized by that keyword's
    allocation (`target_field`). page_size falls back to each keyword's target count."""
    if dry_run:
        raise RuntimeError("--keyword is required with --dry-run because dry-run cannot load stored keywords.")
    if supabase is None:
        raise RuntimeError("Supabase credentials are required to load stored keyword allocations.")

    rows = active_keyword_allocations(supabase, run_id)
    if not rows:
        raise RuntimeError(f"No active keywords found for run {run_id}.")

    details: list[dict[str, Any]] = []
    fetched = 0
    written = 0
    for row in rows:
        keyword = str(row.get("keyword_text") or "").strip()
        target_count = int(row.get(target_field) or 0)
        if not keyword or target_count <= 0:
            continue
        result = ingest_func(
            config=config,
            supabase=supabase,
            run_id=run_id,
            keyword=keyword,
            target_count=target_count,
            page_size=int(page_size or target_count),
            dry_run=False,
            input_json=input_json,
            extra_params=extra_params or {},
        )
        fetched += result.fetched
        written += result.written
        details.append(
            {
                "keyword": keyword,
                "target_count": target_count,
                "fetched": result.fetched,
                "written": result.written,
            }
        )

    return {"fetched": fetched, "written": written, "keywords": details}
