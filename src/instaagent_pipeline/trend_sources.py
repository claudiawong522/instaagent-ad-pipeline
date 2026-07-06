"""Web trend-page ingestion for the viral-format pipeline.

Fetches each configured trend page (Ramdam, Newengen, ...), strips it to text while
preserving the TikTok/Reel links (these live in href/cite/src attributes, not visible
text, so a naive .get_text() would drop them), then asks the LLM to extract each viral
*format* and its example video URLs. The CLI (ingest-trends) turns those into
viral_formats rows + re-scraped organic_items.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup

from .apify_client import run_apify_actor_items
from .config import Config
from .http_client import HttpClientError
from .openrouter import openrouter_json_call

logger = logging.getLogger(__name__)

_MONTH_SLUGS = (
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
)


def _newengen_insights_url(today: date | None = None) -> str:
    """Newengen's monthly deep-dive at /insights/<month>-tiktok-trends/ — the report with one
    section per trend, each with its own embedded example video (~9-11 trends). The weekly
    /tiktok-trends/ hub only features ~3 and name-drops the rest in FAQ prose (which yielded
    empty cards). The month slug rolls over, so derive it from today's date rather than
    hard-coding a month that silently goes stale. Newengen publishes each month's report before
    the month begins, so the current month is reliably live. (Month names are hard-coded rather
    than strftime('%B') so the slug never depends on the server locale.)"""
    return f"https://newengen.com/insights/{_MONTH_SLUGS[(today or date.today()).month - 1]}-tiktok-trends/"


def issue_date_from_url(url: str, today: date | None = None) -> str | None:
    """The report month of a monthly trend URL (…/<month>-tiktok-trends/…) as an ISO date (the
    1st of that month), used to stamp viral_formats.issue_date so the dashboard can tell June's
    trends from July's. Returns None for weekly/undated sources (no month in the URL). The year
    isn't in the slug; use the current one — safe because the slug tracks the current month."""
    m = re.search(r"/([a-z]+)-tiktok-trends", url, re.I)
    if not m or m.group(1).lower() not in _MONTH_SLUGS:
        return None
    month = _MONTH_SLUGS.index(m.group(1).lower()) + 1
    return date((today or date.today()).year, month, 1).isoformat()


# Public web trend pages, no auth. Override via the TREND_SOURCES env var (JSON list of
# {"name", "url", optional "render"}). render:"js" pages inject their example-video links
# client-side (no <a> in the static HTML), so they must be fetched through a headless browser
# (Apify) instead of plain requests. Built fresh per call so newengen's month slug stays current.
def default_trend_sources() -> list[dict[str, str]]:
    return [
        {"name": "ramdam", "url": "https://www.ramd.am/blog/trends-tiktok"},
        {"name": "newengen", "url": _newengen_insights_url(), "render": "js"},
        {"name": "socialbee", "url": "https://socialbee.com/blog/tiktok-trends/"},
    ]

# Patterns that identify a link as an actual example *video post* (not a tag, sound,
# profile, or hashtag page, which TikTok also links and we must not treat as examples).
VIDEO_URL_PATTERNS = (
    re.compile(r"tiktok\.com/@[\w.\-]+/video/\d+", re.I),  # canonical TikTok post
    re.compile(r"tiktok\.com/share/video/\d+", re.I),      # share-link form (JS-rendered embeds)
    re.compile(r"(?:vm|vt)\.tiktok\.com/[\w]+", re.I),     # TikTok short link
    re.compile(r"tiktok\.com/t/[\w]+", re.I),              # TikTok short link (alt)
    re.compile(r"instagram\.com/(?:reel|reels|p)/[\w\-]+", re.I),
    re.compile(r"youtube\.com/shorts/[\w\-]+", re.I),
    re.compile(r"youtu\.be/[\w\-]+", re.I),
)

_FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


@dataclass
class TrendIssue:
    source_name: str
    source_url: str
    content_hash: str
    text: str
    candidate_urls: list[str] = field(default_factory=list)


