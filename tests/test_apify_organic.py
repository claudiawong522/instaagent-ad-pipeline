from __future__ import annotations

import json

import instaagent_pipeline.apify_organic as apify_organic
from instaagent_pipeline.apify_organic import ingest_tiktok, ingest_tiktok_trends
from instaagent_pipeline.config import Config
from instaagent_pipeline.normalizers import (
    normalize_instagram_reel,
    normalize_tiktok_item,
    normalize_tiktok_trend_item,
    recompute_virality,
    tiktok_trend_video_url,
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
    # log-normalized: reach 6.41 (cap 100)→0.434, eng rate 0.1 (cap 0.30)→0.363;
    # 0.6*0.434 + 0.4*0.363 = 0.406
    assert row["virality_score"] == 0.406
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
    # No views → no score.
    assert recompute_virality(views=0, likes=10, comments=0, shares=0) == (None, None)
    # No follower count → engagement-only fallback, log-normalized rate (cap 0.30).
    # er=0.2 → log1p(0.2)/log1p(0.30) = 0.695
    assert recompute_virality(views=1000, likes=200, comments=0, shares=0) == (0.695, "high")
    # Reach path: views 10x followers, blended 0.6/0.4 with engagement, both log-normalized.
    # reach=10 (cap 100)→0.520; er=0.1 (cap 0.30)→0.363; 0.6*0.520 + 0.4*0.363 = 0.457
    score, tier = recompute_virality(
        views=10000, likes=1000, comments=0, shares=0, followers=1000
    )
    assert score == 0.457 and tier == "medium"


# Condensed real novi/tiktok-trend-api item (raw TikTok aweme shape).
TIKTOK_TREND_ITEM = {
    "aweme_id": "7622543522922614029",
    "desc": "#viralvideo #fyp #vegas",
    "create_time": 1774761752,
    "region": "US",
    "is_ads": False,
    "statistics": {
        "play_count": 1580942,
        "digg_count": 150438,
        "comment_count": 7718,
        "share_count": 2878,
    },
    "author": {
        "unique_id": "username279296",
        "nickname": "Creator",
        "uid": "7622542160131032077",
        "sec_uid": "MS4sec",
        "avatar_medium": {"url_list": ["https://avatar.jpg"]},
        # note: no follower_count in the trend payload
    },
    "music": {"title": "sidewalks and skeletons goth", "author": "Trendformusic"},
    "cha_list": [{"cha_name": "viralvideo"}, {"cha_name": "fyp"}],
    "video": {
        "duration": 10657,
        "download_addr": {"url_list": ["https://cdn/nowm.mp4", "https://cdn/nowm2.mp4"]},
        "play_addr": {"url_list": ["https://cdn/play.mp4"]},
        "origin_cover": {"url_list": ["https://cdn/cover.jpg"]},
    },
}


def test_normalize_tiktok_trend_item() -> None:
    row = normalize_tiktok_trend_item(TIKTOK_TREND_ITEM, "run1", "raw1")
    assert row["source"] == "tiktok"
    assert row["external_id"] == "7622543522922614029"
    assert row["video_url"] == "https://cdn/nowm.mp4"  # download_addr preferred
    assert row["cover"] == "https://cdn/cover.jpg"
    assert row["handle"] == "username279296"
    assert row["user_id"] == "7622542160131032077"
    assert row["nickname"] == "Creator"
    assert row["avatar"] == "https://avatar.jpg"
    assert row["views"] == 1580942
    assert row["likes"] == 150438
    assert row["hashtags"] == ["viralvideo", "fyp"]
    assert row["music"] == {"title": "sidewalks and skeletons goth", "author": "Trendformusic"}
    assert row["followers"] is None  # absent from payload; backfilled separately
    # engagement-only virality (no followers): er=161034/1580942=0.1019 -> 0.37
    assert row["virality_score"] == 0.37
    assert row["virality_tier"] == "medium"
    assert row["date_created"].startswith("2026-")  # epoch seconds -> ISO
    assert row["source_metrics"]["endpoint_kind"] == "apify_tiktok_trend"
    assert row["source_metrics"]["region"] == "US"
    assert row["source_metrics"]["page_url"].endswith("/video/7622543522922614029")
    # analysis fields left for the vision enrichment
    assert "hook" not in row


def test_tiktok_trend_video_url_play_addr_fallback() -> None:
    # Some trending items omit download_addr but still carry a playable URL.
    item = {"video": {"play_addr": {"url_list": ["https://cdn/play-only.mp4"]}}}
    assert tiktok_trend_video_url(item) == "https://cdn/play-only.mp4"
    assert tiktok_trend_video_url({"video": {}}) is None


def test_ingest_tiktok_trends_actor_input(monkeypatch) -> None:
    captured: dict = {}

    def fake_run(*, api_key, actor_id, actor_input, target_count):
        captured["actor_id"] = actor_id
        captured["actor_input"] = actor_input
        return [TIKTOK_TREND_ITEM], 200, {}, {}

    monkeypatch.setattr(apify_organic, "run_apify_actor_items", fake_run)
    cfg = Config(
        supabase_url=None,
        supabase_key=None,
        apify_api_key="x",
        claude_api_key=None,
        claude_model="claude-haiku-4-5",
    )
    result = ingest_tiktok_trends(
        config=cfg,
        supabase=None,
        run_id="run1",
        region="US",
        target_count=50,
        dry_run=True,
    )
    assert captured["actor_id"] == "novi~tiktok-trend-api"
    assert captured["actor_input"] == {"region": "US", "limit": 50}
    assert result.fetched == 1  # the item has a download_addr, so it's kept


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
