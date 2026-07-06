"""Trends dashboard API — viral formats scraped from web trend pages.

GET /trends/formats returns each viral_formats row with its example videos (re-scraped
ugc_items, source='trend') grouped under it, ranked by the videos' aggregate live views.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

router = APIRouter()

# ugc_items fields the cards need (storage_* are filled by enrichment's MP4 persist).
_VIDEO_COLUMNS = (
    "id,format_id,storage_video_url,storage_thumb_url,video_url,cover,views,likes,"
    "virality_score,handle,description,enrichment_status,source_metrics"
)


def _supabase(request: Request):
    supabase = request.app.state.supabase
    if supabase is None:
        raise HTTPException(503, "Supabase is not configured (set SUPABASE_URL and a key).")
    return supabase


@router.get("/trends/formats")
def list_trend_formats(
    request: Request,
    source_name: str | None = None,
    q: str | None = None,
    min_views: int = 0,
    limit: int = 200,
) -> dict[str, Any]:
    supabase = _supabase(request)

    params: dict[str, Any] = {
        "select": "id,source_name,source_url,issue_date,format_name,format_description,niche_constraint,ingest_note,created_at",
        "order": "created_at.desc",
        "limit": str(max(1, min(limit, 1000))),
    }
    if source_name:
        params["source_name"] = f"eq.{source_name}"
    if q:
        params["niche_constraint"] = f"ilike.*{q}*"
    formats = supabase.select("viral_formats", params)
    if not formats:
        return {"formats": []}

    format_ids = [str(f["id"]) for f in formats if f.get("id")]
    videos_by_format: dict[str, list[dict[str, Any]]] = {}
    if format_ids:
        rows = supabase.select(
            "ugc_items",
            {
                "select": _VIDEO_COLUMNS,
                "format_id": f"in.({','.join(format_ids)})",
                "order": "views.desc.nullslast",
                "limit": "2000",
            },
        )
        for row in rows:
            videos_by_format.setdefault(str(row.get("format_id")), []).append(_video_out(row))

    out: list[dict[str, Any]] = []
    for fmt in formats:
        videos = videos_by_format.get(str(fmt["id"]), [])
        agg_views = sum(v["views"] or 0 for v in videos)
        if agg_views < min_views:
            continue
        out.append(
            {
                "id": fmt["id"],
                "source_name": fmt.get("source_name"),
                "source_url": fmt.get("source_url"),
                "issue_date": fmt.get("issue_date"),
                "format_name": fmt.get("format_name"),
                "format_description": fmt.get("format_description"),
                "niche_constraint": fmt.get("niche_constraint"),
                "ingest_note": fmt.get("ingest_note"),
                "video_count": len(videos),
                "total_views": agg_views,
                "videos": videos,
            }
        )

    # Rank formats by aggregate live views (most viral first).
    out.sort(key=lambda f: f["total_views"], reverse=True)
    return {"formats": out}


def _video_out(row: dict[str, Any]) -> dict[str, Any]:
    metrics = row.get("source_metrics") if isinstance(row.get("source_metrics"), dict) else {}
    return {
        "id": row.get("id"),
        "video_url": row.get("storage_video_url") or row.get("video_url"),
        "thumb_url": row.get("storage_thumb_url") or row.get("cover"),
        "original_url": metrics.get("page_url"),
        "views": row.get("views"),
        "likes": row.get("likes"),
        "virality": row.get("virality_score"),
        "handle": row.get("handle"),
        "description": row.get("description"),
        "enrichment_status": row.get("enrichment_status"),
    }
