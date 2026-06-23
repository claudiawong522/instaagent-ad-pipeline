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
from ..embeddings import embed_query, vector_literal
from ..supabase_client import SupabaseClient

PAID_HYDRATE_COLUMNS = (
    "paid_ad_row_id,run_id,name,headline,description,publisher_platform,storage_video_url,"
    "storage_thumb_url,video,thumbnail,image,link_url"
)
UGC_HYDRATE_COLUMNS = (
    "id,run_id,handle,user_handle,nickname,source,followers,views,likes,virality_score,"
    "virality_tier,storage_video_url,storage_thumb_url,video_url,cover"
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
    limit: int | None = 20,
) -> list[dict[str, Any]]:
    # limit=None means "every match" (capped only by MAX_RESULTS). With a limit,
    # over-fetch so secondary (platform/virality/views) filters still leave `limit` rows.
    pool = MAX_RESULTS if limit is None else min(200, max(limit * 4, 40))

    # Empty query => browse mode: return all ads (filtered) instead of a vector search.
    if not query.strip():
        return _browse_ads(
            supabase,
            item_type=item_type,
            platform=platform,
            run_id=run_id,
            min_virality=min_virality,
            min_views=min_views,
            limit=limit,
            pool=pool,
        )

    vector = embed_query(config, query)
    ranked = supabase.rpc(
        "match_item_embeddings",
        {
            "p_query": vector_literal(vector),
            "p_space": "search",
            "p_item_type": item_type,
            "p_model": config.embedding_model,
            "p_run_id": run_id,
            "p_limit": pool,
            "p_min_similarity": config.search_min_similarity,
        },
    )

    order: list[tuple[str, str]] = []
    similarity: dict[tuple[str, str], Any] = {}
    paid_ids: list[str] = []
    ugc_ids: list[str] = []
    for row in ranked:
        it = row.get("item_type")
        iid = row.get("item_id")
        if not it or not iid:
            continue
        key = (str(it), str(iid))
        if key in similarity:
            continue
        similarity[key] = row.get("similarity")
        order.append(key)
        (paid_ids if it == "paid_ad" else ugc_ids).append(str(iid))

    with ThreadPoolExecutor(max_workers=4) as ex:
        f_paid = ex.submit(_hydrate, supabase, "paid_ads", "paid_ad_row_id", paid_ids, PAID_HYDRATE_COLUMNS)
        f_ugc = ex.submit(_hydrate, supabase, "ugc_items", "id", ugc_ids, UGC_HYDRATE_COLUMNS)
        f_paid_enr = ex.submit(_enrichments, supabase, "paid_ad", paid_ids)
        f_ugc_enr = ex.submit(_enrichments, supabase, "ugc_item", ugc_ids)
        paid, ugc, paid_enr, ugc_enr = f_paid.result(), f_ugc.result(), f_paid_enr.result(), f_ugc_enr.result()

    return _assemble(
        order, paid, ugc, paid_enr, ugc_enr, similarity,
        platform=platform, min_virality=min_virality, min_views=min_views, limit=limit,
    )


def _browse_ads(
    supabase: SupabaseClient,
    *,
    item_type: str | None,
    platform: str | None,
    run_id: str | None,
    min_virality: float | None,
    min_views: int | None,
    limit: int | None,
    pool: int,
) -> list[dict[str, Any]]:
    """Empty-query browse: list ads straight from the source tables (no vector search)."""
    order: list[tuple[str, str]] = []
    paid: dict[str, dict[str, Any]] = {}
    ugc: dict[str, dict[str, Any]] = {}
    paid_ids: list[str] = []
    ugc_ids: list[str] = []

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
        params = {"select": UGC_HYDRATE_COLUMNS, "limit": str(pool)}
        if run_id:
            params["run_id"] = f"eq.{run_id}"
        for row in supabase.select("ugc_items", params):
            iid = row.get("id")
            if not iid:
                continue
            iid = str(iid)
            ugc[iid] = row
            ugc_ids.append(iid)
            order.append(("ugc_item", iid))

    with ThreadPoolExecutor(max_workers=2) as ex:
        f_paid_enr = ex.submit(_enrichments, supabase, "paid_ad", paid_ids)
        f_ugc_enr = ex.submit(_enrichments, supabase, "ugc_item", ugc_ids)
        paid_enr, ugc_enr = f_paid_enr.result(), f_ugc_enr.result()

    return _assemble(
        order, paid, ugc, paid_enr, ugc_enr, {},
        platform=platform, min_virality=min_virality, min_views=min_views, limit=limit,
    )


