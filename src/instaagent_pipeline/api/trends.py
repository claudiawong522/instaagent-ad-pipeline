"""Trends service: viral-format listing + product → trend matching, framework-independent.

Listing (GET /trends/formats) returns each viral_formats row with its example videos
(re-scraped organic_items, source='trend') grouped under it, ranked by aggregate live views.

Matching (POST /trends/match) is a three-stage funnel that keeps the LLM judge's payload
flat as the trend library grows:
  1. Candidate set — all formats when few; else vector recall (embed the product, KNN over the
     'trend' space) UNIONed with every `universal` format. Universals are force-included because
     a "works for anything" format embeds poorly against a specific product, so cosine alone
     would wrongly drop the most reusable trends.
  2. LLM judge — one OpenRouter call scores each candidate against the product (great/workable/no
     + 0-100 + a "how to use it for THIS product" idea). It only ever sees ~JUDGE_POOL formats.
  3. Assemble — join scores onto the formats, hydrate example videos, rank by score. `no` fits
     ride along at the bottom so "fits none" stays visible.
"""

from __future__ import annotations

from typing import Any

from ..config import Config
from ..embeddings import embed_query, vector_literal
from ..http_client import HttpClientError
from ..openrouter import openrouter_json_call
from ..supabase_client import SupabaseClient
from ..trend_classify import TREND_EMBEDDING_SPACE, VIRAL_FORMAT_ITEM_TYPE

# The most formats the LLM judge scores in one call. Vector recall trims to this so judge
# latency/cost stays constant no matter how big the trend library grows.
JUDGE_POOL = 30

_FORMAT_COLUMNS = (
    "id,source_name,source_url,issue_date,format_name,format_description,niche_constraint,"
    "versatility,fit_niches,product_requirements,created_at"
)
# organic_items fields the trend cards need (storage_* are filled by enrichment's MP4 persist).
_VIDEO_COLUMNS = (
    "id,format_id,storage_video_url,storage_thumb_url,video_url,cover,views,likes,"
    "virality_score,handle,description,enrichment_status,source_metrics,date_created"
)

MATCH_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "matches": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "format_id": {"type": "string"},
                    "fit": {"type": "string", "enum": ["great", "workable", "no"]},
                    "score": {"type": "integer"},
                    "idea": {"type": "string"},
                },
                "required": ["format_id", "fit", "score", "idea"],
            },
        }
    },
    "required": ["matches"],
}

MATCH_PROMPT = (
    "You match a marketer's PRODUCT to viral video FORMATS they could remake with it. For EACH "
    "format below, decide how well this product could recreate it, and give one concrete idea "
    "for shooting it with THIS product.\n\n"
    "Return JSON: a list of {{format_id, fit, score, idea}} where\n"
    "- fit: \"great\" | \"workable\" | \"no\"\n"
    "- score: 0-100 — how well this product suits the format\n"
    "- idea: one sentence on how to use THIS product in THIS format; \"\" when fit is \"no\".\n\n"
    "Be honest — many formats will be \"no\". Never force a fit.\n\n"
    "PRODUCT: {product}\n\n"
    "FORMATS:\n{formats}"
)


def _video_out(row: dict[str, Any]) -> dict[str, Any]:
    """One example-video card, shared by the listing and match endpoints."""
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


def list_trend_scrape_dates(supabase: SupabaseClient, *, source_name: str | None = None) -> list[str]:
    """Distinct scrape dates (UTC, YYYY-MM-DD) of viral_formats rows, newest-first."""
    params: dict[str, Any] = {"select": "created_at", "order": "created_at.desc"}
    if source_name:
        params["source_name"] = f"eq.{source_name}"
    rows = supabase.select("viral_formats", params)
    seen: dict[str, None] = {}  # dict preserves the created_at.desc order while de-duping
    for row in rows:
        created = row.get("created_at")
        if created:
            seen.setdefault(str(created)[:10], None)
    return list(seen.keys())


