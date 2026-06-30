"""ingest-trends orchestration: web trend pages -> viral_formats + ugc_items.

For each configured source: fetch the page, skip it if unchanged since last run, LLM-parse
it into formats, upsert a viral_formats row per format, then re-scrape each example video
URL through the existing Apify TikTok scraper (by postURLs) to get live metrics + a
downloadable video, writing ugc_items linked via format_id. The video MP4s are downloaded
and the analysis filled by the existing organic enrichment (enrich-ugc), chained after.

Instagram/YouTube example links are noted but not re-scraped yet (no URL-based actor wired
— see future-add-ons.md); TikTok is the dominant source on these pages.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from .apify_organic import TIKTOK_ACTOR_ID, TIKTOK_PROVIDER, run_apify_actor_items
from .config import Config
from .ingestion import utc_now_iso
from .normalizers import normalize_tiktok_item
from .organic_enrichment import enrich_organic_items
from .supabase_client import SupabaseClient
from .trend_sources import fetch_trend_page, parse_trend_formats, resolve_trend_sources

logger = logging.getLogger(__name__)

TREND_PRODUCT_PREFIX = "Trend: "


@dataclass
class TrendSourceResult:
    source_name: str
    status: str  # parsed | unchanged | skipped | failed
    formats: int = 0
    videos_found: int = 0
    videos_ingested: int = 0
    videos_skipped: int = 0  # non-TikTok (IG/YT) or unmappable short links — not re-scraped yet
    error: str | None = None


@dataclass
class TrendIngestResult:
    sources: list[dict[str, Any]] = field(default_factory=list)
    enrichment: Any = None


# ── run/product bootstrap ─────────────────────────────────────────────────────────


def get_or_create_trend_run(supabase: SupabaseClient, source_name: str) -> str:
    """One persistent product + pipeline_run per trend source, so the dashboard aggregates
    every re-fetch under one run. Keyed on a product named 'Trend: <source>'."""
    product_name = f"{TREND_PRODUCT_PREFIX}{source_name}"
    products = supabase.select(
        "products", {"select": "id", "name": f"eq.{product_name}", "limit": "1"}
    )
    product_id = products[0]["id"] if products else supabase.insert(
        "products", {"name": product_name, "category": "trend-source"}
    )["id"]

    runs = supabase.select(
        "pipeline_runs", {"select": "id", "product_id": f"eq.{product_id}", "limit": "1"}
    )
    if runs:
        return str(runs[0]["id"])
    run = supabase.insert(
        "pipeline_runs",
        {"product_id": product_id, "status": "created", "config": {"trend_source": source_name}},
    )
    return str(run["id"])


def _latest_content_hash(supabase: SupabaseClient, source_name: str) -> str | None:
    rows = supabase.select(
        "viral_formats",
        {
            "select": "content_hash",
            "source_name": f"eq.{source_name}",
            "content_hash": "not.is.null",
            "order": "created_at.desc",
            "limit": "1",
        },
    )
    return str(rows[0]["content_hash"]) if rows else None


# ── TikTok URL helpers ────────────────────────────────────────────────────────────

_TIKTOK_VIDEO_ID_RE = re.compile(r"/video/(\d+)")


def _tiktok_video_id(url: str) -> str | None:
    """The aweme id from a canonical /video/<id> URL. Returns None for short links
    (vm.tiktok.com/...) — those can't be mapped to a format pre-scrape, so we skip them."""
    match = _TIKTOK_VIDEO_ID_RE.search(url)
    return match.group(1) if match else None


def _is_tiktok(url: str) -> bool:
    return "tiktok.com" in url.lower()


# ── main entry ────────────────────────────────────────────────────────────────────


