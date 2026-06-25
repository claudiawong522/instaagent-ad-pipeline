from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import campaigns as campaigns_module

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
    target_ugc_count: int = Field(default=50, ge=1, le=5000)


class ScrapeRequest(BaseModel):
    platform: str  # facebook | instagram | tiktok
    target_count: int | None = Field(default=None, ge=1, le=5000)  # new total to fetch (split per keyword)


def _supabase(request: Request):
    supabase = request.app.state.supabase
    if supabase is None:
        raise HTTPException(503, "Supabase is not configured (set SUPABASE_URL and a key).")
    return supabase


@router.post("/campaigns")
def create_campaign(req: CreateCampaignRequest, request: Request) -> dict[str, Any]:
    supabase = _supabase(request)
    config = request.app.state.config
    return campaigns_module.create_campaign(config, supabase, **req.model_dump())


@router.get("/campaigns")
def list_campaigns(request: Request) -> dict[str, Any]:
    return {"campaigns": campaigns_module.list_campaigns(_supabase(request))}


@router.get("/campaigns/{run_id}/scrape-stats")
def scrape_stats(run_id: str, request: Request) -> dict[str, Any]:
    return campaigns_module.scrape_stats(_supabase(request), run_id)


@router.post("/campaigns/{run_id}/scrape")
def scrape(run_id: str, req: ScrapeRequest, request: Request) -> dict[str, Any]:
    _supabase(request)  # ensure configured before launching the thread
    config = request.app.state.config
    try:
        return campaigns_module.trigger_scrape(config, run_id, req.platform, req.target_count)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/products")
def list_products(request: Request) -> dict[str, Any]:
    rows = _supabase(request).select(
        "products",
        {"select": "id,name,category,target_market,notes,created_at", "order": "created_at.desc"},
    )
    return {"products": rows}
