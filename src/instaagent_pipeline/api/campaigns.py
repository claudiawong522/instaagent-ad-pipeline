"""Campaign (pipeline_run) creation + scraping for the UI.

A "campaign" is a pipeline_run plus its product. The wizard collects product info and
campaign details (name, marketing goals, objective); `create_campaign` writes the product
+ run and seeds keywords (so the scrapers have something to search). The scrape endpoints
kick off the Apify ingestion in a background thread and expose live per-platform counts so
the UI can show "X Facebook ads / X reels / X TikToks scraped".
"""
from __future__ import annotations

import threading
from typing import Any

from ..ad_enrichment import enrich_paid_ads
from ..apify_ads import ingest_apify_ads
from ..apify_organic import ingest_instagram, ingest_tiktok
from ..audience_enrichment import enrich_audience
from ..config import Config
from ..embeddings import ALL_SPACES, embed_items
from ..ingestion import utc_now_iso
from ..keywords import (
    active_keyword_allocations,
    generate_keyword_allocations,
    insert_keyword_allocations,
)
from ..supabase_client import SupabaseClient
from ..organic_enrichment import enrich_organic_items
from .search import _hydrate

# UI platform name -> (ingest function, run target column, Apify page_size).
# page_size mirrors the CLI: the ads actor paginates by target_count, the organic actors use 0.
_PLATFORMS: dict[str, tuple[Any, str, bool]] = {
    "facebook": (ingest_apify_ads, "target_paid_count", True),
    "instagram": (ingest_instagram, "target_ugc_count", False),
    "tiktok": (ingest_tiktok, "target_ugc_count", False),
}

# Scrapes currently running, so the UI can show a spinner and we refuse duplicates. Keyed
# by (run_id, platform). Process-local — fine for the single-worker dev server; a
# multi-worker deploy would track this in the DB instead.
_running: set[tuple[str, str]] = set()
_running_lock = threading.Lock()


def create_campaign(
    config: Config,
    supabase: SupabaseClient,
    *,
    product_name: str,
    category: str | None,
    target_market: str | None,
    notes: str | None,
    campaign_name: str,
    marketing_goals: list[str],
    campaign_objective: str | None,
    target_paid_count: int,
    target_ugc_count: int,
) -> dict[str, Any]:
    """Create the product + pipeline_run and seed keywords. Mirrors cli.init_run, but stores
    the campaign name / marketing goals / objective in the run config and never hard-fails the
    whole campaign if keyword generation hiccups (it leaves a warning so the user can retry)."""
    run_config = {
        "campaign_name": campaign_name,
        "marketing_goals": marketing_goals,
        "campaign_objective": campaign_objective,
        # campaign_guidelines is what the keyword generator reads.
        "campaign_guidelines": campaign_objective,
    }
    product = supabase.insert(
        "products",
        {"name": product_name, "category": category, "target_market": target_market, "notes": notes},
    )
    run = supabase.insert(
        "pipeline_runs",
        {
            "status": "created",
            "config": run_config,
            "product_id": product["id"],
            "target_paid_count": target_paid_count,
            "target_ugc_count": target_ugc_count,
        },
    )

    keyword_count = 0
    warning = None
    try:
        result = generate_keyword_allocations(
            config=config,
            supabase=supabase,
            dry_run=False,
            run_id=run["id"],
            product_name=product_name,
            category=category,
            target_market=target_market,
            notes=notes,
            campaign_guidelines=campaign_objective,
            target_paid_count=target_paid_count,
            target_ugc_count=target_ugc_count,
        )
        keywords = insert_keyword_allocations(supabase, run_id=run["id"], allocations=result.allocations)
        keyword_count = len(keywords)
    except Exception as exc:  # don't lose the campaign over a keyword-gen blip; let the user retry
        warning = f"keyword generation failed: {exc}"

    return {
        "run_id": str(run["id"]),
        "product_id": str(product["id"]),
        "keyword_count": keyword_count,
        "warning": warning,
    }


