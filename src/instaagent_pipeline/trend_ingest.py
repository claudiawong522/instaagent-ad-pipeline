"""ingest-trends orchestration: web trend pages -> viral_formats + ugc_items.

For each configured source: fetch the page, skip it if unchanged since last run, LLM-parse
it into formats, upsert a viral_formats row per format, then re-scrape each example video
URL to get live metrics + a downloadable video, writing ugc_items linked via format_id.
TikTok links go through the Apify TikTok scraper (by postURLs) and Instagram reel links
through the Apify Instagram scraper (by directUrls). The video MP4s are downloaded and the
analysis filled by the existing organic enrichment (enrich-ugc), chained after.

TikTok short links (vm./vt.tiktok.com, /t/) are redirect-resolved to their canonical
/video/<id> form first. YouTube Shorts are not re-scraped yet. When a format ends up with no
video, the reason is recorded on viral_formats.ingest_note so the dashboard can explain it.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

import requests

from .apify_organic import (
    IG_URL_ACTOR_ID,
    IG_URL_PROVIDER,
    TIKTOK_ACTOR_ID,
    TIKTOK_PROVIDER,
    run_apify_actor_items,
)
from .config import Config
from .ingestion import utc_now_iso
from .normalizers import normalize_instagram_post, normalize_tiktok_item
from .organic_enrichment import enrich_organic_items
from .supabase_client import SupabaseClient
from .trend_sources import fetch_trend_page, parse_trend_formats, resolve_trend_sources

logger = logging.getLogger(__name__)

TREND_PRODUCT_PREFIX = "Trend: "


@dataclass
class TrendSourceResult:
    source_name: str
    status: str  # parsed | unchanged | skipped | incomplete_render | failed
    formats: int = 0
    videos_found: int = 0
    videos_ingested: int = 0
    videos_skipped: int = 0  # YouTube, unresolvable short links, or non-video links — not re-scraped
    videos_already_ingested: int = 0  # in ugc_items from a prior run — not re-scraped (metrics not refreshed)
    formats_removed: int = 0  # stale rows from an earlier page version, pruned after re-link
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


def _existing_video_ids(
    supabase: SupabaseClient, run_id: str, video_ids: list[str]
) -> set[str]:
    """Which of video_ids are already in ugc_items for this run (scraped by a prior pass).
    Changed pages keep their old formats' embeds, so without this every weekly page edit
    would re-pay the Apify scrape for the whole archive."""
    if not video_ids:
        return set()
    rows = supabase.select(
        "ugc_items",
        {
            "select": "external_id",
            "run_id": f"eq.{run_id}",
            "external_id": f"in.({','.join(video_ids)})",
        },
    )
    return {str(row["external_id"]) for row in rows}


def _relink_existing_videos(
    supabase: SupabaseClient,
    run_id: str,
    video_ids: set[str],
    vid_to_format: dict[str, str],
) -> None:
    """Point already-scraped ugc_items at the format the current parse assigns them to,
    without re-scraping. A page that renames/re-splits a trend would otherwise leave the
    video stranded on its old-name row and the new row empty."""
    if not video_ids:
        return
    rows = supabase.select(
        "ugc_items",
        {
            "select": "id,external_id,format_id",
            "run_id": f"eq.{run_id}",
            "external_id": f"in.({','.join(video_ids)})",
        },
    )
    for row in rows:
        target = vid_to_format.get(str(row.get("external_id")))
        if target and str(row.get("format_id")) != target:
            supabase.update_by_id("ugc_items", str(row["id"]), {"format_id": target})


def _prune_stale_formats(
    supabase: SupabaseClient, source_name: str, current_hash: str
) -> int:
    """Delete this source's viral_formats rows left over from an earlier page version
    (content_hash != current). Their videos were just re-linked onto the current rows, so
    what remains are empty renamed/removed trends. content_hash is the stable per-page-version
    identity — format_name is not (the LLM renames trends between fetches)."""
    stale = supabase.select(
        "viral_formats",
        {"select": "id", "source_name": f"eq.{source_name}", "content_hash": f"neq.{current_hash}"},
    )
    for row in stale:
        supabase.delete("viral_formats", {"id": f"eq.{row['id']}"})
    return len(stale)


# ── URL helpers ───────────────────────────────────────────────────────────────────

_TIKTOK_VIDEO_ID_RE = re.compile(r"/video/(\d+)")
_TIKTOK_SHORT_RE = re.compile(r"(?:vm|vt)\.tiktok\.com/|tiktok\.com/t/", re.I)
_IG_SHORTCODE_RE = re.compile(r"instagram\.com/(?:reel|reels|p)/([\w\-]+)", re.I)
_SHORT_LINK_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def _tiktok_video_id(url: str) -> str | None:
    """The aweme id from a canonical /video/<id> URL. Returns None for short links
    (vm.tiktok.com/...) that weren't redirect-resolved."""
    match = _TIKTOK_VIDEO_ID_RE.search(url)
    return match.group(1) if match else None


