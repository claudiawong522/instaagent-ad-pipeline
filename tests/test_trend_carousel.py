from __future__ import annotations

from instaagent_pipeline.trend_sources import _is_carousel_recommendation, html_to_text

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
