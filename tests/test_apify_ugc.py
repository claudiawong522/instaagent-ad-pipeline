from __future__ import annotations

import json

from instaagent_pipeline.apify_ugc import ingest_tiktok
from instaagent_pipeline.config import Config
from instaagent_pipeline.normalizers import (
    normalize_instagram_reel,
    normalize_tiktok_item,
    recompute_virality,
)

TIKTOK_ITEM = {
    "id": "7611",
    "text": "gentle cleanser routine #skincare",
    "playCount": 100000,
    "diggCount": 8000,
    "commentCount": 1500,
    "shareCount": 500,
    "webVideoUrl": "https://www.tiktok.com/@creator/video/7611",
    "mediaUrls": ["https://cdn.apify/video.mp4"],
    "authorMeta": {"name": "creator", "nickName": "Creator", "fans": 15600, "avatar": "https://a", "id": "u1"},
    "videoMeta": {"coverUrl": "https://cover.jpg"},
    "musicMeta": {"musicName": "original sound"},
    "createTimeISO": "2026-06-01T00:00:00.000Z",
    "hashtags": [{"name": "skincare"}, {"name": "cleanser"}],
}

IG_ITEM = {
    "id": "331",
    "code": "ABC",
    "video_url": "https://cdn.ig/reel.mp4",
    "thumbnail_url": "https://t.jpg",
    "play_count": 816959,
    "like_count": 5268,
    "comment_count": 120,
    "share_count": 40,
    "caption": {"text": "acne facial routine"},
    "user": {"username": "derm", "full_name": "Dr Derm", "pk": "99", "profile_pic_url": "https://p"},
}


def test_normalize_tiktok_item() -> None:
    row = normalize_tiktok_item(TIKTOK_ITEM, "run1", "raw1")
    assert row["source"] == "tiktok"
    assert row["external_id"] == "7611"
    assert row["video_url"] == "https://cdn.apify/video.mp4"  # direct mp4, not the page url
    assert row["followers"] == 15600
    assert row["views"] == 100000
    assert row["likes"] == 8000
    assert row["handle"] == "creator"
    assert row["hashtags"] == ["skincare", "cleanser"]
    assert row["cover"] == "https://cover.jpg"
    assert row["music"] == {"title": "original sound"}
    assert row["virality_score"] == 10.0  # (8000+1500+500)/100000*100
    assert row["virality_tier"] == "medium"
    assert row["source_metrics"]["page_url"] == "https://www.tiktok.com/@creator/video/7611"
    # analysis fields are left for the vision enrichment
    assert "hook" not in row


def test_normalize_instagram_reel() -> None:
    row = normalize_instagram_reel(IG_ITEM, "run1", "raw1")
    assert row["source"] == "instagram"
    assert row["video_url"] == "https://cdn.ig/reel.mp4"
    assert row["views"] == 816959
    assert row["handle"] == "derm"
    assert row["nickname"] == "Dr Derm"
    assert row["followers"] is None  # backfilled separately (platform limit)
    assert row["description"] == "acne facial routine"
    assert row["cover"] == "https://t.jpg"
    assert row["source_metrics"]["page_url"] == "https://www.instagram.com/reel/ABC/"


def test_recompute_virality() -> None:
    assert recompute_virality(views=0, likes=10, comments=0, shares=0) == (None, None)
    score, tier = recompute_virality(views=1000, likes=200, comments=0, shares=0)
    assert score == 20.0 and tier == "high"


def test_ingest_tiktok_drops_no_video(tmp_path) -> None:
    fixture = tmp_path / "tt.json"
    # Second item has no mediaUrls/downloadAddr → no downloadable video → dropped.
    fixture.write_text(json.dumps([TIKTOK_ITEM, {"id": "nope", "webVideoUrl": "https://x"}]))
    cfg = Config(
        supabase_url=None,
        supabase_key=None,
        apify_api_key=None,
        claude_api_key=None,
        claude_model="claude-haiku-4-5",
    )
    result = ingest_tiktok(
        config=cfg,
        supabase=None,
        run_id="run1",
        keyword="cleanser",
        target_count=10,
        dry_run=True,
        input_json=fixture,
    )
    assert result.fetched == 1
    assert result.written == 0