def _is_tiktok(url: str) -> bool:
    return "tiktok.com" in url.lower()


def _is_instagram(url: str) -> bool:
    return "instagram.com" in url.lower()


def _is_youtube(url: str) -> bool:
    u = url.lower()
    return "youtube.com/shorts" in u or "youtu.be/" in u


def _ig_shortcode(url: str) -> str | None:
    """The shortcode from an instagram.com/reel|p/<code>/ URL — used to map a scraped
    reel back to its format (the IG analogue of the TikTok /video/<id> id)."""
    match = _IG_SHORTCODE_RE.search(url)
    return match.group(1) if match else None


def _video_key(url: str) -> str:
    """A canonical identity for an example video, so the same TikTok/Reel referenced by
    two formats collapses to one key regardless of query strings or trailing slashes."""
    u = url.split("?", 1)[0].rstrip("/").lower()
    vid = _tiktok_video_id(u)
    if vid:
        return f"tt:{vid}"
    code = _ig_shortcode(u)
    if code:
        return f"ig:{code.lower()}"
    return u


def _dedupe_formats(formats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse formats that share an example video into one. The trend blogs — and the LLM
    reading them — sometimes emit the same trend under two or three names ("Sorry I can't" /
    "Hands are full"). Left alone, those become duplicate cards fighting over the single
    ugc_items row per (run, video): the video attaches to one and its siblings render empty.
    Merging up front means one card per trend, with its video. Formats with no example video
    have nothing to key on and are kept as-is."""
    kept: list[dict[str, Any]] = []
    key_to_format: dict[str, dict[str, Any]] = {}
    for fmt in formats:
        keys = {_video_key(u) for u in fmt.get("video_urls", [])}
        match = next((key_to_format[k] for k in keys if k in key_to_format), None)
        if match is None:
            kept.append(fmt)
            for k in keys:
                key_to_format.setdefault(k, fmt)
        else:
            existing = set(match["video_urls"])
            for u in fmt.get("video_urls", []):
                if u not in existing:
                    match["video_urls"].append(u)
                    existing.add(u)
            for k in keys:
                key_to_format.setdefault(k, match)
    return kept


def _resolve_tiktok_short(url: str, cache: dict[str, str]) -> str:
    """vm./vt.tiktok.com and /t/ links 30x-redirect to the canonical /video/<id> URL.
    Follow the redirect so the id can be extracted; fall back to the original on error."""
    if not _TIKTOK_SHORT_RE.search(url):
        return url
    if url in cache:
        return cache[url]
    resolved = url
    try:
        resp = requests.get(
            url, allow_redirects=True, timeout=10, stream=True,
            headers={"User-Agent": _SHORT_LINK_UA},
        )
        resolved = resp.url or url
        resp.close()
    except requests.RequestException as exc:
        logger.warning("TikTok short-link resolve failed for %s: %s", url, exc)
    cache[url] = resolved
    return resolved


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

            formats = _dedupe_formats(parse_trend_formats(config, issue, timeout=min(timeout, 180)))
            sr.formats = len(formats)
            sr.videos_found = sum(len(f["video_urls"]) for f in formats)

            if dry_run:
                sr.status = "parsed"
                result.sources.append(
                    {**sr.__dict__, "preview": [{"format_name": f["format_name"], "video_urls": f["video_urls"]} for f in formats]}
                )
                continue

            # A JS-rendered page whose TikTok embeds didn't finish loading parses to formats
            # with no example videos at all. Persisting that would spawn empty cards and, worse,
            # let _prune_stale_formats delete the good rows from a healthy render. Treat a
            # zero-video JS render as incomplete: skip it without writing (existing data stays
            # intact; the next scheduled run retries). Static sources can legitimately list a
            # format with no example link, so this guard is JS-only.
            if src.get("render") == "js" and formats and sr.videos_found == 0:
                sr.status = "incomplete_render"
                result.sources.append(sr.__dict__)
                continue

            run_id = get_or_create_trend_run(supabase, name)
            touched_run_ids.add(run_id)

            # Upsert one viral_formats row per format; classify each example URL and map it
            # back to its format (TikTok by /video/<id>, Instagram by reel shortcode).
            vid_to_format: dict[str, str] = {}
            tiktok_urls: list[str] = []
            code_to_format: dict[str, str] = {}
            ig_urls: list[str] = []
            fmt_counts: dict[str, dict[str, int]] = {}
            short_cache: dict[str, str] = {}
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
                counts = {"tiktok": 0, "ig": 0, "youtube": 0, "short_unresolved": 0,
                          "other": 0, "links": len(fmt["video_urls"])}
                for video_url in fmt["video_urls"]:
                    resolved = _resolve_tiktok_short(video_url, short_cache) if _is_tiktok(video_url) else video_url
                    if _is_tiktok(resolved):
                        vid = _tiktok_video_id(resolved)
                        if vid:
                            vid_to_format[vid] = format_id
                            # Drop ?referer_url=… noise; the scraper resolves the bare post/share URL.
                            tiktok_urls.append(resolved.split("?", 1)[0])
                            counts["tiktok"] += 1
                        else:
                            counts["short_unresolved"] += 1
                    elif _is_instagram(video_url):
                        code = _ig_shortcode(video_url)
                        if code:
                            code_to_format[code] = format_id
                            ig_urls.append(video_url.split("?", 1)[0])
                            counts["ig"] += 1
                        else:
                            counts["other"] += 1
                    elif _is_youtube(video_url):
                        counts["youtube"] += 1
                    else:
                        counts["other"] += 1
                fmt_counts[format_id] = counts
                sr.videos_skipped += counts["short_unresolved"] + counts["youtube"] + counts["other"]

            already = _existing_video_ids(supabase, run_id, list(vid_to_format))
            if already:
                sr.videos_already_ingested = len(already)
                # Re-link videos we've already scraped to the format THIS parse assigns them
                # to, then skip re-scraping (the expensive part). Without the re-link, a page
                # that renames a trend would orphan its video on the old-name row and leave the
                # new row empty. vid_to_format is the current parse's mapping.
                _relink_existing_videos(supabase, run_id, already, vid_to_format)
                tiktok_urls = [u for u in tiktok_urls if _tiktok_video_id(u) not in already]
                vid_to_format = {v: f for v, f in vid_to_format.items() if v not in already}

            tt_written, _ = _rescrape_and_write(
                config=config,
                supabase=supabase,
                run_id=run_id,
                tiktok_urls=tiktok_urls,
                vid_to_format=vid_to_format,
            )
            ig_written, _ = _rescrape_instagram(
                config=config,
                supabase=supabase,
                run_id=run_id,
                ig_urls=ig_urls,
                code_to_format=code_to_format,
            )
            sr.videos_ingested = tt_written + ig_written
            _annotate_formats(supabase, fmt_counts)
            # The DB should mirror the current page: drop rows left behind by earlier page
            # versions (renamed/removed trends), whose videos have just been re-linked away.
            sr.formats_removed = _prune_stale_formats(supabase, name, issue.content_hash)
            _record_scrape_event(
                supabase, run_id, len(tiktok_urls) + len(ig_urls), sr.videos_ingested
            )
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
) -> tuple[int, set[str]]:
    """Re-scrape the example TikTok URLs for live metrics + a downloadable video, then
    upsert them into ugc_items (source='trend') linked to their format. Returns
    (rows written, format_ids that got at least one video)."""
    if not tiktok_urls:
        return 0, set()
    if not config.apify_api_key:
        raise RuntimeError("APIFY_API_KEY is required to re-scrape trend videos.")
    items, _, _, _ = run_apify_actor_items(
        api_key=config.apify_api_key,
        actor_id=TIKTOK_ACTOR_ID,
        actor_input={"postURLs": tiktok_urls, "shouldDownloadVideos": True, "resultsPerPage": 1},
        target_count=len(tiktok_urls),
    )
    written = 0
    format_ids: set[str] = set()
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
        if format_id:
            format_ids.add(format_id)
    return written, format_ids


def _rescrape_instagram(
    *,
    config: Config,
    supabase: SupabaseClient,
    run_id: str,
    ig_urls: list[str],
    code_to_format: dict[str, str],
) -> tuple[int, set[str]]:
    """Re-scrape Instagram reel URLs via apify/instagram-scraper (by directUrls) and upsert
    them into ugc_items (source='trend') linked to their format by reel shortcode. Rows with
    no downloadable video_url are skipped, so a failed scrape degrades to no rows (never
    corrupt ones). Returns (rows written, format_ids that got at least one video)."""
    if not ig_urls:
        return 0, set()
    if not config.apify_api_key:
        raise RuntimeError("APIFY_API_KEY is required to re-scrape trend videos.")
    items, _, _, _ = run_apify_actor_items(
        api_key=config.apify_api_key,
        actor_id=IG_URL_ACTOR_ID,
        actor_input={"directUrls": ig_urls, "resultsType": "posts", "resultsLimit": len(ig_urls)},
        target_count=len(ig_urls),
    )
    written = 0
    format_ids: set[str] = set()
    for item in items:
        code = str(_first_present_str(item, "shortCode", "shortcode", "code") or "")
        raw = supabase.insert(
            "raw_payloads",
            {
                "run_id": run_id,
                "provider": IG_URL_PROVIDER,
                "endpoint": f"/acts/{IG_URL_ACTOR_ID}/runs",
                "external_id": code,
                "payload_json": item,
            },
        )
        normalized = normalize_instagram_post(item, run_id, raw.get("id"))
        if not normalized.get("video_url"):
            continue
        format_id = code_to_format.get(code)
        normalized["source"] = "trend"
        normalized["format_id"] = format_id
        supabase.upsert("ugc_items", normalized, "run_id,external_id")
        written += 1
        if format_id:
            format_ids.add(format_id)
    return written, format_ids


def _first_present_str(item: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        val = item.get(key)
        if val:
            return str(val)
    return None


# ── no-video reason notes ───────────────────────────────────────────────────────────


def _plural(n: int) -> str:
    return "" if n == 1 else "s"


def _ingest_note(counts: dict[str, int], has_video: bool) -> str | None:
    """A short human explanation of why a format has no playable video, or None if it does."""
    if has_video:
        return None
    if not counts.get("links"):
        return "Source listed no example video links."
    if counts.get("tiktok"):
        return "TikTok scrape returned no downloadable video (post may be deleted, private, or region-locked)."
    if counts.get("ig"):
        return "Instagram reel could not be scraped (post may be deleted, private, or age-gated)."
    parts: list[str] = []
    if counts.get("youtube"):
        parts.append(f"{counts['youtube']} YouTube Shorts link{_plural(counts['youtube'])} not scraped yet")
    if counts.get("short_unresolved"):
        parts.append(f"{counts['short_unresolved']} TikTok short link{_plural(counts['short_unresolved'])} couldn't be resolved")
    if counts.get("other"):
        parts.append(f"{counts['other']} non-video link{_plural(counts['other'])} skipped")
    return ("; ".join(parts) + ".") if parts else "No example video could be scraped."


def _formats_with_videos(supabase: SupabaseClient, format_ids: list[str]) -> set[str]:
    """Which of format_ids currently have at least one ugc_items row."""
    if not format_ids:
        return set()
    rows = supabase.select(
        "ugc_items",
        {"select": "format_id", "format_id": f"in.({','.join(format_ids)})"},
    )
    return {str(row["format_id"]) for row in rows if row.get("format_id")}


def _annotate_formats(supabase: SupabaseClient, fmt_counts: dict[str, dict[str, int]]) -> None:
    """Write viral_formats.ingest_note so the dashboard can explain empty cards. Best-effort;
    clears the note (None) for formats that do have a video."""
    format_ids = list(fmt_counts)
    if not format_ids:
        return
    with_videos = _formats_with_videos(supabase, format_ids)
    for fid in format_ids:
        note = _ingest_note(fmt_counts[fid], fid in with_videos)
        try:
            supabase.update_by_id("viral_formats", fid, {"ingest_note": note})
        except Exception as exc:
            logger.warning("ingest_note update failed for format %s: %s", fid, exc)


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
