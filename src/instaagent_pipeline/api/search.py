"""Core search logic, independent of the web framework so it can be unit-tested.

Embeds the query with Voyage, runs a pgvector KNN over the 'search' space via the
match_item_embeddings RPC, hydrates the ranked items from paid_ads/ugc_items (+
enrichment fields and transcripts from item_enrichments), applies secondary filters,
and returns unified VideoResult dicts.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import urlsplit

from ..config import Config
from ..embeddings import embed_query, rerank, vector_literal
from ..http_client import HttpClientError
from ..supabase_client import SupabaseClient
from .campaigns import runs_with_products

# running_duration (days the ad has been live, the verified-populated column — NOT the
# legacy running_duration_days) is the paid-ad performance metric, the analog of organic
# virality. Exposed as `days_live` on the result.
PAID_HYDRATE_COLUMNS = (
    "paid_ad_row_id,run_id,name,headline,description,publisher_platform,storage_video_url,"
    "storage_thumb_url,video,thumbnail,image,link_url,running_duration"
)
ORGANIC_HYDRATE_COLUMNS = (
    "id,run_id,handle,user_handle,nickname,source,followers,views,likes,virality_score,"
    "virality_tier,storage_video_url,storage_thumb_url,video_url,cover,date_created"
)

# Safety ceiling for an unbounded (limit=None) search. Results are gated by the
# relevance threshold (config.search_min_similarity), not a fixed count, so this
# only guards against a pathologically large response as the corpus grows.
MAX_RESULTS = 1000


def search_ads(
    config: Config,
    supabase: SupabaseClient,
    *,
    query: str,
    item_type: str | None = None,
    platform: str | None = None,
    run_id: str | None = None,
    min_virality: float | None = None,
    min_views: int | None = None,
    min_days_live: float | None = None,
    min_date: str | None = None,
    languages: list[str] | None = None,
    age_brackets: list[str] | None = None,
    content_formats: list[str] | None = None,
    price_tier: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    # Empty query => browse mode: return all ads (filtered) instead of a vector search.
    if not query.strip():
        pool = MAX_RESULTS if limit is None else min(200, max(limit * 4, 40))
        return _browse_ads(
            supabase,
            item_type=item_type,
            platform=platform,
            run_id=run_id,
            min_virality=min_virality,
            min_views=min_views,
            min_days_live=min_days_live,
            min_date=min_date,
            languages=languages,
            age_brackets=age_brackets,
            content_formats=content_formats,
            price_tier=price_tier,
            limit=limit,
            pool=pool,
        )

    # Recall: embed the query and pull candidates from BOTH embedding spaces with no
    # cosine floor. The reranker — not the cosine score — decides relevance, so recall
    # is deliberately generous.
    vector = embed_query(config, query)
    vector_text = vector_literal(vector)

    candidate_docs: dict[tuple[str, str], str] = {}
    seen_order: list[tuple[str, str]] = []
    for space in ("search", "icp"):
        ranked = supabase.rpc(
            "match_item_embeddings",
            {
                "p_query": vector_text,
                "p_space": space,
                "p_item_type": item_type,
                "p_model": config.embedding_model,
                "p_run_id": run_id,
                "p_limit": config.rerank_candidate_pool,
                "p_min_similarity": 0.0,
            },
        )
        for row in ranked:
            it = row.get("item_type")
            iid = row.get("item_id")
            if not it or not iid:
                continue
            key = (str(it), str(iid))
            text = (row.get("source_text") or "").strip()
            if key not in candidate_docs:
                candidate_docs[key] = text
                seen_order.append(key)
            elif text and text not in candidate_docs[key]:
                # Same item matched in both spaces — give the reranker the union of what
                # each space embedded (content description + audience/tone text).
                candidate_docs[key] = f"{candidate_docs[key]}\n\n{text}"

    if not seen_order:
        return []

    # Rerank with the query (the cross-encoder reads the natural query best). Gate by the
    # calibrated rerank score, which gives an honest variable result count — not a fixed top-N.
    documents = [candidate_docs[key] for key in seen_order]
    reranked = rerank(config, query, documents, top_k=len(documents))

    order: list[tuple[str, str]] = []
    similarity: dict[tuple[str, str], Any] = {}
    for idx, score in reranked:
        if score < config.rerank_min_score:
            continue
        key = seen_order[idx]
        order.append(key)
        similarity[key] = score
    if not order:
        return []

    paid_ids = [iid for it, iid in order if it == "paid_ad"]
    organic_ids = [iid for it, iid in order if it == "ugc_item"]

    with ThreadPoolExecutor(max_workers=4) as ex:
        f_paid = ex.submit(supabase.select_by_ids, "paid_ads", "paid_ad_row_id", paid_ids, PAID_HYDRATE_COLUMNS)
        f_organic = ex.submit(supabase.select_by_ids, "ugc_items", "id", organic_ids, ORGANIC_HYDRATE_COLUMNS)
        f_paid_enr = ex.submit(_enrichments, supabase, "paid_ad", paid_ids)
        f_organic_enr = ex.submit(_enrichments, supabase, "ugc_item", organic_ids)
        paid, organic, paid_enr, organic_enr = f_paid.result(), f_organic.result(), f_paid_enr.result(), f_organic_enr.result()

    return _assemble(
        order, paid, organic, paid_enr, organic_enr, similarity,
        platform=platform, min_virality=min_virality, min_views=min_views,
        min_days_live=min_days_live, min_date=min_date, languages=languages, age_brackets=age_brackets,
        content_formats=content_formats, price_tier=price_tier, limit=limit,
    )


def _browse_ads(
    supabase: SupabaseClient,
    *,
    item_type: str | None,
    platform: str | None,
    run_id: str | None,
    min_virality: float | None,
    min_views: int | None,
    min_days_live: float | None,
    min_date: str | None,
    languages: list[str] | None,
    age_brackets: list[str] | None,
    content_formats: list[str] | None,
    price_tier: str | None,
    limit: int | None,
    pool: int,
) -> list[dict[str, Any]]:
    """Empty-query browse: list ads straight from the source tables (no vector search)."""
    order: list[tuple[str, str]] = []
    paid: dict[str, dict[str, Any]] = {}
    organic: dict[str, dict[str, Any]] = {}
    paid_ids: list[str] = []
    organic_ids: list[str] = []

    if item_type in (None, "paid_ad"):
        params: dict[str, str] = {"select": PAID_HYDRATE_COLUMNS, "limit": str(pool)}
        if run_id:
            params["run_id"] = f"eq.{run_id}"
        for row in supabase.select("paid_ads", params):
            iid = row.get("paid_ad_row_id")
            if not iid:
                continue
            iid = str(iid)
            paid[iid] = row
            paid_ids.append(iid)
            order.append(("paid_ad", iid))

    if item_type in (None, "ugc_item"):
        params = {"select": ORGANIC_HYDRATE_COLUMNS, "limit": str(pool)}
        if run_id:
            params["run_id"] = f"eq.{run_id}"
        for row in supabase.select("ugc_items", params):
            iid = row.get("id")
            if not iid:
                continue
            iid = str(iid)
            organic[iid] = row
            organic_ids.append(iid)
            order.append(("ugc_item", iid))

    with ThreadPoolExecutor(max_workers=2) as ex:
        f_paid_enr = ex.submit(_enrichments, supabase, "paid_ad", paid_ids)
        f_organic_enr = ex.submit(_enrichments, supabase, "ugc_item", organic_ids)
        paid_enr, organic_enr = f_paid_enr.result(), f_organic_enr.result()

    return _assemble(
        order, paid, organic, paid_enr, organic_enr, {},
        platform=platform, min_virality=min_virality, min_views=min_views,
        min_days_live=min_days_live, min_date=min_date, languages=languages, age_brackets=age_brackets,
        content_formats=content_formats, price_tier=price_tier, limit=limit,
    )


def _assemble(
    order: list[tuple[str, str]],
    paid: dict[str, dict[str, Any]],
    organic: dict[str, dict[str, Any]],
    paid_enr: dict[str, dict[str, Any]],
    organic_enr: dict[str, dict[str, Any]],
    similarity: dict[tuple[str, str], Any],
    *,
    platform: str | None,
    min_virality: float | None,
    min_views: int | None,
    min_days_live: float | None,
    min_date: str | None = None,
    languages: list[str] | None = None,
    age_brackets: list[str] | None = None,
    content_formats: list[str] | None = None,
    price_tier: str | None = None,
    limit: int | None,
) -> list[dict[str, Any]]:
    """Hydrate ranked/browsed keys into VideoResult dicts, dedupe by video, apply filters."""
    want_languages = {s.strip().title() for s in languages} if languages else None
    want_brackets = {s.strip().lower() for s in age_brackets} if age_brackets else None
    want_formats = {s.strip().lower() for s in content_formats} if content_formats else None
    want_price = price_tier.strip().lower() if price_tier else None
    cap = MAX_RESULTS if limit is None else limit
    results: list[dict[str, Any]] = []
    seen_videos: set[str] = set()
    for key in order:
        it, iid = key
        if it == "paid_ad":
            row = paid.get(iid)
            enrichment = paid_enr.get(iid)
        else:
            row = organic.get(iid)
            enrichment = organic_enr.get(iid)
        if not row:
            continue
        source_video = row.get("video") if it == "paid_ad" else row.get("video_url")
        # Dedupe on the video *filename*, not the full URL: the same Meta creative is
        # served under different signed URLs and CDN hosts (e.g. fabe1-1 vs lax7-1), so
        # the signed URLs differ while the content-hash filename is identical. Filenames
        # are content-addressed (Meta) or per-record unique (Apify organic), so no false merges.
        video_key = _video_dedupe_key(source_video)
        if video_key:
            if video_key in seen_videos:
                continue
            seen_videos.add(video_key)
        result = _to_video_result(it, row, enrichment, similarity.get(key))
        if platform and (result["platform"] or "").lower() != platform.lower():
            continue
        if min_virality is not None and (result["virality"] is None or result["virality"] < min_virality):
            continue
        if min_views is not None and (result["views"] is None or result["views"] < min_views):
            continue
        # Posted-since filter (organic). date_created is an ISO timestamp, so a date-only
        # bound like "2026-06-15" compares lexicographically against "2026-06-15T..." correctly.
        if min_date and (result.get("date_created") is None or str(result["date_created"]) < min_date):
            continue
        # days_live is paid-only (None for organic), so this filter narrows to paid ads —
        # the longevity analog of the organic-only virality/views filters above.
        if min_days_live is not None and (result.get("days_live") is None or result["days_live"] < min_days_live):
            continue
        # Categorical filters (cross-type). Multi-value (languages, age_brackets) match by
        # overlap; price_tier is exact. Rows lacking the value are dropped when filtered on.
        if want_price is not None and (result.get("price_positioning") or "").lower() != want_price:
            continue
        if want_brackets is not None and not (want_brackets & {b.lower() for b in result.get("age_brackets") or []}):
            continue
        if want_formats is not None and not (want_formats & {f.lower() for f in result.get("content_formats") or []}):
            continue
        if want_languages is not None and not (want_languages & {l.title() for l in result.get("languages") or []}):
            continue
        results.append(result)
        if len(results) >= cap:
            break
    return results


def _video_dedupe_key(url: str | None) -> str | None:
    """The video's filename (path basename), used to collapse the same creative served
    under different signed URLs/CDN hosts. Falls back to the full URL if no basename."""
    if not url:
        return None
    return urlsplit(url).path.rsplit("/", 1)[-1] or url


def list_runs(supabase: SupabaseClient) -> list[dict[str, Any]]:
    out = []
    for run, product in runs_with_products(supabase, "id,name,category"):
        out.append(
            {
                "run_id": str(run.get("id")),
                "status": run.get("status"),
                # campaign_name lives in the run config (set by the campaign wizard); None for
                # runs created via the bare CLI init_run. Lets search filter/label by campaign.
                "campaign_name": (run.get("config") or {}).get("campaign_name"),
                # True for the keyword-free Viral Discovery run, so Search can offer a dedicated
                # "viral formats only" filter without matching on the campaign name.
                "discovery": bool((run.get("config") or {}).get("discovery")),
                "product_name": product.get("name"),
                "category": product.get("category"),
                "target_paid_count": run.get("target_paid_count"),
                "target_ugc_count": run.get("target_ugc_count"),
                "target_tiktok_count": run.get("target_tiktok_count"),
                "created_at": run.get("created_at"),
            }
        )
    return out


_ENRICH_BASE_COLUMNS = (
    "item_id,ai_description,hook,content_format,product_category,video_topic,transcript_text"
)
# Phase 4 columns (migration 018) + content_formats (migration 020). Selected when present;
# the 400-fallback drops them pre-migration so search keeps working.
_ENRICH_FULL_COLUMNS = (
    _ENRICH_BASE_COLUMNS
    + ",target_generation,price_positioning,age_brackets,languages,content_formats"
)


def _enrichments(
    supabase: SupabaseClient,
    item_type: str,
    ids: list[str],
) -> dict[str, dict[str, Any]]:
    if not ids:
        return {}
    params = {
        "item_type": f"eq.{item_type}",
        "item_id": f"in.({','.join(ids)})",
        "limit": str(len(ids)),
    }
    try:
        rows = supabase.select("item_enrichments", {"select": _ENRICH_FULL_COLUMNS, **params})
    except HttpClientError as exc:
        if exc.status != 400:
            raise
        rows = supabase.select("item_enrichments", {"select": _ENRICH_BASE_COLUMNS, **params})
    return {str(r.get("item_id")): r for r in rows if r.get("item_id")}


def _to_video_result(
    item_type: str,
    row: dict[str, Any],
    enrichment: dict[str, Any] | None,
    similarity: Any,
) -> dict[str, Any]:
    enr = enrichment or {}
    ai_description = enr.get("ai_description")
    hook = enr.get("hook")
    content_format = enr.get("content_format")
    product_category = enr.get("product_category")
    video_topic = enr.get("video_topic")
    transcript = enr.get("transcript_text")
    # Phase 4 audience fields (None/[] until migration 018 + enrich-audience populate them).
    # content_formats (migration 020) is the multi-value successor to content_format.
    audience = {
        "target_generation": enr.get("target_generation"),
        "price_positioning": enr.get("price_positioning"),
        "age_brackets": enr.get("age_brackets") or [],
        "languages": enr.get("languages") or [],
        "content_formats": enr.get("content_formats") or [],
    }
    if item_type == "paid_ad":
        return {
            "item_type": "paid_ad",
            "item_id": str(row.get("paid_ad_row_id")),
            "run_id": row.get("run_id"),
            "title": row.get("name") or row.get("headline"),
            "platform": _paid_platform(row.get("publisher_platform")),
            "video_url": row.get("storage_video_url") or row.get("video"),
            "thumb_url": row.get("storage_thumb_url") or row.get("thumbnail") or row.get("image"),
            "original_url": row.get("link_url"),
            "followers": None,
            "views": None,
            "likes": None,
            "virality": None,
            "days_live": row.get("running_duration"),
            **audience,
            "hook": hook,
            "ai_description": ai_description,
            "content_format": content_format,
            "product_category": product_category,
            "video_topic": video_topic,
            "transcript": transcript,
            "similarity": similarity,
        }
    return {
        "item_type": "ugc_item",
        "item_id": str(row.get("id")),
        "run_id": row.get("run_id"),
        "title": row.get("handle") or row.get("user_handle") or row.get("nickname"),
        "platform": row.get("source"),
        "video_url": row.get("storage_video_url") or row.get("video_url"),
        "thumb_url": row.get("storage_thumb_url") or row.get("cover"),
        "original_url": row.get("video_url"),
        "followers": row.get("followers"),
        "views": row.get("views"),
        "likes": row.get("likes"),
        "virality": row.get("virality_score"),
        "date_created": row.get("date_created"),
        "days_live": None,
        **audience,
        "hook": hook,
        "ai_description": ai_description,
        "content_format": content_format,
        "product_category": product_category,
        "video_topic": video_topic,
        "transcript": transcript,
        "similarity": similarity,
    }


def _paid_platform(publisher_platform: Any) -> str:
    if isinstance(publisher_platform, list) and publisher_platform:
        return str(publisher_platform[0]).lower()
    if isinstance(publisher_platform, str) and publisher_platform.strip():
        return publisher_platform.strip().lower()
    return "meta"
