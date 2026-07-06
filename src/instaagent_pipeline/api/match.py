"""Product → viral-trend matching, independent of the web framework so it can be unit-tested.

A three-stage funnel that keeps the LLM judge's payload flat as the trend library grows:
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

from ..ad_enrichment import (
    OPENROUTER_BASE_URL,
    OPENROUTER_CHAT_COMPLETIONS_ENDPOINT,
    parse_enrichment_response,
)
from ..config import Config
from ..embeddings import embed_query, vector_literal
from ..http_client import HttpClientError, request_json
from ..supabase_client import SupabaseClient
from ..trend_classify import TREND_EMBEDDING_SPACE, VIRAL_FORMAT_ITEM_TYPE

# The most formats the LLM judge scores in one call. Vector recall trims to this so judge
# latency/cost stays constant no matter how big the trend library grows.
JUDGE_POOL = 30

_FORMAT_COLUMNS = (
    "id,source_name,source_url,issue_date,format_name,format_description,niche_constraint,"
    "versatility,fit_niches,product_requirements,created_at"
)
# ugc_items fields the cards need (mirrors routes_trends).
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
    response = request_json(
        "POST",
        f"{OPENROUTER_BASE_URL}{OPENROUTER_CHAT_COMPLETIONS_ENDPOINT}",
        headers={"Authorization": f"Bearer {config.openrouter_api_key}"},
        body={
            "model": config.openrouter_model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "product_matches", "strict": True, "schema": MATCH_SCHEMA},
            },
            "max_tokens": min(4000, 200 + 80 * len(candidates)),
        },
        timeout=timeout,
    )
    analysis = parse_enrichment_response(response.body)
    matches = analysis.get("matches") if isinstance(analysis, dict) else None
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
    """Example videos per format (ugc_items, source='trend'), same shape as routes_trends."""
    if not format_ids:
        return {}
    rows = supabase.select(
        "ugc_items",
        {
            "select": _VIDEO_COLUMNS,
            "format_id": f"in.({','.join(format_ids)})",
            "order": "views.desc.nullslast",
            "limit": "2000",
        },
    )
    videos_by_format: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        metrics = row.get("source_metrics") if isinstance(row.get("source_metrics"), dict) else {}
        videos_by_format.setdefault(str(row.get("format_id")), []).append(
            {
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
        )
    return videos_by_format
