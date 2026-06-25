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

from ..apify_ads import ingest_apify_ads
from ..apify_ugc import ingest_instagram, ingest_tiktok
from ..config import Config
from ..ingestion import utc_now_iso
from ..keywords import (
    active_keyword_allocations,
    generate_keyword_allocations,
    insert_keyword_allocations,
)
from ..supabase_client import SupabaseClient
from .search import _hydrate

# UI platform name -> (ingest function, run target column, Apify page_size).
# page_size mirrors the CLI: the ads actor paginates by target_count, the UGC actors use 0.
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
                "campaign_name": cfg.get("campaign_name"),
                "marketing_goals": cfg.get("marketing_goals") or [],
                "campaign_objective": cfg.get("campaign_objective"),
                "target_paid_count": run.get("target_paid_count"),
                "target_ugc_count": run.get("target_ugc_count"),
                "created_at": run.get("created_at"),
            }
        )
    return out


def _count(supabase: SupabaseClient, table: str, params: dict[str, str]) -> int:
    # No PostgREST count header exposed on the client, so select the run_id column (tiny) and
    # length it. Fine at current scale; revisit with a count RPC if a run holds 10k+ items.
    rows = supabase.select(table, {"select": "run_id", "limit": "100000", **params})
    return len(rows)


def scrape_stats(supabase: SupabaseClient, run_id: str) -> dict[str, Any]:
    """Live scraped counts for a run, plus which platforms are mid-scrape."""
    with _running_lock:
        running = sorted(p for (r, p) in _running if r == run_id)
    return {
        "run_id": run_id,
        "facebook_ads": _count(supabase, "paid_ads", {"run_id": f"eq.{run_id}"}),
        "instagram_reels": _count(supabase, "ugc_items", {"run_id": f"eq.{run_id}", "source": "eq.instagram"}),
        "tiktoks": _count(supabase, "ugc_items", {"run_id": f"eq.{run_id}", "source": "eq.tiktok"}),
        "running": running,
    }


def trigger_scrape(config: Config, run_id: str, platform: str) -> dict[str, Any]:
    """Kick off the Apify scrape for one platform in a background thread; return immediately."""
    if platform not in _PLATFORMS:
        raise ValueError(f"unknown platform {platform!r}; expected one of {sorted(_PLATFORMS)}")
    key = (run_id, platform)
    with _running_lock:
        if key in _running:
            return {"started": False, "platform": platform, "reason": "already running"}
        _running.add(key)
    threading.Thread(target=_run_scrape, args=(config, run_id, platform), daemon=True).start()
    return {"started": True, "platform": platform}


def _run_scrape(config: Config, run_id: str, platform: str) -> None:
    ingest_func, target_field, ads_pagesize = _PLATFORMS[platform]
    # Fresh client for the thread — don't share the request handler's session across threads.
    supabase = SupabaseClient(config.supabase_url, config.supabase_key)
    try:
        rows = active_keyword_allocations(supabase, run_id)
        for row in rows:
            keyword = str(row.get("keyword_text") or "").strip()
            target = int(row.get(target_field) or 0)
            if not keyword or target <= 0:
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
    except Exception as exc:  # background thread — surface to the server log, nothing to return to
        print(f"[scrape] run={run_id} platform={platform} failed: {exc}")
    finally:
        with _running_lock:
            _running.discard((run_id, platform))
