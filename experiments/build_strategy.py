#!/usr/bin/env python3
"""Build web/strategy_data.js from live Supabase data.

Pulls the ICP clusters for BOTH sources (organic + paid ads) and their member
items, shaping them into the structure strategy.html renders: a source
toggle (Organic / Paid Ads), each holding one accordion per ICP / persona with
persona text + pains + scrolls-for + trending pillars + proven-format videos.

Re-run any time to refresh the page against the database:
    python web/build_strategy.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
OUT_PATH = ROOT / "web" / "strategy_data.js"

ORGANIC_FIELDS = [
    "id", "handle", "nickname", "country", "views", "likes",
    "video_url", "cover", "avatar", "description", "hook", "hashtags",
    "content_format", "virality_score", "virality_tier",
]
PAID_FIELDS = [
    "paid_ad_row_id", "id", "name", "headline", "description", "hook",
    "video", "image", "thumbnail", "avatar", "content_format", "video_topic",
    "niches", "market_target", "link_url", "source_metrics",
]


def load_env() -> tuple[str, str]:
    env: dict[str, str] = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")

    def pick(name: str) -> str | None:
        return os.environ.get(name) or env.get(name)

    raw = pick("SUPABASE_URL")
    key = pick("SUPABASE_SERVICE_ROLE_KEY") or pick("SUPABASE_ANON_KEY")
    if not raw or not key:
        sys.exit("SUPABASE_URL and a Supabase key must be set (env or .env).")
    base = re.sub(r"/rest/v1/?$", "", raw).rstrip("/")
    return base, key


def fetch(base: str, key: str, path: str, params: dict[str, str]) -> list[dict]:
    url = f"{base}/rest/v1/{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url, headers={"apikey": key, "Authorization": f"Bearer {key}"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
        return json.loads(resp.read().decode())


def humanize(n) -> str:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "—"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".replace(".0M", "M")
    if n >= 1_000:
        return f"{round(n / 1_000)}K"
    return str(n)


def embed_for(video_url: str) -> dict[str, str]:
    """Map a TikTok/Instagram page URL to an embeddable iframe URL."""
    if not video_url:
        return {"platform": "", "embed_url": ""}
    m = re.search(r"tiktok\.com/.+/video/(\d+)", video_url)
    if m:
        return {"platform": "tiktok",
                "embed_url": f"https://www.tiktok.com/embed/v2/{m.group(1)}"}
    m = re.search(r"instagram\.com/(?:p|reel)/([^/?#]+)", video_url)
    if m:
        return {"platform": "instagram",
                "embed_url": f"https://www.instagram.com/p/{m.group(1)}/embed"}
    return {"platform": "other", "embed_url": ""}


def map_organic(it: dict) -> dict:
    return {
        "handle": "@" + (it.get("handle") or "creator"),
        "nickname": it.get("nickname") or "",
        "country": it.get("country") or "—",
        "metric": humanize(it.get("views")),
        "unit": "views",
        "cover": it.get("cover") or "",
        "description": it.get("description") or "",
        "hook": it.get("hook") or "",
        "format": (it.get("content_format") or "").replace("_", " "),
        "tier": (it.get("virality_tier") or "").upper(),
        "score": it.get("virality_score") or 0,
        "video_url": it.get("video_url") or "",
        "direct_video": "",
        **embed_for(it.get("video_url") or ""),
        "tags": [re.sub(r"[^\w]+$", "", str(h)) for h in (it.get("hashtags") or [])],
    }


def map_paid(it: dict) -> dict:
    sm = it.get("source_metrics") or {}
    snap = sm.get("snapshot") or {}
    likes = snap.get("pageLikeCount")
    ad_id = it.get("id")
    return {
        "handle": "@" + (snap.get("pageName") or it.get("name") or "brand"),
        "nickname": it.get("name") or snap.get("pageName") or "",
        "country": it.get("market_target") or (snap.get("pageCategories") or ["—"])[0],
        "metric": humanize(likes),
        "unit": "page likes",
        "cover": it.get("thumbnail") or it.get("image") or "",
        "description": it.get("description") or it.get("headline") or "",
        "hook": it.get("hook") or "",
        "format": (it.get("content_format") or "").replace("_", " "),
        "tier": "AD",
        "score": likes or 0,
        # Direct fbcdn mp4 plays in a <video> tag; open-original points at the
        # Meta Ad Library entry for the ad.
        "direct_video": it.get("video") or "",
        "video_url": (f"https://www.facebook.com/ads/library/?id={ad_id}"
                      if ad_id else (it.get("link_url") or "")),
        "platform": "paid",
        "embed_url": "",
        "tags": [str(n) for n in (it.get("niches") or [])],
    }


def build_source(base, key, run_id, item_type, table, pk, fields, mapper) -> dict:
    clusters = fetch(base, key, "clusters", {
        "run_id": f"eq.{run_id}",
        "item_type": f"eq.{item_type}",
        "space": "eq.icp",
        "select": "cluster_label,name,label_json,member_count",
        "order": "cluster_label",
    })
    clusters = [c for c in clusters if c["cluster_label"] != -1]

    memberships = fetch(base, key, "item_clusters", {
        "run_id": f"eq.{run_id}",
        "item_type": f"eq.{item_type}",
        "space": "eq.icp",
        "select": "item_id,cluster_label",
    })
    by_cluster: dict[int, list[str]] = {}
    for m in memberships:
        if m["cluster_label"] != -1:
            by_cluster.setdefault(m["cluster_label"], []).append(m["item_id"])

    all_ids = [i for ids in by_cluster.values() for i in ids]
    items_by_id: dict[str, dict] = {}
    if all_ids:
        rows = fetch(base, key, table, {
            pk: f"in.({','.join(all_ids)})",
            "select": ",".join(fields),
        })
        items_by_id = {r[pk]: r for r in rows}

    icps, total, unlabeled = [], 0, []
    for c in clusters:
        lab = c.get("label_json") or {}
        if not lab.get("persona"):
            # Cluster exists but the LLM labeling step didn't fill it in
            # (label_failed, --no-label, or missing OPENROUTER_API_KEY).
            unlabeled.append(c["cluster_label"])
        videos, tags, seen = [], [], set()
        for iid in by_cluster.get(c["cluster_label"], []):
            it = items_by_id.get(iid)
            if not it:
                continue
            v = mapper(it)
            for t in v.pop("tags", []):
                if t and t.lower() not in {x.lower() for x in tags}:
                    tags.append(t)
            # Collapse duplicate creatives: brands re-run the same video under
            # several ad ids. Key on the media URL minus its (signed) querystring.
            dkey = ((v.get("direct_video") or "").split("?")[0]
                    or v.get("video_url") or v.get("cover") or iid)
            if dkey in seen:
                continue
            seen.add(dkey)
            videos.append(v)
        videos.sort(key=lambda v: v.get("score") or 0, reverse=True)
        videos = videos[:12]   # cap the rail at the top 12 by score
        for i, v in enumerate(videos):
            v["picked"] = i == 0
        total += len(videos)
        icps.append({
            "name": c.get("name") or lab.get("persona") or f"ICP {c['cluster_label']}",
            "persona": lab.get("persona") or "",
            "pains": lab.get("pains") or [],
            "scrolls_for": lab.get("scrolls_for") or [],
            "quote": lab.get("quote") or "",
            "tags": tags[:10],
            "count": len(videos),
            "videos": videos,
        })
    return {"persona_count": len(icps), "generation_count": total,
            "icps": icps, "unlabeled": unlabeled}


def resolve_run_id(base, key) -> str:
    """The run to render: RUN_ID env override, else the newest run that has
    ICP clusters. Scoping to one run keeps the page from mixing personas
    across pipeline runs once more than one run exists in the database."""
    override = os.environ.get("RUN_ID")
    if override:
        return override
    rows = fetch(base, key, "clusters", {
        "space": "eq.icp",
        "select": "run_id,created_at",
        "order": "created_at.desc",
        "limit": "1",
    })
    if not rows:
        sys.exit("No ICP clusters found — run the cluster-items stage first.")
    return rows[0]["run_id"]


def build() -> dict:
    base, key = load_env()
    run_id = resolve_run_id(base, key)
    organic = build_source(base, key, run_id, "ugc_item", "ugc_items", "id",
                       ORGANIC_FIELDS, map_organic)
    paid = build_source(base, key, run_id, "paid_ad", "paid_ads", "paid_ad_row_id",
                        PAID_FIELDS, map_paid)
    return {
        "campaign": "QV Summer Product Launch",
        "product": "QV (Ego Pharmaceuticals)",
        "run_id": run_id,
        "sources": [
            {"key": "ugc", "label": "Organic", **organic},
            {"key": "paid_ad", "label": "Paid Ads", **paid},
        ],
    }


def main() -> None:
    data = build()
    print(f"run_id: {data['run_id']}")
    warnings = []
    for s in data["sources"]:
        unlabeled = s.pop("unlabeled", [])   # keep it out of the emitted JSON
        if unlabeled:
            warnings.append(f"{s['label']} clusters missing LLM labels: {unlabeled}")
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    OUT_PATH.write_text(f"window.STRATEGY_DATA = {payload};\n")
    for s in data["sources"]:
        print(f"{s['label']}: {s['persona_count']} ICPs, "
              f"{s['generation_count']} videos.")
    if warnings:
        print("\n⚠️  LABELING INCOMPLETE — these personas will render blank:")
        for w in warnings:
            print(f"   - {w}")
        print("   Re-run: instaagent cluster-items --run-id "
              f"{data['run_id']} --source all  (ensure OPENROUTER_API_KEY is set)")


if __name__ == "__main__":
    main()
