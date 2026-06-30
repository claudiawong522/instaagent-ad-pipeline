"""Organic ingestion via Apify keyword scrapers, replacing TopYappers.

TikTok  -> clockworks/tiktok-scraper        (keyword search; followers native)
Instagram -> data-slayer/instagram-search-reels (keyword search; followers backfilled)

Both write to ugc_items. Rows without a usable downloadable video are dropped. The
analysis columns are filled later by the organic vision enrichment.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .apify_ads import APIFY_API_BASE_URL, APIFY_RUN_WAIT_SECONDS, apify_data, wait_for_apify_run
from .config import Config
from .http_client import HttpClientError, request_json
from .ingestion import IngestResult, log_api_usage, log_failed_query, start_query, write_items
from .normalizers import (
    normalize_instagram_reel,
    normalize_tiktok_item,
    normalize_tiktok_trend_item,
    recompute_virality,
    result_items,
    tiktok_download_url,
    tiktok_trend_video_url,
    tiktok_trend_views,
)
from .supabase_client import SupabaseClient

TIKTOK_ACTOR_ID = "clockworks~tiktok-scraper"
TIKTOK_PROVIDER = "apify:clockworks/tiktok-scraper"
TIKTOK_TREND_ACTOR_ID = "novi~tiktok-trend-api"
TIKTOK_TREND_PROVIDER = "apify:novi/tiktok-trend-api"
INSTAGRAM_ACTOR_ID = "data-slayer~instagram-search-reels"
INSTAGRAM_PROVIDER = "apify:data-slayer/instagram-search-reels"
IG_PROFILE_ACTOR_ID = "apify~instagram-profile-scraper"
IG_PROFILE_PROVIDER = "apify:apify/instagram-profile-scraper"
INSTAGRAM_PAGE_SIZE = 50  # data-slayer returns ~50-100 reels per page


def run_apify_actor_items(
    *,
    api_key: str,
    actor_id: str,
    actor_input: dict[str, Any],
    target_count: int,
) -> tuple[list[dict[str, Any]], int, dict[str, str], dict[str, Any]]:
    endpoint = f"/acts/{actor_id}/runs"
    run_response = request_json(
        "POST",
        f"{APIFY_API_BASE_URL}{endpoint}",
        params={"token": api_key, "waitForFinish": APIFY_RUN_WAIT_SECONDS},
        body=actor_input,
        timeout=APIFY_RUN_WAIT_SECONDS + 30,
    )
    run = wait_for_apify_run(api_key, apify_data(run_response.body))
    dataset_id = run.get("defaultDatasetId")
    if not dataset_id:
        raise RuntimeError(f"Apify run {run.get('id')} did not return a defaultDatasetId.")
    dataset_response = request_json(
        "GET",
        f"{APIFY_API_BASE_URL}/datasets/{dataset_id}/items",
        params={"token": api_key, "format": "json", "clean": "1", "limit": target_count},
        timeout=180,
    )
    metadata = {
        "actor_run_id": run.get("id"),
        "actor_run_status": run.get("status"),
        "actor_default_dataset_id": dataset_id,
        "actor_usage_total_usd": run.get("usageTotalUsd"),
    }
    return result_items(dataset_response.body), dataset_response.status, dataset_response.headers, metadata


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
    has_video: Any,
    dry_run: bool,
    input_json: Path | None,
) -> IngestResult:
    endpoint = f"/acts/{actor_id}/runs"
    request_params = {"actor": actor_id, "keyword": keyword, "actor_input": actor_input}
    source_query_id = start_query(
        supabase=supabase,
        dry_run=dry_run,
        run_id=run_id,
        provider=provider,
        endpoint=endpoint,
        method="POST",
        request_params=request_params,
    )
    response_headers: dict[str, str] = {}
    response_status: int | None = None
    run_metadata: dict[str, Any] = {}
    try:
        if input_json:
            items = result_items(json.loads(input_json.read_text()))
        else:
            if not config.apify_api_key:
                raise RuntimeError("APIFY_API_KEY is required unless --input-json is used.")
            items, response_status, response_headers, run_metadata = run_apify_actor_items(
                api_key=config.apify_api_key,
                actor_id=actor_id,
                actor_input=actor_input,
                target_count=target_count,
            )
        # Drop rows without a downloadable video (the no-video rule).
        items = [item for item in items if has_video(item)][:target_count]
        log_api_usage(
            supabase=supabase,
            dry_run=dry_run,
            run_id=run_id,
            provider=provider,
            endpoint=endpoint,
            status=response_status,
            response_count=len(items),
            headers=response_headers,
            metadata={"actor": actor_id, **run_metadata},
        )
        return write_items(
            supabase=supabase,
            dry_run=dry_run,
            run_id=run_id,
            provider=provider,
            endpoint=endpoint,
            method="POST",
            request_params=request_params,
            source_query_id=source_query_id,
            destination_table="ugc_items",
            items=items,
            normalizer=normalizer,
            conflict_columns="run_id,external_id",
            response_status=response_status,
        )
    except (HttpClientError, RuntimeError) as exc:
        if isinstance(exc, HttpClientError) and response_status is None and not input_json:
            log_api_usage(
                supabase=supabase,
                dry_run=dry_run,
                run_id=run_id,
                provider=provider,
                endpoint=endpoint,
                status=exc.status,
                response_count=None,
                headers={},
                metadata={"actor": actor_id},
            )
        log_failed_query(
            supabase=supabase,
            dry_run=dry_run,
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
    feed (no search term). Writes to ugc_items like the other organic sources; follower
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
    if supabase is None:
        raise RuntimeError("Supabase credentials are required for the IG follower backfill.")
    rows = supabase.select(
        "ugc_items",
        {
            "select": "id,user_handle",
            "run_id": f"eq.{run_id}",
            "source": "eq.instagram",
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

    followers_map = fetch_instagram_followers(config, usernames, input_json=input_json)
    updated = 0
    for username, count in followers_map.items():
        if count is None:
            continue
        for row_id in by_user.get(username, []):
            supabase.update_by_id("ugc_items", row_id, {"followers": count})
            updated += 1
    return {"usernames": len(usernames), "resolved": len(followers_map), "updated": updated}


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
    if supabase is None:
        raise RuntimeError("Supabase credentials are required for the TikTok follower backfill.")
    rows = supabase.select(
        "ugc_items",
        {
            "select": "id,user_handle",
            "run_id": f"eq.{run_id}",
            "source": "eq.tiktok",
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

    followers_map = fetch_tiktok_followers(config, usernames, input_json=input_json)
    updated = 0
    for username, count in followers_map.items():
        if count is None:
            continue
        for row_id in by_user.get(username, []):
            supabase.update_by_id("ugc_items", row_id, {"followers": count})
            updated += 1
    return {"usernames": len(usernames), "resolved": len(followers_map), "updated": updated}


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
        "ugc_items",
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
        supabase.update_by_id("ugc_items", str(row["id"]), {"virality_score": score, "virality_tier": tier})
        updated += 1
    return {"scanned": len(rows), "updated": updated}