def resolve_trend_sources(config: Config) -> list[dict[str, Any]]:
    """The configured trend pages, falling back to the built-in defaults."""
    if not config.trend_sources_json:
        return default_trend_sources()
    try:
        parsed = json.loads(config.trend_sources_json)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"TREND_SOURCES is not valid JSON: {exc}") from exc
    sources: list[dict[str, Any]] = []
    for s in parsed:
        if not (isinstance(s, dict) and s.get("name") and s.get("url")):
            continue
        entry: dict[str, Any] = {"name": str(s["name"]).strip(), "url": str(s["url"]).strip()}
        if s.get("render"):
            entry["render"] = str(s["render"]).strip()
        # Structured-JSON source knobs (kind="sge_formats"); carried through untouched.
        if s.get("kind"):
            entry["kind"] = str(s["kind"]).strip()
        if s.get("limit") is not None:
            entry["limit"] = int(s["limit"])
        if s.get("since"):
            entry["since"] = str(s["since"]).strip()
        if s.get("categories"):
            entry["categories"] = [str(c).strip() for c in s["categories"]]
        sources.append(entry)
    if not sources:
        raise RuntimeError("TREND_SOURCES parsed to an empty source list.")
    return sources


def _is_video_url(url: str) -> bool:
    return any(pat.search(url) for pat in VIDEO_URL_PATTERNS)


def _is_carousel_recommendation(url: str) -> bool:
    """True when a TikTok share/video link is an embed's auto-injected "you might also like"
    recommendation rather than the article's chosen example. A TikTok embed injects a carousel
    of unrelated videos next to the real one; each carousel link is a share/video/<other-id>
    URL stamped with referer_video_id=<the actually-embedded video>. When the link's own path
    id differs from that referer, it belongs to the recommendation strip — harvesting it dumps
    random high-view videos onto the wrong format (see newengen's "Wow, Ok")."""
    m = re.search(r"tiktok\.com/share/video/(\d+)", url, re.I)
    if not m:
        return False
    ref = parse_qs(urlparse(url).query).get("referer_video_id", [None])[0]
    return bool(ref) and ref != m.group(1)


def html_to_text(html: str) -> tuple[str, list[str]]:
    """Strip a page to readable text and harvest candidate video URLs.

    Links are inlined as `anchor text (url)` and TikTok/IG embeds (blockquote cite /
    iframe src) are collected separately, so the LLM can associate each format with its
    example videos even though those URLs never appear in the visible text.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    candidates: list[str] = []

    def _add(url: str | None) -> None:
        if url and _is_video_url(url) and not _is_carousel_recommendation(url) and url not in candidates:
            candidates.append(url)

    # Inline anchor hrefs next to their text so the model sees which link belongs where.
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if _is_video_url(href):
            _add(href)
            label = a.get_text(strip=True)
            a.replace_with(f"{label} ({href})" if label else href)
    # Embeds carry the canonical URL in cite/src, not in text.
    for bq in soup.find_all("blockquote"):
        _add((bq.get("cite") or "").strip() or None)
    for frame in soup.find_all("iframe", src=True):
        _add(frame["src"].strip())

    text = re.sub(r"\n{3,}", "\n\n", soup.get_text("\n")).strip()
    return text, candidates


# Apify headless-browser actor used to render JS-only trend pages (render:"js"). These pages
# inject their TikTok example links client-side, so we need the post-JS DOM. We use the
# website-content-crawler (no full-permission approval required) with htmlTransformer:"none"
# so it returns the raw rendered HTML — readability cleaning would strip the embeds we harvest.
_RENDER_ACTOR_ID = "apify~website-content-crawler"


def _fetch_static_html(url: str, timeout: int) -> str:
    try:
        resp = requests.get(url, headers=_FETCH_HEADERS, timeout=timeout)
    except requests.RequestException as exc:
        raise HttpClientError(f"Network error fetching trend page {url}: {exc}") from exc
    if resp.status_code >= 400:
        raise HttpClientError(f"HTTP {resp.status_code} fetching trend page {url}", status=resp.status_code)
    return resp.text


def _fetch_rendered_html(url: str, apify_api_key: str | None) -> str:
    """Render a JS-only page in Apify's headless browser and return its raw rendered HTML."""
    if not apify_api_key:
        raise RuntimeError(f"APIFY_API_KEY is required to render JS trend page {url}.")
    items, _, _, _ = run_apify_actor_items(
        api_key=apify_api_key,
        actor_id=_RENDER_ACTOR_ID,
        actor_input={
            "startUrls": [{"url": url}],
            "crawlerType": "playwright:firefox",
            "maxCrawlPages": 1,
            "maxCrawlDepth": 0,
            "saveHtml": True,
            "htmlTransformer": "none",
            # The monthly report lazy-loads a TikTok embed per trend as it scrolls into view;
            # each embed's script then injects the canonical link we harvest. Too little scroll
            # or wait and the lower trends never render (a partial render silently drops them).
            # Scroll the full page and give the embeds time to initialize before capturing HTML.
            "waitForSelectorOnLoadTimeoutSecs": 30,
            "maxScrollHeightPixels": 120000,
            "dynamicContentWaitSecs": 20,
        },
        target_count=1,
    )
    html = next((str(it.get("html")) for it in items if it.get("html")), None)
    if not html:
        raise HttpClientError(f"Headless render of trend page {url} returned no HTML.")
    return html


