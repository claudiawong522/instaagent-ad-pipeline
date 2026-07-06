"""Keyword-free viral-format discovery for the UI.

Unlike a campaign scrape (product- and keyword-scoped), discovery pulls TikTok's For You
feed with no search term to study winning *formats* regardless of product. It writes to
organic_items under a single sentinel "Viral Discovery" pipeline_run (pipeline_runs.product_id
is NOT NULL, so the run needs a product). One Discover click runs the full chain in a
background thread so the items become searchable and correctly scored:

    ingest_tiktok_trends -> enrich (video/vision) -> audience -> embed
        -> backfill follower counts -> recompute virality

The follower backfill + recompute matter: trend items arrive with no follower count, so
they're first scored engagement-only, which under-scores mega-viral hits whose reach
dwarfs their follower base. Status is read via the existing /campaigns/{run_id}/scrape-stats.
"""
from __future__ import annotations

import threading
from typing import Any

from ..apify_organic import (
    backfill_tiktok_followers,
    ingest_tiktok_trends,
    recompute_tiktok_virality,
)
from ..audience_enrichment import enrich_audience
from ..config import Config
from ..costs import estimate_cost
from ..embeddings import ALL_SPACES, embed_items
from ..organic_enrichment import enrich_organic_items
from ..supabase_client import SupabaseClient
from . import jobs

# The discovery run is a singleton pseudo-campaign keyed by this product name + a config flag
# (list_campaigns hides runs whose config.discovery is true). "tiktok-trends" is the platform
# label used for the _running guard and the scrape_events cost row.
DISCOVERY_PRODUCT_NAME = "Viral Discovery"
DISCOVERY_PLATFORM = "tiktok-trends"


def find_or_create_discovery_run(config: Config, supabase: SupabaseClient) -> str:
    """Return the singleton discovery run_id, creating its sentinel product + run on first use."""
    products = supabase.select(
        "products", {"select": "id", "name": f"eq.{DISCOVERY_PRODUCT_NAME}", "limit": "1"}
    )
    if products:
        runs = supabase.select(
            "pipeline_runs",
            {"select": "id", "product_id": f"eq.{products[0]['id']}", "limit": "1"},
        )
        if runs:
            return str(runs[0]["id"])
        product_id = products[0]["id"]
    else:
        product = supabase.insert(
            "products",
            {"name": DISCOVERY_PRODUCT_NAME, "category": None, "target_market": None, "notes": None},
        )
        product_id = product["id"]
    run = supabase.insert(
        "pipeline_runs",
        {
            "status": "created",
            "config": {"discovery": True, "campaign_name": DISCOVERY_PRODUCT_NAME},
            "product_id": product_id,
        },
    )
    return str(run["id"])


def trigger_discovery(
    config: Config,
    supabase: SupabaseClient,
    *,
    region: str,
    target_count: int,
    min_views: int,
    estimated_cost_usd: float | None = None,
) -> dict[str, Any]:
    """Kick off a keyword-free trends scrape in a background thread; return immediately with the
    discovery run_id so the UI can poll /campaigns/{run_id}/scrape-stats for live progress."""
    run_id = find_or_create_discovery_run(config, supabase)
    if not jobs.try_claim(run_id, DISCOVERY_PLATFORM):
        return {"started": False, "run_id": run_id, "reason": "already running"}
    threading.Thread(
        target=_run_discovery,
        args=(config, run_id, region, target_count, min_views, estimated_cost_usd),
        daemon=True,
    ).start()
    return {"started": True, "run_id": run_id}


def _run_discovery(
    config: Config,
    run_id: str,
    region: str,
    target_count: int,
    min_views: int,
    estimated_cost_usd: float | None = None,
) -> None:
    """Full chain so discovered videos become searchable AND correctly scored. Long-running
    (minutes) — runs in a thread. Same job skeleton as a campaign scrape (jobs.run_job) but
    keyword-free, plus the follower backfill + virality recompute only the trend source needs."""
    estimate = (
        estimated_cost_usd
        if estimated_cost_usd is not None
        else estimate_cost("tiktok", target_count)
    )

    def work(supabase: SupabaseClient, state: jobs.JobState) -> None:
        # Stage 1 — ingest the For You feed (keyword-free), dropping sub-min_views filler.
        result = ingest_tiktok_trends(
            config=config,
            supabase=supabase,
            run_id=run_id,
            region=region,
            target_count=target_count,
            min_views=min_views,
            dry_run=False,
        )
        state.items_ingested = getattr(result, "written", 0) or 0
        # Stage 2 — SCORING FIRST. Fill follower counts (absent from the trend payload) and
        # re-score virality before the expensive/rate-capped enrichment. Trend items land with
        # followers=None → engagement-only scores that wrongly tank mega-viral hits; this fixes
        # that. Kept ahead of enrichment so a Gemini throttle can't leave scores broken.
        backfill_tiktok_followers(config=config, supabase=supabase, run_id=run_id, dry_run=False)
        recompute_tiktok_virality(config=config, supabase=supabase, run_id=run_id)
        # Stage 3 — make searchable: enrich (video/vision) → audience → embed. Heavier and prone
        # to throttling; isolated so a failure here doesn't undo the scoring or fail the whole run.
        # Re-running discovery is idempotent, so a partial embed finishes on the next pass.
        try:
            enrich_organic_items(config=config, supabase=supabase, run_id=run_id, limit=10000, dry_run=False)
            enrich_audience(config=config, supabase=supabase, run_id=run_id, source="all", dry_run=False)
            embed_items(config=config, supabase=supabase, run_id=run_id, spaces=ALL_SPACES, dry_run=False)
        except Exception as exc:
            print(f"[discover] run={run_id} enrichment/embed incomplete (scores are still correct): {exc}")
        print(f"[discover] run={run_id} region={region} ingested={state.items_ingested}")

    jobs.run_job(
        config=config,
        run_id=run_id,
        platform=DISCOVERY_PLATFORM,
        target_count=target_count,
        estimate=estimate,
        work=work,
        log_prefix="discover",
    )
