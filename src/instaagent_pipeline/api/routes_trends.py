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
from . import trends as trends_module
from .deps import require_supabase

router = APIRouter()


class MatchRequest(BaseModel):
    product: str
    limit: int | None = None


@router.get("/trends/formats")
def list_trend_formats(
    request: Request,
    source_name: str | None = None,
    q: str | None = None,
    min_views: int = 0,
    posted_after: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    formats = trends_module.list_trend_formats(
        require_supabase(request),
        source_name=source_name,
        q=q,
        min_views=min_views,
        posted_after=posted_after,
        limit=limit,
    )
    return {"formats": formats}


@router.post("/trends/match")
def match_trends(request: Request, body: MatchRequest) -> dict[str, Any]:
    """Rank viral formats by how well the given product could reuse each one. Each returned
    format carries a fit verdict (great/workable/no), a 0-100 score, and a one-line idea for
    using it with this product. Same card shape as /trends/formats, plus those match fields."""
    supabase = require_supabase(request)
    config = request.app.state.config
    if not (body.product or "").strip():
        return {"formats": []}
    try:
        formats = trends_module.match_product(
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
