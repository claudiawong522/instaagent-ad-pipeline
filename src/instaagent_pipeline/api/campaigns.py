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
from ..costs import estimate_cost, reconcile_actual_cost, reconstruct_history
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
    "tiktok": (ingest_tiktok, "target_tiktok_count", False),
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
    target_tiktok_count: int,
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
            "target_tiktok_count": target_tiktok_count,
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
            target_tiktok_count=target_tiktok_count,
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
            "select": "id,status,config,target_paid_count,target_ugc_count,target_tiktok_count,created_at,product_id",
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
                "target_tiktok_count": run.get("target_tiktok_count"),
                "created_at": run.get("created_at"),
            }
        )
    return out


def update_campaign(
    supabase: SupabaseClient,
    run_id: str,
    *,
    product_name: str,
    category: str | None,
    target_market: str | None,
    notes: str | None,
    campaign_name: str,
    marketing_goals: list[str],
    campaign_objective: str | None,
) -> dict[str, Any]:
    """Edit a campaign's details in place: the product fields and the run's campaign config
    (name / goals / objective). Does NOT regenerate keywords — those are seeded at create time,
    so editing the objective here won't re-seed them (see future-add-ons.md)."""
    runs = supabase.select(
        "pipeline_runs", {"select": "id,config,product_id", "id": f"eq.{run_id}", "limit": "1"}
    )
    if not runs:
        raise ValueError(f"campaign {run_id} not found")
    run = runs[0]
    supabase.update_by_id(
        "products",
        str(run["product_id"]),
        {"name": product_name, "category": category, "target_market": target_market, "notes": notes},
    )
    config = dict(run.get("config") or {})
    config.update(
        {
            "campaign_name": campaign_name,
            "marketing_goals": marketing_goals,
            "campaign_objective": campaign_objective,
            # keep campaign_guidelines in sync — it's the key the keyword generator reads.
            "campaign_guidelines": campaign_objective,
        }
    )
    supabase.update_by_id("pipeline_runs", run_id, {"config": config})
    return {"run_id": run_id, "product_id": str(run["product_id"])}


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
    config: Config,
    run_id: str,
    platform: str,
    target_count: int | None = None,
    estimated_cost_usd: float | None = None,
) -> dict[str, Any]:
    """Kick off the Apify scrape for one platform in a background thread; return immediately.

    target_count, if given, is the new TOTAL to fetch for this platform; it's split across the
    run's keywords. None falls back to each keyword's stored allocation (the create-time target).
    estimated_cost_usd is the pre-scrape cost estimate from the UI (recorded for the scrape history).
    """
    if platform not in _PLATFORMS:
        raise ValueError(f"unknown platform {platform!r}; expected one of {sorted(_PLATFORMS)}")
    key = (run_id, platform)
    with _running_lock:
        if key in _running:
            return {"started": False, "platform": platform, "reason": "already running"}
        _running.add(key)
    threading.Thread(
        target=_run_scrape, args=(config, run_id, platform, target_count, estimated_cost_usd), daemon=True
    ).start()
    return {"started": True, "platform": platform}


def list_scrape_events(supabase: SupabaseClient, run_id: str) -> dict[str, Any]:
    """Unified per-scrape cost history for a run, newest-first: each row is one platform scrape with
    its date/time and total cost (Apify + enrichment + embeddings, summed). Scrapes triggered from
    the UI are exact (cost_kind 'actual' once finished, 'estimate' while running); spend that
    predates tracking is reconstructed per-platform from api_usage (cost_kind 'reconstructed')."""
    tracked = supabase.select(
        "scrape_events",
        {
            "select": "id,platform,items_ingested,estimated_cost_usd,actual_cost_usd,status,started_at",
            "run_id": f"eq.{run_id}",
            "order": "started_at.desc",
            "limit": "200",
        },
    )

    def _num(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    events: list[dict[str, Any]] = []
    for r in tracked:
        done = r.get("actual_cost_usd") is not None
        events.append(
            {
                "id": str(r.get("id")),
                "platform": r.get("platform"),
                "when": r.get("started_at"),
                "cost_usd": round(_num(r["actual_cost_usd"]) if done else _num(r.get("estimated_cost_usd")), 4),
                "cost_kind": "actual" if done else "estimate",
                "items": r.get("items_ingested"),
                "status": r.get("status"),
            }
        )

    # Reconstruct pre-tracking spend from api_usage that the tracked events don't already cover.
    cutoff = tracked[-1].get("started_at") if tracked else None
    for h in reconstruct_history(supabase, run_id, before_iso=cutoff):
        events.append(
            {
                "id": f"hist-{h['platform']}-{h['when']}",
                "platform": h["platform"],
                "when": h["when"],
                "cost_usd": h["cost_usd"],
                "cost_kind": "reconstructed",
                "items": h["items"],
                "status": "done",
            }
        )

    events.sort(key=lambda e: e["when"] or "", reverse=True)
    return {
        "events": events,
        "total_spent_usd": round(sum(e["cost_usd"] for e in events), 4),
        "total_actual_usd": round(sum(e["cost_usd"] for e in events if e["cost_kind"] != "estimate"), 4),
    }


def _run_scrape(
    config: Config,
    run_id: str,
    platform: str,
    target_count: int | None = None,
    estimated_cost_usd: float | None = None,
) -> None:
    """Full chain so scraped items become searchable: ingest → enrich (downloads video, vision,
    uploads to Storage) → audience fields → embed (search + icp). Each stage skips already-done
    items, so it's safe to re-run. Long-running (minutes) — that's why it lives in a thread."""
    ingest_func, target_field, ads_pagesize = _PLATFORMS[platform]
    is_paid = target_field == "target_paid_count"
    # Fresh client for the thread — don't share the request handler's session across threads.
    supabase = SupabaseClient(config.supabase_url, config.supabase_key)
    # Record the scrape so the UI can show its cost. Fall back to a server-side estimate if the UI
    # didn't send one (estimate treats the whole requested total as new items). Best-effort — cost
    # bookkeeping must never block the scrape (e.g. if migration 022 hasn't been applied yet).
    estimate = estimated_cost_usd if estimated_cost_usd is not None else estimate_cost(platform, target_count or 0)
    event_id: str | None = None
    started_at: str | None = None
    try:
        event = supabase.insert(
            "scrape_events",
            {"run_id": run_id, "platform": platform, "target_count": target_count, "estimated_cost_usd": estimate},
        )
        event_id, started_at = event.get("id"), event.get("started_at")
    except Exception as exc:
        print(f"[scrape] run={run_id} could not record scrape_event: {exc}")
    items_ingested = 0
    failed = False
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
            result = ingest_func(
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
            items_ingested += getattr(result, "written", 0) or 0

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
        failed = True
        print(f"[scrape] run={run_id} platform={platform} failed: {exc}")
    finally:
        # Reconcile the real spend (Apify USD + token-priced LLM/embeds) for this scrape's window.
        if event_id:
            try:
                actual = reconcile_actual_cost(supabase, run_id, started_at) if started_at else None
                supabase.update_by_id(
                    "scrape_events",
                    str(event_id),
                    {
                        "actual_cost_usd": actual,
                        "items_ingested": items_ingested,
                        "status": "failed" if failed else "done",
                        "finished_at": utc_now_iso(),
                    },
                )
            except Exception as exc:  # never let cost bookkeeping mask the scrape outcome
                print(f"[scrape] run={run_id} cost reconcile failed: {exc}")
        with _running_lock:
            _running.discard((run_id, platform))