def fetch_trend_page(
    source_name: str,
    url: str,
    *,
    render: str | None = None,
    apify_api_key: str | None = None,
    timeout: int = 30,
) -> TrendIssue:
    html = (
        _fetch_rendered_html(url, apify_api_key)
        if render == "js"
        else _fetch_static_html(url, timeout)
    )
    text, candidates = html_to_text(html)
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return TrendIssue(
        source_name=source_name,
        source_url=url,
        content_hash=content_hash,
        text=text,
        candidate_urls=candidates,
    )


# ── Social Growth Engineers: structured JSON API (no HTML/LLM) ─────────────────────

# Social Growth Engineers publishes its viral-format library as structured JSON at /api/formats/
# (public, no auth), so we skip the HTML→LLM path entirely and map the API's fields straight to the
# pipeline's format shape. Each format's `latest_video` is its single public example (the fuller
# per-format video sets sit behind their Pro gate). Optional filters cap volume / Apify re-scrape
# cost. A source opts into this path with {"kind": "sge_formats"} in its config.
SGE_FORMATS_URL = "https://www.socialgrowthengineers.com/api/formats/"


def fetch_sge_formats(
    source_name: str,
    url: str,
    *,
    limit: int | None = None,
    since: str | None = None,
    categories: list[str] | None = None,
    timeout: int = 30,
) -> tuple[TrendIssue, list[dict[str, Any]]]:
    """Fetch SGE's viral-format library and return (issue, formats) ready for ingest_trends —
    the same {format_name, format_description, video_urls} shape parse_trend_formats produces.

    Filters (all optional): `limit` keeps the N most recent formats; `since` (ISO YYYY-MM-DD)
    keeps only formats created on/after that date; `categories` keeps only formats tagged with one
    of the given niche names (case-insensitive)."""
    try:
        resp = requests.get(url, headers=_FETCH_HEADERS, timeout=timeout)
    except requests.RequestException as exc:
        raise HttpClientError(f"Network error fetching SGE formats {url}: {exc}") from exc
    if resp.status_code >= 400:
        raise HttpClientError(f"HTTP {resp.status_code} fetching SGE formats {url}", status=resp.status_code)
    raw = resp.json().get("formats", [])
    raw.sort(key=lambda f: f.get("created_at") or "", reverse=True)  # newest first, so `limit` keeps recent
    wanted = {c.lower() for c in categories} if categories else None

    formats: list[dict[str, Any]] = []
    for f in raw:
        if since and (f.get("created_at") or "")[:10] < since:
            continue
        if wanted and not any((c.get("name") or "").lower() in wanted for c in f.get("categories") or []):
            continue
        link = (f.get("latest_video") or {}).get("video_link")
        name = (f.get("title") or "").strip()
        if not link or not name:
            continue
        formats.append({
            "format_name": name,
            "format_description": (f.get("description") or "").strip(),
            "video_urls": [link],
        })
        if limit and len(formats) >= limit:
            break

    # Hash the (name, video) identity of what we selected so an unchanged library is skipped like
    # any other source; adding/removing a format or swapping its example flips the hash.
    digest = json.dumps([(f["format_name"], f["video_urls"][0]) for f in formats], sort_keys=True)
    issue = TrendIssue(
        source_name=source_name,
        source_url=url,
        content_hash=hashlib.sha256(digest.encode("utf-8")).hexdigest(),
        text=digest,
        candidate_urls=[f["video_urls"][0] for f in formats],
    )
    return issue, formats


# ── LLM parse: page text → viral formats ──────────────────────────────────────────

