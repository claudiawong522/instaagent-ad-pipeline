"""segment_headed_page: deterministically split a heading-delimited page into one format per
video-owning heading, auto-detecting which heading level owns the videos."""

from instaagent_pipeline.trend_sources import TrendIssue, segment_headed_page


def _issue(html):
    return TrendIssue(
        source_name="ramdam", source_url="u", content_hash="h", text="", html=html
    )


RAMDAM_STYLE = """
<html><body>
<h1>Tiktok Trends - July 2026</h1>
<h2>6 July 2026</h2>
<h4>The Inspiration Sound trend</h4>
<p>Creators lip-sync the inspiration sound. How to do it: point and smile.</p>
<blockquote cite="https://www.tiktok.com/@amy/video/111"></blockquote>
<a href="https://www.tiktok.com/@amy/video/111?is_from_webapp=1">watch</a>
<h4>The No Pen Or Paper trend</h4>
<p>Writing without pen or paper.</p>
<iframe src="https://www.tiktok.com/@gray/video/222"></iframe>
<h2>Read more articles</h2>
<h4>Customers</h4>
<h4>Resources</h4>
</body></html>
"""


def test_detects_owner_level_and_splits_per_heading():
    out = segment_headed_page(_issue(RAMDAM_STYLE))
    names = [f["format_name"] for f in out]
    assert names[:2] == ["The Inspiration Sound trend", "The No Pen Or Paper trend"]
    assert out[0]["video_urls"] == ["https://www.tiktok.com/@amy/video/111"]  # cite+anchor deduped
    assert out[1]["video_urls"] == ["https://www.tiktok.com/@gray/video/222"]


def test_description_trims_at_boilerplate():
    out = segment_headed_page(_issue(RAMDAM_STYLE))
    assert out[0]["format_description"] == "Creators lip-sync the inspiration sound."


def test_nav_junk_headings_return_empty_and_are_left_to_ingest_filter():
    out = segment_headed_page(_issue(RAMDAM_STYLE))
    junk = [f for f in out if f["format_name"] in ("Customers", "Resources")]
    assert all(f["video_urls"] == [] for f in junk)  # ingest's zero-link filter drops these


SOCIALBEE_STYLE = """
<html><body>
<h2>June 2026 TikTok trends</h2>
<h3>Fendi dance</h3>
<p>Dance to the Fendi sound.</p>
<a href="https://www.tiktok.com/@a/video/111?_r=1">v</a>
<h3>Goals list</h3>
<p>List your goals. No embed here.</p>
<h2>May 2026 TikTok trends</h2>
<a href="https://www.tiktok.com/@stray/video/999">stray link under month divider</a>
<h3>Pose trend</h3>
<p>Strike the pose.</p>
<a href="https://www.tiktok.com/@b/video/222">v</a>
</body></html>
"""


def test_month_divider_closes_section_and_strays_dont_leak():
    out = segment_headed_page(_issue(SOCIALBEE_STYLE))
    by_name = {f["format_name"]: f["video_urls"] for f in out}
    assert by_name["Fendi dance"] == ["https://www.tiktok.com/@a/video/111?_r=1"]
    assert by_name["Goals list"] == []  # divider-stray 999 must NOT attach to the previous trend
    assert by_name["Pose trend"] == ["https://www.tiktok.com/@b/video/222"]


def test_carousel_recommendation_links_excluded():
    html = """
    <h3>Real trend</h3>
    <a href="https://www.tiktok.com/share/video/111?referer_video_id=111">real</a>
    <a href="https://www.tiktok.com/share/video/999?referer_video_id=111">carousel junk</a>
    <h3>Other trend</h3>
    <a href="https://www.tiktok.com/@u/video/222">v</a>
    """
    out = segment_headed_page(_issue(html))
    assert out[0]["video_urls"] == ["https://www.tiktok.com/share/video/111?referer_video_id=111"]


def test_ambiguous_page_falls_back_to_llm():
    one_section = '<h3>Only trend</h3><a href="https://www.tiktok.com/@u/video/1">v</a>'
    assert segment_headed_page(_issue(one_section)) is None  # <2 video-owning sections
    assert segment_headed_page(_issue("<p>no headings at all</p>")) is None
    assert segment_headed_page(_issue(None)) is None  # no html captured (e.g. old TrendIssue)
