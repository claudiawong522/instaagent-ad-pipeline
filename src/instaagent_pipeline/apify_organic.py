"""Organic ingestion via Apify keyword scrapers, replacing TopYappers.

TikTok  -> clockworks/tiktok-scraper        (keyword search; followers native)
Instagram -> data-slayer/instagram-search-reels (keyword search; followers backfilled)

Both write to organic_items. Rows without a usable downloadable video are dropped. The
analysis columns are filled later by the organic vision enrichment.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Callable

from .apify_client import ingest_actor_items, run_apify_actor_items
from .config import Config
from .ingestion import IngestResult
from .normalizers import (
    normalize_instagram_reel,
    normalize_tiktok_item,
    normalize_tiktok_trend_item,
    result_items,
    tiktok_download_url,
    tiktok_trend_video_url,
    tiktok_trend_views,
)
from .virality import recompute_virality
from .supabase_client import SupabaseClient

TIKTOK_ACTOR_ID = "clockworks~tiktok-scraper"
TIKTOK_PROVIDER = "apify:clockworks/tiktok-scraper"
TIKTOK_TREND_ACTOR_ID = "novi~tiktok-trend-api"
TIKTOK_TREND_PROVIDER = "apify:novi/tiktok-trend-api"
INSTAGRAM_ACTOR_ID = "data-slayer~instagram-search-reels"
INSTAGRAM_PROVIDER = "apify:data-slayer/instagram-search-reels"
IG_PROFILE_ACTOR_ID = "apify~instagram-profile-scraper"
IG_PROFILE_PROVIDER = "apify:apify/instagram-profile-scraper"
IG_URL_ACTOR_ID = "apify~instagram-scraper"  # by-URL (directUrls) scrape, for trend example reels
IG_URL_PROVIDER = "apify:apify/instagram-scraper"
INSTAGRAM_PAGE_SIZE = 50  # data-slayer returns ~50-100 reels per page


def _ingest_apify_organic(
    *,
    config: Config,
    supabase: SupabaseClient | None,
    run_id: str,
    keyword: str,
    target_count: int,
    provider: str,
    actor_id: str,
    actor_input: dict[str, Any],
    normalizer: Any,
    has_video: Callable[[dict[str, Any]], bool],
    dry_run: bool,
    input_json: Path | None,
) -> IngestResult:
    return ingest_actor_items(
        config=config,
        supabase=supabase,
        run_id=run_id,
        provider=provider,
        actor_id=actor_id,
        actor_input=actor_input,
        request_params={"actor": actor_id, "keyword": keyword, "actor_input": actor_input},
        # Drop rows without a downloadable video (the no-video rule).
        prepare_items=lambda items: [item for item in items if has_video(item)],
        destination_table="organic_items",
        normalizer=normalizer,
        conflict_columns="run_id,external_id",
        target_count=target_count,
        dry_run=dry_run,
        input_json=input_json,
    )


def ingest_tiktok(
    *,
    config: Config,
    supabase: SupabaseClient | None,
    run_id: str,
    keyword: str,
    target_count: int,
    page_size: int = 0,
    dry_run: bool = False,
    input_json: Path | None = None,
    extra_params: dict[str, Any] | None = None,
) -> IngestResult:
    actor_input: dict[str, Any] = {
        "searchQueries": [keyword],
        "resultsPerPage": target_count,
        "shouldDownloadVideos": True,
    }
    if extra_params:
        actor_input.update(extra_params)
    return _ingest_apify_organic(
        config=config,
        supabase=supabase,
        run_id=run_id,
        keyword=keyword,
        target_count=target_count,
        provider=TIKTOK_PROVIDER,
        actor_id=TIKTOK_ACTOR_ID,
        actor_input=actor_input,
        normalizer=normalize_tiktok_item,
        has_video=lambda item: bool(tiktok_download_url(item)),
        dry_run=dry_run,
        input_json=input_json,
    )


def ingest_tiktok_trends(
    *,
    config: Config,
    supabase: SupabaseClient | None,
    run_id: str,
    region: str,
    target_count: int,
    min_views: int = 0,
    dry_run: bool = False,
    input_json: Path | None = None,
    extra_params: dict[str, Any] | None = None,
) -> IngestResult:
    """Keyword-free viral discovery: novi/tiktok-trend-api returns a country's For You
    feed (no search term). Writes to organic_items like the other organic sources; follower
    counts are absent from the payload and filled later by backfill_tiktok_followers.

    min_views drops low-view feed-filler at ingest — the For You feed isn't a pure viral
    filter (it mixes in brand-new posts still being test-distributed), so a floor keeps
    the pull to genuinely viral content."""
    actor_input: dict[str, Any] = {"region": region, "limit": target_count}
    if extra_params:
        actor_input.update(extra_params)

    def has_video(item: dict[str, Any]) -> bool:
        if not tiktok_trend_video_url(item):
            return False
        return (tiktok_trend_views(item) or 0) >= min_views

    return _ingest_apify_organic(
        config=config,
        supabase=supabase,
        run_id=run_id,
        keyword=f"trending:{region}",
        target_count=target_count,
        provider=TIKTOK_TREND_PROVIDER,
        actor_id=TIKTOK_TREND_ACTOR_ID,
        actor_input=actor_input,
        normalizer=normalize_tiktok_trend_item,
        has_video=has_video,
        dry_run=dry_run,
        input_json=input_json,
    )


def ingest_instagram(
    *,
    config: Config,
    supabase: SupabaseClient | None,
    run_id: str,
    keyword: str,
    target_count: int,
    page_size: int = 0,
    dry_run: bool = False,
    input_json: Path | None = None,
    extra_params: dict[str, Any] | None = None,
) -> IngestResult:
    max_pages = max(1, min(10, math.ceil(target_count / INSTAGRAM_PAGE_SIZE)))
    actor_input: dict[str, Any] = {"query": keyword, "maxPages": max_pages}
    if extra_params:
        actor_input.update(extra_params)
    return _ingest_apify_organic(
        config=config,
        supabase=supabase,
        run_id=run_id,
        keyword=keyword,
        target_count=target_count,
        provider=INSTAGRAM_PROVIDER,
        actor_id=INSTAGRAM_ACTOR_ID,
        actor_input=actor_input,
        normalizer=normalize_instagram_reel,
        has_video=lambda item: bool(item.get("video_url")),
        dry_run=dry_run,
        input_json=input_json,
    )


def _backfill_followers(
    *,
    supabase: SupabaseClient | None,
    run_id: str,
    source: str,
    fetch: Callable[[list[str]], dict[str, int]],
    limit: int,
    dry_run: bool,
) -> dict[str, Any]:
    """Shared follower backfill: find the run's null-follower rows for `source`, dedupe
    them per creator, resolve counts via `fetch`, and write them back."""
    if supabase is None:
        raise RuntimeError(f"Supabase credentials are required for the {source} follower backfill.")
    rows = supabase.select(
        "organic_items",
        {
            "select": "id,user_handle",
            "run_id": f"eq.{run_id}",
            "source": f"eq.{source}",
            "followers": "is.null",
            "limit": str(limit),
        },
    )
    by_user: dict[str, list[str]] = {}
    for row in rows:
        username = str(row.get("user_handle") or "").strip()
        if username and row.get("id"):
            by_user.setdefault(username, []).append(str(row["id"]))
    usernames = list(by_user)
    if not usernames:
        return {"usernames": 0, "updated": 0}
    if dry_run:
        return {"usernames": len(usernames), "updated": 0, "dry_run": True}

    followers_map = fetch(usernames)
    updated = 0
    for username, count in followers_map.items():
        if count is None:
            continue
        for row_id in by_user.get(username, []):
            supabase.update_by_id("organic_items", row_id, {"followers": count})
            updated += 1
    return {"usernames": len(usernames), "resolved": len(followers_map), "updated": updated}


def backfill_instagram_followers(
    *,
    config: Config,
    supabase: SupabaseClient | None,
    run_id: str,
    limit: int = 500,
    dry_run: bool = False,
    input_json: Path | None = None,
) -> dict[str, Any]:
    """Fill the IG follower counts that discovery scrapers omit, via a deduped
    per-creator profile scrape (apify/instagram-profile-scraper)."""
    return _backfill_followers(
        supabase=supabase,
        run_id=run_id,
        source="instagram",
        fetch=lambda usernames: fetch_instagram_followers(config, usernames, input_json=input_json),
        limit=limit,
        dry_run=dry_run,
    )


def fetch_instagram_followers(
    config: Config,
    usernames: list[str],
    *,
    input_json: Path | None = None,
) -> dict[str, int]:
    if input_json:
        items = result_items(json.loads(input_json.read_text()))
    else:
        if not config.apify_api_key:
            raise RuntimeError("APIFY_API_KEY is required for the IG follower backfill.")
        items, _, _, _ = run_apify_actor_items(
            api_key=config.apify_api_key,
            actor_id=IG_PROFILE_ACTOR_ID,
            actor_input={"usernames": usernames},
            target_count=len(usernames),
        )
    out: dict[str, int] = {}
    for item in items:
        username = item.get("username") or item.get("ownerUsername")
        count = item.get("followersCount")
        if count is None:
            count = item.get("followers_count")
        if isinstance(username, str) and isinstance(count, (int, float)):
            out[username] = int(count)
    return out


def backfill_tiktok_followers(
    *,
    config: Config,
    supabase: SupabaseClient | None,
    run_id: str,
    limit: int = 500,
    dry_run: bool = False,
    input_json: Path | None = None,
) -> dict[str, Any]:
    """Fill the TikTok follower counts that the trend API omits, via a deduped per-creator
    profile scrape (clockworks/tiktok-scraper in profiles mode). Mirrors the IG backfill."""
    return _backfill_followers(
        supabase=supabase,
        run_id=run_id,
        source="tiktok",
        fetch=lambda usernames: fetch_tiktok_followers(config, usernames, input_json=input_json),
        limit=limit,
        dry_run=dry_run,
    )


def fetch_tiktok_followers(
    config: Config,
    usernames: list[str],
    *,
    input_json: Path | None = None,
) -> dict[str, int]:
    if input_json:
        items = result_items(json.loads(input_json.read_text()))
    else:
        if not config.apify_api_key:
            raise RuntimeError("APIFY_API_KEY is required for the TikTok follower backfill.")
        # One video per profile is enough to read authorMeta.fans; keep it cheap.
        items, _, _, _ = run_apify_actor_items(
            api_key=config.apify_api_key,
            actor_id=TIKTOK_ACTOR_ID,
            actor_input={"profiles": usernames, "resultsPerPage": 1, "shouldDownloadVideos": False},
            target_count=len(usernames),
        )
    out: dict[str, int] = {}
    for item in items:
        author = item.get("authorMeta") if isinstance(item.get("authorMeta"), dict) else {}
        username = author.get("name") or item.get("name")
        count = author.get("fans")
        if isinstance(username, str) and isinstance(count, (int, float)):
            out[username] = int(count)
    return out


def recompute_tiktok_virality(
    *,
    config: Config,
    supabase: SupabaseClient | None,
    run_id: str,
    limit: int = 5000,
) -> dict[str, Any]:
    """Re-score a run's TikTok items now that follower counts are known. Trend-API items are
    first scored engagement-only (no followers in the payload), which under-scores mega-viral
    hits whose reach dwarfs their follower base. Once backfill_tiktok_followers fills `followers`,
    this switches them onto the reach-blended score. Re-runnable; only writes rows that change."""
    if supabase is None:
        raise RuntimeError("Supabase credentials are required to recompute virality.")
    rows = supabase.select(
        "organic_items",
        {
            "select": "id,views,likes,comments,shares,followers,virality_score,virality_tier",
            "run_id": f"eq.{run_id}",
            "source": "eq.tiktok",
            "limit": str(limit),
        },
    )
    updated = 0
    for row in rows:
        score, tier = recompute_virality(
            views=row.get("views"),
            likes=row.get("likes"),
            comments=row.get("comments"),
            shares=row.get("shares"),
            followers=row.get("followers"),
        )
        if score == row.get("virality_score") and tier == row.get("virality_tier"):
            continue
        supabase.update_by_id("organic_items", str(row["id"]), {"virality_score": score, "virality_tier": tier})
        updated += 1
    return {"scanned": len(rows), "updated": updated}
