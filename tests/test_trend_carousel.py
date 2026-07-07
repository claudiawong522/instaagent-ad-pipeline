from __future__ import annotations

from datetime import date

from instaagent_pipeline.trend_sources import (
    _is_carousel_recommendation,
    _newengen_insights_url,
    html_to_text,
    issue_date_from_url,
)


def test_newengen_url_and_issue_date_track_the_month():
    for m, slug in ((1, "january"), (6, "june"), (7, "july"), (12, "december")):
        url = _newengen_insights_url(date(2026, m, 15))
        assert url == f"https://newengen.com/insights/{slug}-tiktok-trends/"
        assert issue_date_from_url(url, date(2026, m, 15)) == f"2026-{m:02d}-01"
    # weekly/undated sources carry no month → no issue_date
    assert issue_date_from_url("https://newengen.com/tiktok-trends/") is None
    assert issue_date_from_url("https://www.ramd.am/blog/trends-tiktok") is None

# The real (embedded) video for both the canonical link and its own share link.
EMBEDDED = "7637619596123557142"
# A carousel "you might also like" video injected next to the embed — stamped with the
# embedded video's id in referer_video_id, but a different id in its own path.
CAROUSEL = "7658772522833317142"


def test_carousel_recommendation_detection() -> None:
    rec = f"https://www.tiktok.com/share/video/{CAROUSEL}?referer_video_id={EMBEDDED}"
    matching_share = f"https://www.tiktok.com/share/video/{EMBEDDED}?referer_video_id={EMBEDDED}"
    canonical = f"https://www.tiktok.com/@charlixcx/video/{EMBEDDED}"
    plain_share = f"https://www.tiktok.com/share/video/{EMBEDDED}"

    assert _is_carousel_recommendation(rec) is True
    assert _is_carousel_recommendation(matching_share) is False
    assert _is_carousel_recommendation(canonical) is False
    assert _is_carousel_recommendation(plain_share) is False


def test_html_to_text_drops_carousel_but_keeps_the_embed() -> None:
    """A TikTok embed's canonical video is harvested; its recommendation carousel is not —
    otherwise random high-view videos get dumped onto the format (newengen's "Wow, Ok")."""
    html = f"""
    <blockquote class="tiktok-embed" cite="https://www.tiktok.com/@charlixcx/video/{EMBEDDED}">
      <a href="https://www.tiktok.com/@charlixcx/video/{EMBEDDED}">the real one</a>
      <a href="https://www.tiktok.com/share/video/{CAROUSEL}?referer_video_id={EMBEDDED}">you might also like</a>
    </blockquote>
    """
    _text, candidates = html_to_text(html)
    assert any(EMBEDDED in u for u in candidates)
    assert not any(CAROUSEL in u for u in candidates)