def list_campaigns(supabase: SupabaseClient) -> list[dict[str, Any]]:
    """All campaigns (runs) newest-first, with product + campaign config fields."""
    runs = supabase.select(
        "pipeline_runs",
        {
            "select": "id,status,config,target_paid_count,target_ugc_count,created_at,product_id",
            "order": "created_at.desc",
        },
    )
    product_ids = [str(r["product_id"]) for r in runs if r.get("product_id")]
    products = _hydrate(supabase, "products", "id", product_ids, "id,name,category,target_market,notes")
    out: list[dict[str, Any]] = []
    for run in runs:
        product = products.get(str(run.get("product_id"))) or {}
        cfg = run.get("config") or {}
        out.append(
            {
                "run_id": str(run.get("id")),
                "status": run.get("status"),
                "product_name": product.get("name"),
                "category": product.get("category"),
                "target_market": product.get("target_market"),
                "description": product.get("notes"),
                "campaign_name": cfg.get("campaign_name"),
                "marketing_goals": cfg.get("marketing_goals") or [],
                "campaign_objective": cfg.get("campaign_objective"),
                "target_paid_count": run.get("target_paid_count"),
                "target_ugc_count": run.get("target_ugc_count"),
                "created_at": run.get("created_at"),
            }
        )
    return out


def _breakdown(rows: list[dict[str, Any]], video_key: str) -> dict[str, Any]:
    """Bucket a platform's rows by enrichment outcome so the UI can show how many
    scraped videos became searchable vs expired/failed. `total` is the searchable
    universe (rows that have a video to enrich) — rows with no video URL are excluded
    since they can never become searchable. `processing` = has a video but not yet
    enriched (in-flight or queued)."""
    out = {"total": 0, "searchable": 0, "expired": 0, "failed": 0, "processing": 0}
    last: str | None = None
    for row in rows:
        saved = row.get("saved_to_supabase_at")
        if saved and (last is None or saved > last):
            last = saved
        status = row.get("enrichment_status")
        if status == "enriched":
            out["searchable"] += 1
        elif status == "expired":
            out["expired"] += 1
        elif status == "failed":
            out["failed"] += 1
        elif row.get(video_key):
            out["processing"] += 1
        else:
            continue  # no video to enrich — not part of the searchable universe
        out["total"] += 1
    out["last_scraped"] = last
    return out


def _platform_stats(prefix: str, b: dict[str, Any]) -> dict[str, Any]:
    return {
        f"{prefix}_searchable": b["searchable"],
        f"{prefix}_expired": b["expired"],
        f"{prefix}_failed": b["failed"],
        f"{prefix}_processing": b["processing"],
        f"{prefix}_total": b["total"],
        f"{prefix}_last_scraped": b["last_scraped"],
    }


def scrape_stats(supabase: SupabaseClient, run_id: str) -> dict[str, Any]:
    """Live per-platform scrape health: searchable / expired / failed / processing counts,
    last-scraped time, and which platforms are mid-scrape. Two selects (paid + organic), bucketed
    in Python; fine at current scale (revisit with a count RPC if a run holds 10k+ items)."""
    cols = "enrichment_status,saved_to_supabase_at"
    paid = supabase.select("paid_ads", {"select": f"{cols},video", "run_id": f"eq.{run_id}", "limit": "100000"})
    organic = supabase.select(
        "ugc_items", {"select": f"{cols},video_url,source", "run_id": f"eq.{run_id}", "limit": "100000"}
    )
    fb = _breakdown(paid, "video")
    ig = _breakdown([r for r in organic if r.get("source") == "instagram"], "video_url")
    tt = _breakdown([r for r in organic if r.get("source") == "tiktok"], "video_url")
    with _running_lock:
        running = sorted(p for (r, p) in _running if r == run_id)
    return {
        "run_id": run_id,
        # `*_ads`/`*_reels`/`tiktoks` are the headline "searchable" counts the tiles show
        # (per product: the scraped number reflects successful videos only).
        "facebook_ads": fb["searchable"],
        "instagram_reels": ig["searchable"],
        "tiktoks": tt["searchable"],
        **_platform_stats("facebook", fb),
        **_platform_stats("instagram", ig),
        **_platform_stats("tiktok", tt),
        "running": running,
    }


