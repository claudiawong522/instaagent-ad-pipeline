"""Campaign (pipeline_run) creation + scraping for the UI.

A "campaign" is a pipeline_run plus its product. The wizard collects product info and
campaign details (name, marketing goals, objective); `create_campaign` writes the product
+ run and seeds keywords (so the scrapers have something to search). The scrape endpoints
kick off the Apify ingestion in a background thread and expose live per-platform counts so
the UI can show "X Facebook ads / X reels / X TikToks scraped".
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from ..paid_enrichment import enrich_paid_ads
from ..apify_ads import ingest_apify_ads
from ..apify_organic import ingest_instagram, ingest_tiktok
from ..audience_enrichment import enrich_audience
from ..config import Config
from ..costs import detect_out_of_credits, estimate_cost, reconcile_actual_cost, reconstruct_history
from ..embeddings import ALL_SPACES, embed_items
from ..ingestion import utc_now_iso
from ..keywords import (
    active_keyword_allocations,
    generate_keyword_allocations,
    insert_keyword_allocations,
    split_proportionally,
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

# How long a scrape_event may sit in 'running' with no completion before we treat its worker
# as dead. A job's thread marks the event done/failed in a finally block; if the process is
# killed first (e.g. a `uvicorn --reload` restart), the event stays 'running' forever and its
# items stay stuck at "processing". Real jobs take minutes, so anything older than this whose
# key isn't in the live _running set is an orphan we can safely re-run.
STALE_AFTER_SECONDS = 10 * 60
# Don't auto-resume jobs older than this. Recent kills (a reload) are worth self-healing;
# a run abandoned days ago shouldn't suddenly re-spend when the server next boots.
MAX_RESUME_AGE_SECONDS = 48 * 60 * 60
# Backstop for a worker that hangs *after* fetching (e.g. a stalled vision/embed call): if its
# event sits in 'running' this long, mark it failed so the UI stops spinning forever and offers a
# re-run, and free the _running slot. Sized above a full first post-pass, not a tight SLA — the
# run-wide passes are serialized and skip already-done items, so only one worker pays full cost.
WATCHDOG_SECONDS = 30 * 60

# The post-ingest passes (organic enrich, audience, embed) all cover a run's WHOLE item set, not
# just one scrape's. With several platform workers live at once, running them in parallel just makes
# N workers hammer the same rate-limited vision/embed APIs and crawl — which is what leaves an event
# stuck 'running' long after its fetch is done. Serialize them per run: one lock per run_id, lazily
# created under a guard. Apify ingest stays parallel; only post-processing is single-file.
_postpass_locks: dict[str, threading.Lock] = {}
_postpass_guard = threading.Lock()


def _postpass_lock(run_id: str) -> threading.Lock:
    with _postpass_guard:
        lock = _postpass_locks.get(run_id)
        if lock is None:
            lock = threading.Lock()
            _postpass_locks[run_id] = lock
        return lock


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
        if cfg.get("discovery"):
            continue  # the keyword-free Viral Discovery run lives on the Discover page, not here
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
    """Bucket a platform's rows into the scrape→attempt→searchable funnel.

    `scraped`  = every row ingested (top of funnel).
    `no_video` = scraped but has no video URL → can never be enriched (skipped).
    `total`    = the searchable universe (rows that have a video to enrich).
    `processing` = has a video but no enrichment verdict yet (in-flight / not attempted).
    `searchable` / `expired` / `failed` = the three terminal enrichment verdicts.

    Attempted (searchable + expired + failed) is derived by the UI, not stored here."""
    out = {"scraped": 0, "no_video": 0, "total": 0, "searchable": 0, "expired": 0, "failed": 0, "processing": 0}
    last: str | None = None
    for row in rows:
        out["scraped"] += 1
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
            out["no_video"] += 1  # no video to enrich — never part of the searchable universe
            continue
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
        f"{prefix}_scraped": b["scraped"],
        f"{prefix}_no_video": b["no_video"],
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
    outcome = _last_scrape_outcome(supabase, run_id)
    with _running_lock:
        running = sorted(p for (r, p) in _running if r == run_id)

    def _failed(platform: str) -> bool:
        return platform not in running and (outcome.get(platform) or {}).get("failed", False)

    def _error(platform: str) -> str | None:
        # Don't show a stale out-of-credits message once a fresh scrape for the platform is running.
        return None if platform in running else (outcome.get(platform) or {}).get("error_message")

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
        # Per-platform: did the most recent finished scrape attempt fail? Lets the UI flag a
        # scrape that errored out (e.g. a network drop mid-write) instead of showing it as a
        # silent partial success. A platform that's currently running is never "failed".
        "facebook_scrape_failed": _failed("facebook"),
        "instagram_scrape_failed": _failed("instagram"),
        "tiktok_scrape_failed": _failed("tiktok"),
        # Out-of-credits message for the latest scrape (null when there's no billing problem). Shown
        # by the UI as a "refill and re-run" prompt; set even on an otherwise-'done' scrape whose
        # enrichment ran out of credits.
        "facebook_scrape_error": _error("facebook"),
        "instagram_scrape_error": _error("instagram"),
        "tiktok_scrape_error": _error("tiktok"),
        "running": running,
    }


def _last_scrape_outcome(supabase: SupabaseClient, run_id: str) -> dict[str, dict[str, Any]]:
    """The latest scrape_event per platform as {failed, error_message}. Best-effort: if the
    scrape_events table / error_message column isn't there yet (migration 022/024 unapplied),
    report nothing. 'tiktok-trends' (the Discover run's event) is folded into 'tiktok' so the
    Discover card, which reads tiktok_* stats, picks up its failure / out-of-credits message."""
    try:
        rows = supabase.select(
            "scrape_events",
            {
                "select": "platform,status,error_message,started_at",
                "run_id": f"eq.{run_id}",
                "order": "started_at.desc",
                "limit": "200",
            },
        )
    except Exception:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for r in rows:  # newest-first, so the first row seen per platform is the latest
        platform = r.get("platform")
        if platform == "tiktok-trends":  # discover.DISCOVERY_PLATFORM (literal avoids a circular import)
            platform = "tiktok"
        if platform and platform not in out:
            out[platform] = {"failed": r.get("status") == "failed", "error_message": r.get("error_message")}
    return out


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


def _existing_count(supabase: SupabaseClient, run_id: str, platform: str) -> int:
    """How many items this run already holds for the platform — the 'have' a top-up scrape counts
    against the requested total. Counts every collected row (matches the *_scraped stat), so a
    re-scrape tops up toward the target instead of stacking a fresh full fetch on top."""
    if platform == "facebook":
        rows = supabase.select("paid_ads", {"select": "id", "run_id": f"eq.{run_id}", "limit": "100000"})
    else:
        rows = supabase.select(
            "ugc_items",
            {"select": "id", "run_id": f"eq.{run_id}", "source": f"eq.{platform}", "limit": "100000"},
        )
    return len(rows)


def _watchdog_timeout(config: Config, run_id: str, platform: str, event_id: str) -> None:
    """Fired by a Timer if a worker overruns WATCHDOG_SECONDS. Flips a still-'running' event to
    failed (so the UI offers a re-run instead of spinning forever) and frees the _running slot.
    No-op if the worker already closed the event — the worker cancels this Timer in its finally,
    so this only runs when the worker is genuinely stuck and never reached that finally."""
    supabase = SupabaseClient(config.supabase_url, config.supabase_key)
    try:
        rows = supabase.select("scrape_events", {"select": "status", "id": f"eq.{event_id}", "limit": "1"})
        if rows and rows[0].get("status") == "running":
            supabase.update_by_id(
                "scrape_events",
                event_id,
                {
                    "status": "failed",
                    "error_message": "Scrape timed out — the worker stalled. Re-run to finish.",
                    "finished_at": utc_now_iso(),
                },
            )
            print(f"[scrape] run={run_id} platform={platform} watchdog: stalled scrape marked failed")
    except Exception as exc:
        print(f"[scrape] run={run_id} watchdog update failed: {exc}")
    with _running_lock:
        _running.discard((run_id, platform))


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
    # Backstop a hung worker: if we never reach the finally below in time, this fires and closes the
    # event (see _watchdog_timeout). Cancelled in the finally the moment the worker finishes normally.
    watchdog: threading.Timer | None = None
    if event_id:
        watchdog = threading.Timer(WATCHDOG_SECONDS, _watchdog_timeout, args=(config, run_id, platform, str(event_id)))
        watchdog.daemon = True
        watchdog.start()
    items_ingested = 0
    failed = False
    keyword_errors = 0
    try:
        # Stage 1 — ingest: fetch from Apify, write rows to paid_ads/ugc_items.
        rows = active_keyword_allocations(supabase, run_id)
        valid = [r for r in rows if str(r.get("keyword_text") or "").strip()]
        # The UI always supplies the ceiling. Top up toward it: split only the GAP between
        # target_count and what's already collected — so a re-scrape adds ~target−have new items,
        # not a fresh full fetch stacked on the pile. Distribute the gap by each keyword's stored
        # allocation weight (the create-time split), so a keyword Claude judged heavier pulls
        # proportionally more; falls back to an even split when no weights are stored (legacy runs).
        # The proportional split sums to exactly the gap, keeping the total at or under the target;
        # a gap smaller than the keyword count just leaves some keywords at 0 this round. With no
        # target there's nothing to top up toward, so fetch nothing rather than re-stacking.
        if target_count and valid:
            gap = max(0, target_count - _existing_count(supabase, run_id, platform))
            weights = [int(r.get(target_field) or 0) for r in valid]
            per_keyword_counts = split_proportionally(gap, weights)
        else:
            per_keyword_counts = [0] * len(valid)
        for row, target in zip(valid, per_keyword_counts):
            keyword = str(row.get("keyword_text")).strip()
            if target <= 0:
                continue
            # Isolate each keyword: one keyword erroring (e.g. an Apify/network failure) must not
            # abort the rest of the split, or "fetch 200" silently delivers only the first keyword's
            # share. Record the error and move on; a partial run is flagged failed so the UI offers retry.
            try:
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
            except Exception as exc:
                keyword_errors += 1
                print(f"[scrape] run={run_id} platform={platform} keyword={keyword!r} ingest failed: {exc}")

        # Stages 2–3 are run-wide (they cover every platform's items, not just this scrape's), so
        # serialize them per run — concurrent platform workers would otherwise throttle each other
        # on the same vision/embed APIs. Skip-already-done makes the later workers cheap; the last
        # one through embeds any stragglers. Apify ingest above stayed parallel.
        with _postpass_lock(run_id):
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
        # Worker finished (or errored) on its own — call off the backstop before it can fire.
        if watchdog is not None:
            watchdog.cancel()
        # Reconcile the real spend (Apify USD + token-priced LLM/embeds) for this scrape's window.
        if event_id:
            try:
                actual = reconcile_actual_cost(supabase, run_id, started_at) if started_at else None
                # Did either leg (Apify ingest / LLM enrichment) run out of credits? Detected from
                # the run's failed source_queries so the UI can prompt a top-up + re-run. Set even
                # when status is 'done' (an enrichment credit failure is swallowed per item).
                credit_error = detect_out_of_credits(supabase, run_id, started_at) if started_at else None
                supabase.update_by_id(
                    "scrape_events",
                    str(event_id),
                    {
                        "actual_cost_usd": actual,
                        "items_ingested": items_ingested,
                        # Any keyword erroring = a short delivery, so flag failed (the UI shows it
                        # as a partial and offers retry to fill the gap).
                        "status": "failed" if (failed or keyword_errors) else "done",
                        "error_message": credit_error,
                        "finished_at": utc_now_iso(),
                    },
                )
            except Exception as exc:  # never let cost bookkeeping mask the scrape outcome
                print(f"[scrape] run={run_id} cost reconcile failed: {exc}")
        with _running_lock:
            _running.discard((run_id, platform))


def orphaned_events(supabase: SupabaseClient, run_id: str | None = None) -> list[dict[str, Any]]:
    """scrape_events whose worker was killed before it could finish: status still 'running',
    older than STALE_AFTER_SECONDS, and not in this process's live _running set. These are the
    jobs that leave items stuck at "processing" with no error and never recover on their own."""
    params: dict[str, str] = {
        "select": "id,run_id,platform,started_at",
        "status": "eq.running",
        "order": "started_at.desc",
        "limit": "200",
    }
    if run_id:
        params["run_id"] = f"eq.{run_id}"
    try:
        rows = supabase.select("scrape_events", params)
    except Exception:  # table missing (migration 022 unapplied) — nothing to recover
        return []
    now = datetime.now(timezone.utc)
    stale_before = (now - timedelta(seconds=STALE_AFTER_SECONDS)).isoformat()
    with _running_lock:
        live = set(_running)
    out: list[dict[str, Any]] = []
    for r in rows:
        started = r.get("started_at") or ""
        if started >= stale_before:
            continue  # young enough it may still be legitimately starting up
        if (str(r.get("run_id")), r.get("platform")) in live:
            continue  # actually running in this process, not an orphan
        out.append(r)
    return out


def _resume(config: Config, event: dict[str, Any]) -> None:
    """Re-run only the post-ingest stages (enrich → audience → embed) for a killed scrape. The
    ingest already wrote the rows, so we deliberately DON'T re-scrape (no Apify spend); every
    stage skips already-done items, so this just finishes the leftovers and marks the event done."""
    run_id = str(event["run_id"])
    platform = event["platform"]
    event_id = str(event["id"])
    supabase = SupabaseClient(config.supabase_url, config.supabase_key)
    failed = False
    try:
        # facebook is the only paid platform; everything else (instagram, tiktok, tiktok-trends)
        # is organic. Discovery does its scoring before enrichment, so leftovers only need this.
        # Same run-wide passes as a live scrape — serialize per run so a resume can't run them
        # concurrently with a fresh scrape and throttle it.
        with _postpass_lock(run_id):
            if platform == "facebook":
                enrich_paid_ads(config=config, supabase=supabase, run_id=run_id, limit=10000, dry_run=False)
            else:
                enrich_organic_items(config=config, supabase=supabase, run_id=run_id, limit=10000, dry_run=False)
            enrich_audience(config=config, supabase=supabase, run_id=run_id, source="all", dry_run=False)
            embed_items(config=config, supabase=supabase, run_id=run_id, spaces=ALL_SPACES, dry_run=False)
        print(f"[resume] run={run_id} platform={platform} finished leftover enrichment/embed")
    except Exception as exc:
        failed = True
        print(f"[resume] run={run_id} platform={platform} failed: {exc}")
    finally:
        # Reconcile the real spend from api_usage (started_at onward) so an interrupted pull's cost
        # stops showing as the pre-scrape estimate. items_ingested stays as-is: the killed worker's
        # ingest count lived in memory and can't be recovered here, so leave it null (UI shows "—").
        started_at = event.get("started_at")
        try:
            actual = reconcile_actual_cost(supabase, run_id, started_at) if started_at else None
            supabase.update_by_id(
                "scrape_events",
                event_id,
                {
                    "status": "failed" if failed else "done",
                    "actual_cost_usd": actual,
                    "finished_at": utc_now_iso(),
                },
            )
        except Exception as exc:
            print(f"[resume] run={run_id} could not close scrape_event: {exc}")
        with _running_lock:
            _running.discard((run_id, platform))


def resume_orphaned_jobs(config: Config, supabase: SupabaseClient) -> int:
    """Re-run scrape jobs whose worker was killed (e.g. a backend reload), in background threads.
    Called once at startup so a restart self-heals instead of leaving items stuck at "processing"
    forever. Skips jobs older than MAX_RESUME_AGE_SECONDS (abandoned, not worth re-spending on).
    Returns how many were resumed."""
    resume_after = (datetime.now(timezone.utc) - timedelta(seconds=MAX_RESUME_AGE_SECONDS)).isoformat()
    resumed = 0
    for event in orphaned_events(supabase):
        if (event.get("started_at") or "") < resume_after:
            print(f"[resume] skipping stale job run={event.get('run_id')} platform={event.get('platform')} (too old)")
            continue
        key = (str(event["run_id"]), event["platform"])
        with _running_lock:
            if key in _running:
                continue
            _running.add(key)
        threading.Thread(target=_resume, args=(config, event), daemon=True).start()
        resumed += 1
    return resumed
