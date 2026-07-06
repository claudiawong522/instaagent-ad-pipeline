"""Trends dashboard API — viral formats scraped from web trend pages.

GET /trends/formats returns each viral_formats row with its example videos (re-scraped
ugc_items, source='trend') grouped under it, ranked by the videos' aggregate live views.
POST /trends/match ranks those formats by how well a given product could reuse each one.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..http_client import HttpClientError
from .match import match_product

router = APIRouter()


class MatchRequest(BaseModel):
    product: str
    limit: int | None = None

# ugc_items fields the cards need (storage_* are filled by enrichment's MP4 persist).
_VIDEO_COLUMNS = (
    "id,format_id,storage_video_url,storage_thumb_url,video_url,cover,views,likes,"
    "virality_score,handle,description,enrichment_status,source_metrics,date_created"
)


def _supabase(request: Request):
    supabase = request.app.state.supabase
    if supabase is None:
        raise HTTPException(503, "Supabase is not configured (set SUPABASE_URL and a key).")
    return supabase


def _latest_month_per_source(formats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep, per source, only the formats from its most recent issue_date (the current monthly
    report), plus every undated format (weekly sources have no issue_date). Uses the latest month
    actually present — never today's calendar month — so the board is never empty at a month
    boundary before the new report is scraped."""
    latest: dict[str, str] = {}
    for f in formats:
        d = f.get("issue_date")
        if d:
            src = str(f.get("source_name"))
            if src not in latest or d > latest[src]:
                latest[src] = d
    return [
        f for f in formats
        if not f.get("issue_date") or f.get("issue_date") == latest.get(str(f.get("source_name")))
    ]


@router.get("/trends/formats")
def list_trend_formats(
    request: Request,
    source_name: str | None = None,
    q: str | None = None,
    min_views: int = 0,
    posted_after: str | None = None,
    all_months: bool = False,
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

    # Default to this month's trends only: per dated source, keep its most recent issue_date
    # (the current monthly report) so last month's trends drop off the board once the new report
    # is ingested — without deleting them (all_months=true still returns every month). Undated
    # (weekly) sources have no issue_date and are always kept.
    if not all_months:
        formats = _latest_month_per_source(formats)

    format_ids = [str(f["id"]) for f in formats if f.get("id")]
    videos_by_format: dict[str, list[dict[str, Any]]] = {}
    if format_ids:
        video_params: dict[str, Any] = {
            "select": _VIDEO_COLUMNS,
            "format_id": f"in.({','.join(format_ids)})",
            "order": "views.desc.nullslast",
            "limit": "2000",
        }
        if posted_after:
            video_params["date_created"] = f"gte.{posted_after}"
        rows = supabase.select("ugc_items", video_params)
        for row in rows:
            videos_by_format.setdefault(str(row.get("format_id")), []).append(_video_out(row))

    out: list[dict[str, Any]] = []
    for fmt in formats:
        videos = videos_by_format.get(str(fmt["id"]), [])
        # With a posted-date filter on, a format is only kept if it still has an
        # in-window example video (empty ones would otherwise pass the min_views gate).
        if posted_after and not videos:
            continue
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


@router.post("/trends/match")
def match_trends(request: Request, body: MatchRequest) -> dict[str, Any]:
    """Rank viral formats by how well the given product could reuse each one. Each returned
    format carries a fit verdict (great/workable/no), a 0-100 score, and a one-line idea for
    using it with this product. Same card shape as /trends/formats, plus those match fields."""
    supabase = _supabase(request)
    config = request.app.state.config
    if not (body.product or "").strip():
        return {"formats": []}
    try:
        formats = match_product(
            config,
            supabase,
            product=body.product,
            limit=body.limit or 30,
        )
    except HttpClientError as exc:
        raise HTTPException(502, f"Upstream error while matching: {exc}") from exc
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"formats": formats}


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
        "date_created": row.get("date_created"),
    }
