"""Web trend-page ingestion for the viral-format pipeline.

Fetches each configured trend page (Ramdam, Newengen, ...), strips it to text while
preserving the TikTok/Reel links (these live in href/cite/src attributes, not visible
text, so a naive .get_text() would drop them), then asks the LLM to extract each viral
*format* and its example video URLs. The CLI (ingest-trends) turns those into
viral_formats rows + re-scraped ugc_items.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

import requests
from bs4 import BeautifulSoup

from .ad_enrichment import (
    OPENROUTER_BASE_URL,
    OPENROUTER_CHAT_COMPLETIONS_ENDPOINT,
    parse_enrichment_response,
)
from .config import Config
from .http_client import HttpClientError, request_json

# Public web trend pages, no auth. Override via the TREND_SOURCES env var (JSON list of
# {"name", "url", optional "render"}). These are weekly-updated TikTok/Reel trend roundups.
# render:"js" pages inject their example-video links client-side (no <a> in the static HTML),
# so they must be fetched through a headless browser (Apify) instead of plain requests.
DEFAULT_TREND_SOURCES: list[dict[str, str]] = [
    {"name": "ramdam", "url": "https://www.ramd.am/blog/trends-tiktok"},
    {"name": "newengen", "url": "https://newengen.com/tiktok-trends/", "render": "js"},
    {"name": "later", "url": "https://later.com/blog/tiktok-trends/"},
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
        return DEFAULT_TREND_SOURCES
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
        if url and _is_video_url(url) and url not in candidates:
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
    # Imported here (not at module top) to avoid a heavier import chain for static sources.
    from .apify_organic import run_apify_actor_items

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
            "waitForSelectorOnLoadTimeoutSecs": 15,
            "maxScrollHeightPixels": 50000,
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
specific format. Return only real formats.

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
    response = request_json(
        "POST",
        f"{OPENROUTER_BASE_URL}{OPENROUTER_CHAT_COMPLETIONS_ENDPOINT}",
        headers={"Authorization": f"Bearer {config.openrouter_api_key}"},
        body={
            "model": config.openrouter_model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "trend_formats", "strict": True, "schema": TREND_PARSE_SCHEMA},
            },
        },
        timeout=timeout,
    )
    analysis = parse_enrichment_response(response.body)
    if not isinstance(analysis, dict):
        raise RuntimeError("OpenRouter returned no trend-format analysis.")
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
