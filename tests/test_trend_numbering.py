"""max_trend_number: read a roundup's own 'Trend #N' numbering as the authoritative trend count.
segment_numbered_page: deterministically split a numbered page into one format per trend."""

from instaagent_pipeline.trend_sources import (
    TrendIssue,
    max_trend_number,
    segment_numbered_page,
)


def test_counts_highest_numbered_trend():
    text = (
        "Trend #1: Rock Music Glitch\n...\n"
        "Trend #2: Wow, Ok\n...\n"
        "Trend #11:  Honeybee Carousel\n"
    )
    assert max_trend_number(text) == 11


def test_tolerates_hash_and_spacing_variants():
    assert max_trend_number("Trend #6: x\nTrend 7 y\ntrend #  8 z") == 8


def test_unnumbered_page_is_zero():
    assert max_trend_number("Fendi dance\nPose trend\nHorse slideshow") == 0


# ── segment_numbered_page ──────────────────────────────────────────────────────────

def _issue(text, urls):
    return TrendIssue(source_name="newengen", source_url="u", content_hash="h", text=text, candidate_urls=urls)


def test_one_format_per_numbered_trend_no_merge():
    text = (
        'Trend #1: Alpha Title\nAlpha is a dance. How to do it: shuffle.\n'
        'https://www.tiktok.com/@u1/video/111\n'
        'Trend #2: Beta (Makes You Smile)\nBeta explanation here.\n'
        'https://www.tiktok.com/@u2/video/222\n'
    )
    urls = ["https://www.tiktok.com/@u1/video/111", "https://www.tiktok.com/@u2/video/222"]
    out = segment_numbered_page(_issue(text, urls))
    assert [f["format_name"] for f in out] == ["Alpha Title", "Beta (Makes You Smile)"]  # full titles, split
    assert out[0]["video_urls"] == ["https://www.tiktok.com/@u1/video/111"]
    assert out[1]["video_urls"] == ["https://www.tiktok.com/@u2/video/222"]  # not borrowed across sections
    assert out[0]["format_description"] == "Alpha is a dance."  # trimmed at "How to do it:"


def test_dead_video_trend_returns_with_no_urls():
    text = "Trend #1: Live One\nhas a video.\nhttps://www.tiktok.com/@u/video/111\nTrend #2: Dead One\nno embed rendered.\n"
    out = segment_numbered_page(_issue(text, ["https://www.tiktok.com/@u/video/111"]))
    assert out[1]["format_name"] == "Dead One"
    assert out[1]["video_urls"] == []


def test_unnumbered_page_falls_back_to_llm():
    assert segment_numbered_page(_issue("Fendi dance\nPose trend\n", [])) is None
