from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from . import discover as discover_module
from .deps import require_supabase

router = APIRouter()


class DiscoverRequest(BaseModel):
    region: str = Field(default="US", min_length=2, max_length=2)  # ISO country code, e.g. US/GB
    target_count: int = Field(default=200, ge=1, le=1000)
    min_views: int = Field(default=0, ge=0)  # drop For-You feed-filler below this view count
    estimated_cost_usd: float | None = Field(default=None, ge=0)


@router.post("/discover/scrape")
def discover_scrape(req: DiscoverRequest, request: Request) -> dict[str, Any]:
    """Trigger a keyword-free TikTok viral-format pull. Returns the discovery run_id; poll
    /campaigns/{run_id}/scrape-stats for live progress (it's a normal pipeline_run)."""
    supabase = require_supabase(request)
    config = request.app.state.config
    return discover_module.trigger_discovery(
        config,
        supabase,
        region=req.region.upper(),
        target_count=req.target_count,
        min_views=req.min_views,
        estimated_cost_usd=req.estimated_cost_usd,
    )
