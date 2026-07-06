from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import campaigns as campaigns_module
from .deps import require_supabase

router = APIRouter()


class CreateCampaignRequest(BaseModel):
    product_name: str = Field(min_length=1)
    category: str | None = None
    target_market: str | None = None
    notes: str | None = None  # product description
    campaign_name: str = Field(min_length=1, max_length=120)
    marketing_goals: list[str] = []  # Awareness/Traffic/Engagement/Leads/App promotion/Sales
    campaign_objective: str | None = Field(default=None, max_length=2000)
    # How many items to scrape per platform. Small defaults — the pipeline's 1000/2500 are
    # for a full production run, not an exploratory UI scrape.
    target_paid_count: int = Field(default=50, ge=1, le=5000)
    target_ugc_count: int = Field(default=50, ge=1, le=5000)  # reels (Instagram)
    target_tiktok_count: int = Field(default=50, ge=1, le=5000)


class UpdateCampaignRequest(BaseModel):
    # Same editable detail fields as create (minus the scrape target counts, which are set
    # per-platform at scrape time). All required-on-create fields stay required here.
    product_name: str = Field(min_length=1)
    category: str | None = None
    target_market: str | None = None
    notes: str | None = None  # product description
    campaign_name: str = Field(min_length=1, max_length=120)
    marketing_goals: list[str] = []
    campaign_objective: str | None = Field(default=None, max_length=2000)


class ScrapeRequest(BaseModel):
    platform: str  # facebook | instagram | tiktok
    target_count: int | None = Field(default=None, ge=1, le=5000)  # new total to fetch (split per keyword)
    estimated_cost_usd: float | None = Field(default=None, ge=0)  # pre-scrape estimate from the UI


@router.post("/campaigns")
def create_campaign(req: CreateCampaignRequest, request: Request) -> dict[str, Any]:
    supabase = require_supabase(request)
    config = request.app.state.config
    return campaigns_module.create_campaign(config, supabase, **req.model_dump())


@router.get("/campaigns")
def list_campaigns(request: Request) -> dict[str, Any]:
    return {"campaigns": campaigns_module.list_campaigns(require_supabase(request))}


@router.patch("/campaigns/{run_id}")
def update_campaign(run_id: str, req: UpdateCampaignRequest, request: Request) -> dict[str, Any]:
    supabase = require_supabase(request)
    try:
        return campaigns_module.update_campaign(supabase, run_id, **req.model_dump())
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@router.get("/campaigns/{run_id}/scrape-stats")
def scrape_stats(run_id: str, request: Request) -> dict[str, Any]:
    return campaigns_module.scrape_stats(require_supabase(request), run_id)


@router.get("/campaigns/{run_id}/scrape-events")
def scrape_events(run_id: str, request: Request) -> dict[str, Any]:
    return campaigns_module.list_scrape_events(require_supabase(request), run_id)


@router.post("/campaigns/{run_id}/scrape")
def scrape(run_id: str, req: ScrapeRequest, request: Request) -> dict[str, Any]:
    require_supabase(request)  # ensure configured before launching the thread
    config = request.app.state.config
    try:
        return campaigns_module.trigger_scrape(
            config, run_id, req.platform, req.target_count, req.estimated_cost_usd
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