def list_trend_formats(
    supabase: SupabaseClient,
    *,
    source_name: str | None = None,
    q: str | None = None,
    min_views: int = 0,
    posted_after: str | None = None,
    scraped_on: str | None = None,
    all_months: bool = False,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Each viral format with its example videos grouped under it, most-viewed first."""
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
        return []

    if scraped_on:
        # Exact scrape-batch view: keep only formats scraped on this date, and skip the
        # month collapse so an older batch stays visible.
        formats = [f for f in formats if str(f.get("created_at"))[:10] == scraped_on]
    # Default to this month's trends only: per dated source, keep its most recent issue_date
    # (the current monthly report) so last month's trends drop off the board once the new report
    # is ingested — without deleting them (all_months=true still returns every month). Undated
    # (weekly) sources have no issue_date and are always kept.
    elif not all_months:
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
        rows = supabase.select("organic_items", video_params)
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
    return out


def match_product(
    config: Config,
    supabase: SupabaseClient,
    *,
    product: str,
    limit: int = JUDGE_POOL,
    timeout: int = 60,
) -> list[dict[str, Any]]:
    product = (product or "").strip()
    if not product:
        return []
    if not config.openrouter_api_key:
        raise RuntimeError("OPENROUTER_API_KEY is required to match a product to trends.")

    formats = supabase.select(
        "viral_formats",
        {"select": _FORMAT_COLUMNS, "order": "created_at.desc", "limit": "2000"},
    )
    by_id: dict[str, dict[str, Any]] = {str(f["id"]): f for f in formats if f.get("id")}
    if not by_id:
        return []

    candidate_ids = _candidates(config, supabase, product, by_id)
    if not candidate_ids:
        return []

    verdicts = _judge(config, product, [by_id[i] for i in candidate_ids], timeout=timeout)
    videos_by_format = _hydrate_videos(supabase, candidate_ids)

    out: list[dict[str, Any]] = []
    for fid in candidate_ids:
        fmt = by_id[fid]
        verdict = verdicts.get(fid) or {"fit": "no", "score": 0, "idea": ""}
        videos = videos_by_format.get(fid, [])
        out.append(
            {
                "id": fmt["id"],
                "source_name": fmt.get("source_name"),
                "source_url": fmt.get("source_url"),
                "issue_date": fmt.get("issue_date"),
                "format_name": fmt.get("format_name"),
                "format_description": fmt.get("format_description"),
                "niche_constraint": fmt.get("niche_constraint"),
                "versatility": fmt.get("versatility"),
                "fit_niches": fmt.get("fit_niches") or [],
                "product_requirements": fmt.get("product_requirements") or [],
                "fit": verdict["fit"],
                "score": verdict["score"],
                "idea": verdict["idea"],
                "video_count": len(videos),
                "total_views": sum(v["views"] or 0 for v in videos),
                "videos": videos,
            }
        )

    # Rank by fit score (the judge's calibrated 0-100); "no" fits fall to the bottom.
    out.sort(key=lambda f: f["score"], reverse=True)
    return out[: max(1, limit)]


# Slice of the judge pool reserved for broadly-reusable `universal` formats. They get a
# guaranteed minority because "works for anything" embeds far from any specific product, so
# vector recall can miss genuinely-reusable universals — but relevance (recall) must still
# fill the majority, or a beauty product would never see a beauty-niche format.
UNIVERSAL_RESERVE = JUDGE_POOL // 3


def _candidates(
    config: Config,
    supabase: SupabaseClient,
    product: str,
    by_id: dict[str, dict[str, Any]],
) -> list[str]:
    """The formats the judge will score. Few → all of them (no embedding call). Many → a blend:
    a reserved slice of `universal` formats, the rest filled by vector-recalled relevance,
    backfilled from universals/all if recall came up short. Capped at JUDGE_POOL."""
    all_ids = list(by_id.keys())
    if len(all_ids) <= JUDGE_POOL:
        return all_ids

    universal_ids = [fid for fid, f in by_id.items() if (f.get("versatility") == "universal")]
    recalled_ids = _recall(config, supabase, product) if config.voyage_api_key else []

    ordered: list[str] = []
    seen: set[str] = set()

    def take(ids: list[str], cap: int) -> None:
        for fid in ids:
            if len(ordered) >= cap:
                return
            if fid in by_id and fid not in seen:
                seen.add(fid)
                ordered.append(fid)

    take(universal_ids, min(len(universal_ids), UNIVERSAL_RESERVE))  # reserved universal slice
    take(recalled_ids, JUDGE_POOL)  # relevance fills the majority
    take(universal_ids, JUDGE_POOL)  # backfill if recall was short (e.g. no Voyage key)
    take(all_ids, JUDGE_POOL)
    return ordered


def _recall(config: Config, supabase: SupabaseClient, product: str) -> list[str]:
    """Vector recall: embed the product as a query, KNN over the 'trend' space. Best-effort —
    any Voyage/RPC failure returns [] so matching falls back to the raw format order."""
    try:
        vector = embed_query(config, f"Product: {product}")
        rows = supabase.rpc(
            "match_item_embeddings",
            {
                "p_query": vector_literal(vector),
                "p_space": TREND_EMBEDDING_SPACE,
                "p_item_type": VIRAL_FORMAT_ITEM_TYPE,
                "p_model": config.embedding_model,
                "p_run_id": None,
                "p_limit": JUDGE_POOL,
                "p_min_similarity": 0.0,
            },
        )
    except (HttpClientError, RuntimeError):
        return []
    return [str(r["item_id"]) for r in rows if r.get("item_id")]


def _judge(
    config: Config,
    product: str,
    candidates: list[dict[str, Any]],
    *,
    timeout: int,
) -> dict[str, dict[str, Any]]:
    """One OpenRouter call scoring every candidate. Returns format_id → {fit, score, idea}."""
    blocks: list[str] = []
    for f in candidates:
        reqs = ", ".join(f.get("product_requirements") or []) or "none"
        niches = ", ".join(f.get("fit_niches") or []) or "any"
        blocks.append(
            f"[id={f['id']}] {f.get('format_name') or 'untitled'}\n"
            f"  needs: {reqs}\n"
            f"  suits: {niches} ({f.get('versatility') or 'broad'})\n"
            f"  about: {(f.get('format_description') or '').strip() or '(none)'}"
        )
    prompt = MATCH_PROMPT.format(product=product, formats="\n".join(blocks))
    analysis = openrouter_json_call(
        config,
        prompt=prompt,
        schema=MATCH_SCHEMA,
        schema_name="product_matches",
        max_tokens=min(4000, 200 + 80 * len(candidates)),
        timeout=timeout,
        empty_error="OpenRouter returned no matches array.",
    )
    matches = analysis.get("matches")
    if not isinstance(matches, list):
        raise RuntimeError("OpenRouter returned no matches array.")
    verdicts: dict[str, dict[str, Any]] = {}
    for m in matches:
        if not isinstance(m, dict):
            continue
        fid = str(m.get("format_id") or "").strip()
        if not fid:
            continue
        score = m.get("score")
        verdicts[fid] = {
            "fit": m.get("fit") if m.get("fit") in ("great", "workable", "no") else "no",
            "score": max(0, min(100, int(score))) if isinstance(score, (int, float)) else 0,
            "idea": (m.get("idea") or "").strip(),
        }
    return verdicts


def _hydrate_videos(supabase: SupabaseClient, format_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    """Example videos per format (organic_items, source='trend'), same card shape as the listing."""
    if not format_ids:
        return {}
    rows = supabase.select(
        "organic_items",
        {
            "select": _VIDEO_COLUMNS,
            "format_id": f"in.({','.join(format_ids)})",
            "order": "views.desc.nullslast",
            "limit": "2000",
        },
    )
    videos_by_format: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        videos_by_format.setdefault(str(row.get("format_id")), []).append(_video_out(row))
    return videos_by_format
