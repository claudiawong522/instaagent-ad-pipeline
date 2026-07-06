"""Live-page checks for the sources the scheduled GitHub Actions ingest (trend-scrape.yml:
ramdam + socialbee + socialgrowthengineers daily; trend-scrape-newengen.yml monthly).

These hit the real pages, so they are opt-in — skipped unless LIVE_TREND_TESTS is set:

    LIVE_TREND_TESTS=1 pytest tests/test_live_trend_pages.py

What they prove, per source, WITHOUT spending Apify/OpenRouter money or touching the DB:
- ramdam/socialbee still parse fully structurally (heading parser, zero LLM) — the
  SimpleNamespace config has no OpenRouter key, so any fall-through to the LLM path raises
  and fails the test. That's the drift alarm: a page redesign that breaks the structural
  parse shows up here, not as silently-worse cards after a scheduled run.
- SGE's sitemap discovery + gated fetch still work and still yield candidate video URLs
  (its LLM parse itself isn't exercised — that's paid; needs SGE_ACCESS_TOKEN in the env).
- newengen's current month URL is live and still numbers its trends (its JS render needs
  Apify, so only the static-HTML numbering assumption is checked).
"""

from __future__ import annotations

import os
import re
from types import SimpleNamespace

import pytest
import requests

from instaagent_pipeline.trend_sources import (
    _is_video_url,
    _newengen_insights_url,
    fetch_sge_newsletter,
    fetch_trend_page,
    max_trend_number,
    parse_trend_formats,
    segment_headed_page,
    segment_numbered_page,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("LIVE_TREND_TESTS"),
    reason="live network tests; set LIVE_TREND_TESTS=1 to run",
)

# No OpenRouter key: parse_trend_formats raises if a source falls off the structural path.
NO_LLM_CONFIG = SimpleNamespace(openrouter_api_key=None)

_MONTH_DIVIDER_RE = re.compile(r"tiktok trends", re.I)


def _assert_structural_formats(formats, *, min_with_videos):
    linked = [f for f in formats if f["video_urls"]]
    assert len(linked) >= min_with_videos, f"only {len(linked)} formats with videos"
    for f in formats:
        assert f["format_name"].strip()
        assert not _MONTH_DIVIDER_RE.search(f["format_name"]), (
            f"month/page divider leaked in as a format: {f['format_name']!r}"
        )
        for u in f["video_urls"]:
            assert _is_video_url(u), f"non-video url attached: {u}"


def test_ramdam_parses_structurally():
    issue = fetch_trend_page("ramdam", "https://www.ramd.am/blog/trends-tiktok")
    formats = parse_trend_formats(NO_LLM_CONFIG, issue)  # raises if the LLM path is hit
    assert segment_numbered_page(issue) is None  # ramdam is heading-, not number-, driven
    _assert_structural_formats(formats, min_with_videos=1)


def test_socialbee_parses_structurally():
    issue = fetch_trend_page("socialbee", "https://socialbee.com/blog/tiktok-trends/")
    formats = parse_trend_formats(NO_LLM_CONFIG, issue)
    # The rolling page keeps months of archive, so a healthy parse is never thin.
    _assert_structural_formats(formats, min_with_videos=5)


def test_sge_discovery_and_gated_fetch_yield_candidates():
    token = os.getenv("SGE_ACCESS_TOKEN")
    if not token:
        pytest.skip("SGE_ACCESS_TOKEN not set (expired? re-run scratchpad/sge_unlock.py)")
    issue = fetch_sge_newsletter(
        "socialgrowthengineers", "https://www.socialgrowthengineers.com", access_token=token
    )
    assert "viral-hits-you-missed-this-week" in issue.source_url
    assert len(issue.text) > 500  # gated body actually came back, not a stub
    # The LLM parse (SGE_PARSE_PROMPT) needs candidates to assign; a linkless week (self-hosted
    # embeds only, e.g. 10-viral-hits-…-week-5) would legitimately yield zero — but the headed
    # structure must still be there for the description context.
    assert issue.html and issue.html.count("<h2") >= 3


def test_newengen_month_url_live_and_numbered():
    url = _newengen_insights_url()
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    assert resp.status_code == 200, f"{url} -> HTTP {resp.status_code} (month slug rolled over?)"
    n = max_trend_number(resp.text)
    assert n >= 3, f"page no longer numbers its trends (max Trend # = {n}); numbered parse breaks"


def test_headed_parser_agrees_with_candidate_harvest():
    """Every video the flattened-text harvest finds on ramdam must also be routed to some
    format by the heading parser — catches a drift where links move outside trend sections."""
    issue = fetch_trend_page("ramdam", "https://www.ramd.am/blog/trends-tiktok")
    formats = segment_headed_page(issue)
    assert formats is not None
    routed = {u.split("?", 1)[0] for f in formats for u in f["video_urls"]}
    harvested = {u.split("?", 1)[0] for u in issue.candidate_urls}
    assert harvested <= routed, f"harvested but unrouted: {harvested - routed}"
