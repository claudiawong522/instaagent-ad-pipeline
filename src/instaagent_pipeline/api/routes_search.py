from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import search as search_module

router = APIRouter()


class SearchRequest(BaseModel):
    query: str
    item_type: Optional[str] = None  # 'paid_ad' | 'ugc_item' | None (both)
    platform: Optional[str] = None  # 'tiktok' | 'instagram' | 'meta'
    run_id: Optional[str] = None
    min_virality: Optional[float] = None  # UGC-only (engagement rate %)
    min_views: Optional[int] = None  # UGC-only
    min_days_live: Optional[float] = None  # paid-only (days the ad has been running)
    languages: Optional[list[str]] = None  # multi-select, overlap match
    age_brackets: Optional[list[str]] = None  # multi-select, overlap match
    price_tier: Optional[str] = None  # single (budget/mid/premium/luxury)
    # None = no count cap; results are gated by the relevance threshold (search_ads
    # caps at MAX_RESULTS as a safety bound). A value still caps to that many.
    limit: Optional[int] = Field(default=None, ge=1, le=1000)


def _require_supabase(request: Request):
    supabase = request.app.state.supabase
    if supabase is None:
        raise HTTPException(503, "Supabase is not configured (set SUPABASE_URL and a key).")
    return supabase


@router.post("/search")
def search(req: SearchRequest, request: Request) -> dict[str, Any]:
    supabase = _require_supabase(request)
    # An empty query is allowed: search_ads treats it as "browse all ads".
    if req.item_type not in (None, "paid_ad", "ugc_item"):
        raise HTTPException(400, "item_type must be 'paid_ad' or 'ugc_item'")
    try:
        results = search_module.search_ads(
            request.app.state.config,
            supabase,
            query=req.query.strip(),
            item_type=req.item_type,
            platform=req.platform,
            run_id=req.run_id,
            min_virality=req.min_virality,
            min_views=req.min_views,
            min_days_live=req.min_days_live,
            languages=req.languages,
            age_brackets=req.age_brackets,
            price_tier=req.price_tier,
            limit=req.limit,
        )
    except RuntimeError as exc:
        raise HTTPException(500, str(exc))
    return {"query": req.query, "count": len(results), "results": results}


@router.get("/runs")
def runs(request: Request) -> dict[str, Any]:
    return {"runs": search_module.list_runs(_require_supabase(request))}


@router.get("/items/{item_type}/{item_id}")
def item(item_type: str, item_id: str, request: Request) -> dict[str, Any]:
    result = search_module.get_item(
        request.app.state.config, _require_supabase(request), item_type, item_id
    )
    if result is None:
        raise HTTPException(404, "item not found")
    return result
