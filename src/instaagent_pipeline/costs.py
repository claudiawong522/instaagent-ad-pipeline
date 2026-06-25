"""Scrape cost: a rough pre-scrape estimate plus actual-cost reconciliation from api_usage.

A "scrape" runs Apify ingest -> LLM enrichment -> embeddings. Apify reports a real USD figure
(usageTotalUsd, stored on each api_usage row's rate_limit); the LLM and embedding calls only log
token counts, so we price those from the table below. The numbers are approximate and centralized
here so they're easy to update when provider pricing changes -- this is a spend gauge, not
accounting. The estimate is summed across the whole scrape (Apify + LLM + embeddings) and never
broken down per provider in the UI.
"""
from __future__ import annotations

from typing import Any

from .supabase_client import SupabaseClient

# Rough blended USD cost per scraped item (Apify fetch + LLM enrichment + embedding), per platform.
# Drives only the pre-scrape estimate. Mirror in frontend/app/campaigns/page.tsx (COST_PER_ITEM_USD).
EST_COST_PER_ITEM_USD: dict[str, float] = {
    "facebook": 0.012,
    "instagram": 0.010,
    "tiktok": 0.010,
}
_DEFAULT_PER_ITEM = 0.012

# Token pricing (USD per 1M tokens) for the LLM + embedding spend that only logs tokens. Keyed by a
# substring matched against the model name recorded on the api_usage row; (input_rate, output_rate).
# Embeddings/rerankers bill input only.
TOKEN_PRICING_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "gemini-3-flash": (0.30, 2.50),
    "gemini-flash": (0.075, 0.30),
    "voyage": (0.07, 0.0),
    "rerank": (0.05, 0.0),
}


def estimate_cost(platform: str, new_items: int) -> float:
    """Pre-scrape estimate: blended per-item cost x the number of new items to fetch."""
    per_item = EST_COST_PER_ITEM_USD.get(platform, _DEFAULT_PER_ITEM)
    return round(per_item * max(0, new_items), 4)


def reconcile_actual_cost(supabase: SupabaseClient, run_id: str, started_at: str | None = None) -> float:
    """Sum the real spend for a run from its api_usage rows: Apify rows carry a real USD figure
    (actor_usage_total_usd); LLM/embedding rows carry only token counts, priced via TOKEN_PRICING.

    With `started_at` (a scrape_event's DB timestamp), only rows from that scrape onward are
    counted, so each scrape is reconciled to its own window. With None, every row for the run is
    summed -- used to recover spend that predates per-scrape tracking.
    """
    params = {"select": "rate_limit", "run_id": f"eq.{run_id}", "limit": "100000"}
    if started_at:
        params["request_timestamp"] = f"gte.{started_at}"
    rows = supabase.select("api_usage", params)
    return round(sum(_row_usd(row.get("rate_limit") or {}) for row in rows), 4)


def _row_usd(meta: dict[str, Any]) -> float:
    """USD for one api_usage row: a real Apify figure, or token-priced LLM/embedding usage."""
    total = 0.0
    apify_usd = meta.get("actor_usage_total_usd")
    if apify_usd is not None:
        try:
            total += float(apify_usd)
        except (TypeError, ValueError):
            pass
    usage = meta.get("usage")
    if isinstance(usage, dict):
        total += _token_cost(str(meta.get("model") or ""), usage)
    return total


def _platform_of(provider: str) -> str | None:
    for key in ("facebook", "tiktok", "instagram"):
        if key in provider:
            return key
    return None


def reconstruct_history(
    supabase: SupabaseClient, run_id: str, before_iso: str | None = None
) -> list[dict[str, Any]]:
    """Rebuild spend that predates per-scrape tracking as one row per platform, from api_usage.

    Old scrapes were never recorded as discrete events (and a CLI run hits all platforms in one
    interleaved burst), so they can't be split per-trigger. Apify cost is per-platform; the shared
    enrichment/embedding spend is allocated across platforms by items fetched (response_count). Each
    row is dated at that platform's first ingestion. `before_iso` excludes rows already covered by
    tracked scrape_events. Returns [] when there's nothing to reconstruct."""
    params: dict[str, Any] = {
        "select": "provider,rate_limit,request_timestamp",
        "run_id": f"eq.{run_id}",
        "order": "request_timestamp.asc",
        "limit": "100000",
    }
    if before_iso:
        params["request_timestamp"] = f"lt.{before_iso}"
    rows = supabase.select("api_usage", params)

    per: dict[str, dict[str, Any]] = {}
    shared = 0.0
    for row in rows:
        meta = row.get("rate_limit") or {}
        cost = _row_usd(meta)
        platform = _platform_of(str(row.get("provider") or ""))
        if platform is None:  # enrichment / embedding / keyword-gen — not platform-tagged
            shared += cost
            continue
        agg = per.setdefault(platform, {"cost": 0.0, "weight": 0, "when": row.get("request_timestamp")})
        agg["cost"] += cost
        try:
            agg["weight"] += int(meta.get("response_count") or 0)
        except (TypeError, ValueError):
            pass

    total_weight = sum(a["weight"] for a in per.values())
    out: list[dict[str, Any]] = []
    for platform, agg in per.items():
        share = shared * (agg["weight"] / total_weight) if total_weight else (shared / len(per) if per else 0.0)
        out.append(
            {
                "platform": platform,
                "when": agg["when"],
                "cost_usd": round(agg["cost"] + share, 4),
                "items": agg["weight"],
            }
        )
    return out


def _token_cost(model: str, usage: dict[str, Any]) -> float:
    name = model.lower()
    price = next((p for key, p in TOKEN_PRICING_USD_PER_MTOK.items() if key in name), None)
    if price is None:
        return 0.0
    in_rate, out_rate = price
    # Accept OpenAI/OpenRouter (prompt/completion_tokens), Gemini (promptTokenCount/
    # candidatesTokenCount) and Voyage (total_tokens) shapes.
    in_tok = usage.get("prompt_tokens") or usage.get("promptTokenCount") or usage.get("input_tokens") or 0
    out_tok = usage.get("completion_tokens") or usage.get("candidatesTokenCount") or usage.get("output_tokens") or 0
    total_tok = usage.get("total_tokens") or usage.get("totalTokenCount") or 0
    if not in_tok and not out_tok and total_tok:
        in_tok = total_tok  # embeddings report only a grand total
    try:
        return (float(in_tok) * in_rate + float(out_tok) * out_rate) / 1_000_000
    except (TypeError, ValueError):
        return 0.0
