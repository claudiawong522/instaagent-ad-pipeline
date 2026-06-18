"""Core search logic, independent of the web framework so it can be unit-tested.

Embeds the query with Voyage, runs a pgvector KNN over the 'search' space via the
match_item_embeddings RPC, hydrates the ranked items from paid_ads/ugc_items (+
transcripts), applies secondary filters, and returns unified VideoResult dicts.
"""

from __future__ import annotations

from typing import Any

from ..config import Config
from ..embeddings import embed_query, vector_literal
from ..supabase_client import SupabaseClient

PAID_HYDRATE_COLUMNS = (
    "paid_ad_row_id,run_id,name,headline,description,ai_description,hook,content_format,"
    "product_category,video_topic,publisher_platform,storage_video_url,storage_thumb_url,"
    "video,thumbnail,image,link_url"
)
UGC_HYDRATE_COLUMNS = (
    "id,run_id,handle,user_handle,nickname,ai_description,hook,content_format,product_category,"
    "video_topic,source,followers,views,likes,virality_score,virality_tier,storage_video_url,"
    "storage_thumb_url,video_url,cover"
)


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
    limit: int = 20,
) -> list[dict[str, Any]]:
    vector = embed_query(config, query)
    # Over-fetch so secondary (platform/virality/views) filters still leave `limit` rows.
    pool = min(200, max(limit * 4, 40))
    ranked = supabase.rpc(
        "match_item_embeddings",
        {
            "p_query": vector_literal(vector),
            "p_space": "search",
            "p_item_type": item_type,
            "p_model": config.embedding_model,
            "p_run_id": run_id,
            "p_limit": pool,
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

    paid = _hydrate(supabase, "paid_ads", "paid_ad_row_id", paid_ids, PAID_HYDRATE_COLUMNS)
    ugc = _hydrate(supabase, "ugc_items", "id", ugc_ids, UGC_HYDRATE_COLUMNS)
    paid_tx = _transcripts(supabase, "paid_ad_transcripts", "paid_ad_row_id", paid_ids)
    ugc_tx = _transcripts(supabase, "ugc_transcripts", "ugc_item_id", ugc_ids)

    results: list[dict[str, Any]] = []
    for key in order:
        it, iid = key
        if it == "paid_ad":
            row = paid.get(iid)
            transcript = paid_tx.get(iid)
        else:
            row = ugc.get(iid)
            transcript = ugc_tx.get(iid)
        if not row:
            continue
        result = _to_video_result(it, row, transcript, similarity.get(key))
        if platform and (result["platform"] or "").lower() != platform.lower():
            continue
        if min_virality is not None and (result["virality"] is None or result["virality"] < min_virality):
            continue
        if min_views is not None and (result["views"] is None or result["views"] < min_views):
            continue
        results.append(result)
        if len(results) >= limit:
            break
    return results


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
        transcript = _transcripts(supabase, "paid_ad_transcripts", "paid_ad_row_id", [item_id]).get(item_id)
    elif item_type == "ugc_item":
        rows = _hydrate(supabase, "ugc_items", "id", [item_id], UGC_HYDRATE_COLUMNS)
        transcript = _transcripts(supabase, "ugc_transcripts", "ugc_item_id", [item_id]).get(item_id)
    else:
        return None
    row = rows.get(item_id)
    if not row:
        return None
    return _to_video_result(item_type, row, transcript, None)


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


def _transcripts(
    supabase: SupabaseClient,
    table: str,
    id_column: str,
    ids: list[str],
) -> dict[str, str]:
    if not ids:
        return {}
    rows = supabase.select(
        table,
        {"select": f"{id_column},transcript_text", id_column: f"in.({','.join(ids)})", "limit": "10000"},
    )
    out: dict[str, str] = {}
    for row in rows:
        key = str(row.get(id_column))
        text = row.get("transcript_text")
        if key and text and key not in out:
            out[key] = text
    return out


def _to_video_result(
    item_type: str,
    row: dict[str, Any],
    transcript: str | None,
    similarity: Any,
) -> dict[str, Any]:
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
            "hook": row.get("hook"),
            "ai_description": row.get("ai_description"),
            "content_format": row.get("content_format"),
            "product_category": row.get("product_category"),
            "video_topic": row.get("video_topic"),
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
        "hook": row.get("hook"),
        "ai_description": row.get("ai_description"),
        "content_format": row.get("content_format"),
        "product_category": row.get("product_category"),
        "video_topic": row.get("video_topic"),
        "transcript": transcript,
        "similarity": similarity,
    }


def _paid_platform(publisher_platform: Any) -> str:
    if isinstance(publisher_platform, list) and publisher_platform:
        return str(publisher_platform[0]).lower()
    if isinstance(publisher_platform, str) and publisher_platform.strip():
        return publisher_platform.strip().lower()
    return "meta"