def ingest_trends(
    *,
    config: Config,
    supabase: SupabaseClient | None,
    only_source: str | None = None,
    timeout: int = 300,
    concurrency: int = 32,
    skip_enrichment: bool = False,
    force: bool = False,
    dry_run: bool = False,
) -> TrendIngestResult:
    sources = resolve_trend_sources(config)
    if only_source:
        sources = [s for s in sources if s["name"] == only_source]
        if not sources:
            raise RuntimeError(f"No configured trend source named {only_source!r}.")
    if not dry_run and supabase is None:
        raise RuntimeError("Supabase credentials are required unless --dry-run is used.")

    result = TrendIngestResult()
    touched_run_ids: set[str] = set()

    for src in sources:
        name, url = src["name"], src["url"]
        sr = TrendSourceResult(source_name=name, status="parsed")
        try:
            issue = fetch_trend_page(
                name, url, render=src.get("render"), apify_api_key=config.apify_api_key
            )
            if not dry_run and not force:
                if _latest_content_hash(supabase, name) == issue.content_hash:
                    sr.status = "unchanged"
                    result.sources.append(sr.__dict__)
                    continue

            formats = parse_trend_formats(config, issue, timeout=min(timeout, 180))
            sr.formats = len(formats)
            sr.videos_found = sum(len(f["video_urls"]) for f in formats)

            if dry_run:
                sr.status = "parsed"
                result.sources.append(
                    {**sr.__dict__, "preview": [{"format_name": f["format_name"], "video_urls": f["video_urls"]} for f in formats]}
                )
                continue

            run_id = get_or_create_trend_run(supabase, name)
            touched_run_ids.add(run_id)

            # Upsert one viral_formats row per format; map each example video id -> format_id.
            vid_to_format: dict[str, str] = {}
            tiktok_urls: list[str] = []
            for fmt in formats:
                row = supabase.upsert(
                    "viral_formats",
                    {
                        "run_id": run_id,
                        "source_name": name,
                        "source_url": url,
                        "content_hash": issue.content_hash,
                        "format_name": fmt["format_name"],
                        "format_description": fmt["format_description"],
                    },
                    "source_name,format_name",
                )
                format_id = str(row.get("id") or "")
                for video_url in fmt["video_urls"]:
                    vid = _tiktok_video_id(video_url) if _is_tiktok(video_url) else None
                    if vid:
                        vid_to_format[vid] = format_id
                        tiktok_urls.append(video_url)
                    else:
                        sr.videos_skipped += 1

            sr.videos_ingested = _rescrape_and_write(
                config=config,
                supabase=supabase,
                run_id=run_id,
                tiktok_urls=tiktok_urls,
                vid_to_format=vid_to_format,
            )
            _record_scrape_event(supabase, run_id, len(tiktok_urls), sr.videos_ingested)
        except Exception as exc:  # one bad source shouldn't sink the rest
            sr.status = "failed"
            sr.error = str(exc)[:300]
            logger.warning("Trend source %s failed: %s", name, exc)
            result.sources.append(sr.__dict__)
            continue
        result.sources.append(sr.__dict__)

    # Download MP4s + run vision enrichment for everything just ingested.
    if not dry_run and not skip_enrichment and touched_run_ids:
        enrichments = []
        for run_id in touched_run_ids:
            enrichments.append(
                {
                    "run_id": run_id,
                    "result": enrich_organic_items(
                        config=config,
                        supabase=supabase,
                        run_id=run_id,
                        limit=500,
                        dry_run=False,
                        timeout=timeout,
                        concurrency=concurrency,
                    ).__dict__,
                }
            )
        result.enrichment = enrichments

    return result


def _rescrape_and_write(
    *,
    config: Config,
    supabase: SupabaseClient,
    run_id: str,
    tiktok_urls: list[str],
    vid_to_format: dict[str, str],
) -> int:
    """Re-scrape the example TikTok URLs for live metrics + a downloadable video, then
    upsert them into ugc_items (source='trend') linked to their format."""
    if not tiktok_urls:
        return 0
    if not config.apify_api_key:
        raise RuntimeError("APIFY_API_KEY is required to re-scrape trend videos.")
    items, _, _, _ = run_apify_actor_items(
        api_key=config.apify_api_key,
        actor_id=TIKTOK_ACTOR_ID,
        actor_input={"postURLs": tiktok_urls, "shouldDownloadVideos": True, "resultsPerPage": 1},
        target_count=len(tiktok_urls),
    )
    written = 0
    for item in items:
        raw = supabase.insert(
            "raw_payloads",
            {
                "run_id": run_id,
                "provider": TIKTOK_PROVIDER,
                "endpoint": f"/acts/{TIKTOK_ACTOR_ID}/runs",
                "external_id": str(item.get("id") or ""),
                "payload_json": item,
            },
        )
        normalized = normalize_tiktok_item(item, run_id, raw.get("id"))
        if not normalized.get("video_url"):
            continue
        format_id = vid_to_format.get(str(item.get("id") or ""))
        normalized["source"] = "trend"
        normalized["format_id"] = format_id
        supabase.upsert("ugc_items", normalized, "run_id,external_id")
        written += 1
    return written


def _record_scrape_event(
    supabase: SupabaseClient, run_id: str, target: int, ingested: int
) -> None:
    """Best-effort cost/visibility row, mirroring the campaign scrapes."""
    try:
        supabase.insert(
            "scrape_events",
            {
                "run_id": run_id,
                "platform": "trend",
                "target_count": target,
                "items_ingested": ingested,
                "status": "done",
                "finished_at": utc_now_iso(),
            },
        )
    except Exception as exc:
        logger.warning("scrape_events insert failed for run %s: %s", run_id, exc)