def trigger_scrape(
    config: Config, run_id: str, platform: str, target_count: int | None = None
) -> dict[str, Any]:
    """Kick off the Apify scrape for one platform in a background thread; return immediately.

    target_count, if given, is the new TOTAL to fetch for this platform; it's split across the
    run's keywords. None falls back to each keyword's stored allocation (the create-time target).
    """
    if platform not in _PLATFORMS:
        raise ValueError(f"unknown platform {platform!r}; expected one of {sorted(_PLATFORMS)}")
    key = (run_id, platform)
    with _running_lock:
        if key in _running:
            return {"started": False, "platform": platform, "reason": "already running"}
        _running.add(key)
    threading.Thread(target=_run_scrape, args=(config, run_id, platform, target_count), daemon=True).start()
    return {"started": True, "platform": platform}


def _run_scrape(config: Config, run_id: str, platform: str, target_count: int | None = None) -> None:
    """Full chain so scraped items become searchable: ingest → enrich (downloads video, vision,
    uploads to Storage) → audience fields → embed (search + icp). Each stage skips already-done
    items, so it's safe to re-run. Long-running (minutes) — that's why it lives in a thread."""
    ingest_func, target_field, ads_pagesize = _PLATFORMS[platform]
    is_paid = target_field == "target_paid_count"
    # Fresh client for the thread — don't share the request handler's session across threads.
    supabase = SupabaseClient(config.supabase_url, config.supabase_key)
    try:
        # Stage 1 — ingest: fetch from Apify, write rows to paid_ads/ugc_items.
        rows = active_keyword_allocations(supabase, run_id)
        valid = [r for r in rows if str(r.get("keyword_text") or "").strip()]
        # Split a requested total evenly across the keywords (so "fetch 100" ≈ 100 items, not
        # 100 per keyword). Without an override, each keyword uses its stored allocation.
        per_keyword = max(1, target_count // len(valid)) if (target_count and valid) else None
        for row in valid:
            keyword = str(row.get("keyword_text")).strip()
            target = per_keyword if per_keyword is not None else int(row.get(target_field) or 0)
            if target <= 0:
                continue
            ingest_func(
                config=config,
                supabase=supabase,
                run_id=run_id,
                keyword=keyword,
                target_count=target,
                page_size=target if ads_pagesize else 0,
                dry_run=False,
                input_json=None,
                extra_params={},
            )

        # Stage 2 — enrich: download each new video → Gemini vision (ai_description, tone…) →
        # upload mp4 + thumbnail to Supabase Storage → write item_enrichments.
        if is_paid:
            enrich_paid_ads(config=config, supabase=supabase, run_id=run_id, limit=10000, dry_run=False)
        else:
            enrich_organic_items(config=config, supabase=supabase, run_id=run_id, limit=10000, dry_run=False)
        # Audience fields (target_generation etc.) — must land before the icp embed reads them.
        enrich_audience(config=config, supabase=supabase, run_id=run_id, source="all", dry_run=False)

        # Stage 3 — embed both spaces so the new items are searchable. Skips already-embedded.
        embed_items(config=config, supabase=supabase, run_id=run_id, spaces=ALL_SPACES, dry_run=False)
    except Exception as exc:  # background thread — surface to the server log, nothing to return to
        print(f"[scrape] run={run_id} platform={platform} failed: {exc}")
    finally:
        with _running_lock:
            _running.discard((run_id, platform))