TREND_PARSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "formats": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "format_name": {"type": "string"},
                    "format_description": {"type": "string"},
                    "video_urls": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["format_name", "format_description", "video_urls"],
            },
        }
    },
    "required": ["formats"],
}

TREND_PARSE_PROMPT = """
You read a web article that rounds up trending TikTok/Reel video FORMATS (a format is a
repeatable content idea, e.g. "old-photo before/after reveal" or "aura points scoreboard").

From the page text below, extract every distinct viral format the article describes.
For each format return:
- format_name: the trend's own heading/title from the page, verbatim and trimmed, when it has
  one — e.g. a "Trend #7: Toy Story 5 "There Was a Time"" heading → use the exact title
  "Toy Story 5 "There Was a Time"". Do NOT shorten, paraphrase, or drop a parenthetical (e.g.
  keep "You Look Like the 4th of July (Makes Me Want a Hot Dog Real Bad)" in full). Only invent a
  short name (≤6 words) when the section genuinely has no title of its own.
- format_description: 1-3 sentences describing the format/structure — the hook, the
  beats, what makes it work. Use the article's explanation; do not invent.
- video_urls: the example TikTok/Instagram/YouTube-Short video URLs the article ties to
  THIS format. Only use URLs from the "Candidate video URLs" list — never invent or guess
  a URL. If the article shows no example link for a format, return an empty array.

Ignore navigation, ads, author bios, newsletter signups, and generic advice that is not a
specific format. Only extract a format from a section that actually describes it (a heading
plus its own explanation) — do NOT extract trend names that are merely listed or mentioned in
passing, e.g. inside an FAQ answer, a "related trends" sentence, or a roundup list ("strong
options include X, Y, Z"). Those name-drops have no example video and are not real entries.
Return only real formats.

Many roundups NUMBER their trends ("Trend #1", "Trend #2", … or "1.", "2."). When the page does,
extract EXACTLY ONE format per number: never merge two numbered trends into a single format, and
never skip a number that has its own titled section (even if its example video failed to load —
return it with an empty video_urls array). Each numbered trend's example video is the embed inside
THAT trend's own section; do not borrow a neighboring trend's video.

PAGE TEXT:
{page_text}

Candidate video URLs (only assign URLs from this list):
{candidate_urls}
""".strip()

# Cap the page text sent to the LLM. JS-rendered pages (e.g. newengen) inline every example
# embed, so their text runs ~40k chars with formats spread top-to-bottom — a tight cap would
# drop the lower formats' videos. ~60k chars (~15k tokens) fits these pages with headroom.
_MAX_PAGE_CHARS = 60000

_TREND_NUMBER_RE = re.compile(r"Trend\s*#?\s*(\d+)", re.I)
_TREND_HEADING_RE = re.compile(r"Trend\s*#?\s*(\d+)\s*:?[ \t]*([^\n]*)", re.I)
# Where a trend section's explanation ends and its embed/CTA boilerplate begins.
_SECTION_STOP_RE = re.compile(r"\b(How to do it|Related videos|Watch (?:more|now))\b", re.I)


def max_trend_number(text: str) -> int:
    """The highest 'Trend #N' the page numbers itself with (0 if unnumbered). Numbered roundups
    (e.g. newengen) label every trend, so this is the authoritative trend count — used to flag a
    parse/render that came back with fewer formats than the page actually lists."""
    return max((int(m.group(1)) for m in _TREND_NUMBER_RE.finditer(text)), default=0)


def _video_id_for_match(url: str) -> str | None:
    """The bare id that a candidate video URL prints inside the page text — a TikTok aweme id or an
    Instagram shortcode — so a candidate can be located in the section it belongs to."""
    m = _TIKTOK_ID_RE.search(url) or _REFERER_ID_RE.search(url)
    if m:
        return m.group(1)
    m = _IG_SHORTCODE_RE.search(url)
    return m.group(1) if m else None


_TIKTOK_ID_RE = re.compile(r"/video/(\d+)")
_REFERER_ID_RE = re.compile(r"referer_video_id=(\d+)")
_IG_SHORTCODE_RE = re.compile(r"instagram\.com/(?:reel|reels|p)/([\w-]+)", re.I)