def _assemble(
    order: list[tuple[str, str]],
    paid: dict[str, dict[str, Any]],
    ugc: dict[str, dict[str, Any]],
    paid_enr: dict[str, dict[str, Any]],
    ugc_enr: dict[str, dict[str, Any]],
    similarity: dict[tuple[str, str], Any],
    *,
    platform: str | None,
    min_virality: float | None,
    min_views: int | None,
    limit: int | None,
) -> list[dict[str, Any]]:
    """Hydrate ranked/browsed keys into VideoResult dicts, dedupe by video, apply filters."""
    cap = MAX_RESULTS if limit is None else limit
    results: list[dict[str, Any]] = []
    seen_videos: set[str] = set()
    for key in order:
        it, iid = key
        if it == "paid_ad":
            row = paid.get(iid)
            enrichment = paid_enr.get(iid)
        else:
            row = ugc.get(iid)
            enrichment = ugc_enr.get(iid)
        if not row:
            continue
        source_video = row.get("video") if it == "paid_ad" else row.get("video_url")
        # Dedupe on the video *filename*, not the full URL: the same Meta creative is
        # served under different signed URLs and CDN hosts (e.g. fabe1-1 vs lax7-1), so
        # the signed URLs differ while the content-hash filename is identical. Filenames
        # are content-addressed (Meta) or per-record unique (Apify UGC), so no false merges.
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
    runs = supabase.select(
        "pipeline_runs",
        {"select": "id,status,target_paid_count,target_ugc_count,created_at,product_id", "order": "created_at.desc"},
    )
    product_ids = [str(r["product_id"]) for r in runs if r.get("product_id")]
    products = _hydrate(supabase, "products", "id", product_ids, "id,name,category")
    out = []
    for run in runs:
        product = products.get(str(run.get("product_id")))
        out.append(
            {
                "run_id": str(run.get("id")),
                "status": run.get("status"),
                "product_name": (product or {}).get("name"),
                "category": (product or {}).get("category"),
                "target_paid_count": run.get("target_paid_count"),
                "target_ugc_count": run.get("target_ugc_count"),
                "created_at": run.get("created_at"),
            }
        )
    return out


def get_item(config: Config, supabase: SupabaseClient, item_type: str, item_id: str) -> dict[str, Any] | None:
    if item_type == "paid_ad":
        rows = _hydrate(supabase, "paid_ads", "paid_ad_row_id", [item_id], PAID_HYDRATE_COLUMNS)
        enrichment = _enrichments(supabase, "paid_ad", [item_id]).get(item_id)
    elif item_type == "ugc_item":
        rows = _hydrate(supabase, "ugc_items", "id", [item_id], UGC_HYDRATE_COLUMNS)
        enrichment = _enrichments(supabase, "ugc_item", [item_id]).get(item_id)
    else:
        return None
    row = rows.get(item_id)
    if not row:
        return None
    return _to_video_result(item_type, row, enrichment, None)


def _hydrate(
    supabase: SupabaseClient,
    table: str,
    id_column: str,
    ids: list[str],
    columns: str,
) -> dict[str, dict[str, Any]]:
    if not ids:
        return {}
    rows = supabase.select(
        table,
        {"select": columns, id_column: f"in.({','.join(ids)})", "limit": str(len(ids))},
    )
    return {str(row.get(id_column)): row for row in rows if row.get(id_column)}


def _enrichments(
    supabase: SupabaseClient,
    item_type: str,
    ids: list[str],
) -> dict[str, dict[str, Any]]:
    if not ids:
        return {}
    rows = supabase.select(
        "item_enrichments",
        {
            "select": "item_id,ai_description,hook,content_format,product_category,video_topic,transcript_text",
            "item_type": f"eq.{item_type}",
            "item_id": f"in.({','.join(ids)})",
            "limit": str(len(ids)),
        },
    )
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
