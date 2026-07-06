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


def resolve_trend_sources(config: Config) -> list[dict[str, str]]:
    """The configured trend pages, falling back to the built-in defaults."""
    if not config.trend_sources_json:
        return default_trend_sources()
    try:
        parsed = json.loads(config.trend_sources_json)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"TREND_SOURCES is not valid JSON: {exc}") from exc
    sources = [
        {
            "name": str(s["name"]).strip(),
            "url": str(s["url"]).strip(),
            **({"render": str(s["render"]).strip()} if s.get("render") else {}),
        }
        for s in parsed
        if isinstance(s, dict) and s.get("name") and s.get("url")
    ]
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
- format_name: a short, specific name for the format (5 words max).
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

PAGE TEXT:
{page_text}

Candidate video URLs (only assign URLs from this list):
{candidate_urls}
""".strip()

# Cap the page text sent to the LLM. JS-rendered pages (e.g. newengen) inline every example
# embed, so their text runs ~40k chars with formats spread top-to-bottom — a tight cap would
# drop the lower formats' videos. ~60k chars (~15k tokens) fits these pages with headroom.
_MAX_PAGE_CHARS = 60000


def parse_trend_formats(config: Config, issue: TrendIssue, *, timeout: int = 120) -> list[dict[str, Any]]:
    """Extract [{format_name, format_description, video_urls[]}] from one trend page."""
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
    return out
