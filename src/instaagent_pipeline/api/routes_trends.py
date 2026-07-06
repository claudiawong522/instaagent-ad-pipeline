"""Trends dashboard API — viral formats scraped from web trend pages.

GET /trends/formats returns each viral_formats row with its example videos (re-scraped
organic_items, source='trend') grouped under it, ranked by the videos' aggregate live views.
GET /trends/scrape-dates lists the distinct scrape-batch dates for the date filter.
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


@router.get("/trends/scrape-dates")
def list_trend_scrape_dates(request: Request, source_name: str | None = None) -> dict[str, Any]:
    """Distinct dates (UTC, YYYY-MM-DD) on which formats were scraped, newest-first — one chip per
    scrape batch for the given source (or all sources). Powers the /trends "Scraped" date filter."""
    dates = trends_module.list_trend_scrape_dates(require_supabase(request), source_name=source_name)
    return {"dates": dates}


@router.get("/trends/formats")
def list_trend_formats(
    request: Request,
    source_name: str | None = None,
    q: str | None = None,
    min_views: int = 0,
    posted_after: str | None = None,
    scraped_on: str | None = None,
    all_months: bool = False,
    limit: int = 200,
) -> dict[str, Any]:
    formats = trends_module.list_trend_formats(
        require_supabase(request),
        source_name=source_name,
        q=q,
        min_views=min_views,
        posted_after=posted_after,
        scraped_on=scraped_on,
        all_months=all_months,
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