def segment_numbered_page(issue: "TrendIssue") -> list[dict[str, Any]] | None:
    """Deterministic parse for a page that numbers its trends (`Trend #1 … #N`): one format per
    numbered heading — the heading's title as the name, the section's opening text as the
    description, and every candidate video whose id first appears inside that heading's text span.
    Returns None when the page isn't numbered (fewer than 2 headings) so unnumbered sources
    (socialbee, ramdam) fall back to the LLM parse.

    This replaces the LLM guesswork that merged adjacent numbered trends into one card and truncated
    their titles (e.g. "You Look Like the 4th of July (…)" → "You Look Like 4th July"). A numbered
    trend whose example video was removed or never rendered still returns here with an empty
    video_urls (the zero-link filter in ingest then drops it, as for any video-less format)."""
    text = issue.text
    marks: list[tuple[int, int, int, str]] = []  # (start, end, number, title)
    seen: set[int] = set()
    for m in _TREND_HEADING_RE.finditer(text):
        n = int(m.group(1))
        if n in seen:  # embeds can echo the "Trend #N" label further down; keep the first
            continue
        seen.add(n)
        marks.append((m.start(), m.end(), n, m.group(2).strip()))
    if len(marks) < 2:
        return None

    # Earliest position (and a canonical URL) for each candidate video id; its section is wherever
    # it first appears in the rendered text.
    id_pos: dict[str, int] = {}
    id_url: dict[str, str] = {}
    for u in issue.candidate_urls:
        vid = _video_id_for_match(u)
        if not vid:
            continue
        p = text.find(vid)
        if p == -1:
            continue
        if vid not in id_pos or p < id_pos[vid]:
            id_pos[vid] = p
        if vid not in id_url or ("/@" in u and "/@" not in id_url[vid]):
            id_url[vid] = u  # prefer the canonical @user/video/<id> form for storage

    out: list[dict[str, Any]] = []
    for i, (_hs, he, n, title) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        body = text[he:end]
        stop = _SECTION_STOP_RE.search(body)
        desc = re.sub(r"\s+", " ", body[: stop.start()] if stop else body[:500]).strip() or None
        urls = [id_url[vid] for vid, p in id_pos.items() if he <= p < end]
        out.append({"format_name": title or f"Trend {n}", "format_description": desc, "video_urls": urls})
    return out


def parse_trend_formats(config: Config, issue: TrendIssue, *, timeout: int = 120) -> list[dict[str, Any]]:
    """Extract [{format_name, format_description, video_urls[]}] from one trend page.

    Pages that number their trends (`Trend #1 … #N`, e.g. newengen) are segmented deterministically
    — no LLM — so adjacent trends never merge and titles stay verbatim. Unnumbered pages fall back
    to the LLM parse below."""
    segmented = segment_numbered_page(issue)
    if segmented is not None:
        return segmented

    if not config.openrouter_api_key:
        raise RuntimeError("OPENROUTER_API_KEY is required to parse trend pages.")
    prompt = TREND_PARSE_PROMPT.format(
        page_text=issue.text[:_MAX_PAGE_CHARS],
        candidate_urls="\n".join(issue.candidate_urls) or "(none found)",
    )
    analysis = openrouter_json_call(
        config,
        prompt=prompt,
        schema=TREND_PARSE_SCHEMA,
        schema_name="trend_formats",
        timeout=timeout,
        empty_error="OpenRouter returned no trend-format analysis.",
    )
    formats = analysis.get("formats")
    if not isinstance(formats, list):
        return []
    out: list[dict[str, Any]] = []
    for fmt in formats:
        if not isinstance(fmt, dict):
            continue
        name = str(fmt.get("format_name") or "").strip()
        if not name:
            continue
        urls = [
            str(u).strip()
            for u in (fmt.get("video_urls") or [])
            if isinstance(u, str) and _is_video_url(str(u))
        ]
        out.append(
            {
                "format_name": name,
                "format_description": str(fmt.get("format_description") or "").strip() or None,
                "video_urls": urls,
            }
        )
    # Numbered roundups list N trends explicitly; fewer formats than that means a numbered trend
    # was merged into another or its section didn't render — surface it (a re-run accumulates the
    # rest; see the trend-scraping skill §8).
    expected = max_trend_number(issue.text)
    if expected and len(out) < expected:
        logger.warning(
            "%s: page numbers %d trends but parse extracted %d — %d missing (merged/unrendered); "
            "re-run ingest to accumulate the rest",
            issue.source_name, expected, len(out), expected - len(out),
        )
    return out
