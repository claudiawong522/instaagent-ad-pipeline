from __future__ import annotations

from instaagent_pipeline.trend_ingest import _dedupe_formats, _video_key


def test_video_key_canonicalizes_tiktok_and_ig():
    assert _video_key("https://www.tiktok.com/@a/video/123?is_from_webapp=1") == "tt:123"
    assert _video_key("https://www.tiktok.com/@b/video/123/") == "tt:123"
    assert _video_key("https://instagram.com/reel/AbC123/") == "ig:abc123"


def test_dedupe_merges_formats_sharing_a_video():
    formats = [
        {"format_name": "Hands are full", "format_description": "x",
         "video_urls": ["https://www.tiktok.com/@a/video/7646"]},
        {"format_name": "Sorry I can't", "format_description": "y",
         "video_urls": ["https://www.tiktok.com/@a/video/7646?ref=1"]},
    ]
    out = _dedupe_formats(formats)
    assert len(out) == 1
    assert out[0]["format_name"] == "Hands are full"  # first one wins
    # the sibling's URL is unioned in, still one video after canonicalization
    assert {_video_key(u) for u in out[0]["video_urls"]} == {"tt:7646"}


def test_dedupe_keeps_distinct_formats_and_empty_ones():
    formats = [
        {"format_name": "A", "format_description": "", "video_urls": ["https://www.tiktok.com/@a/video/1"]},
        {"format_name": "B", "format_description": "", "video_urls": ["https://www.tiktok.com/@b/video/2"]},
        {"format_name": "Goals list", "format_description": "", "video_urls": []},
        {"format_name": "No example either", "format_description": "", "video_urls": []},
    ]
    out = _dedupe_formats(formats)
    # distinct videos stay separate; the two no-video formats are both kept (nothing to key on)
    assert [f["format_name"] for f in out] == ["A", "B", "Goals list", "No example either"]
