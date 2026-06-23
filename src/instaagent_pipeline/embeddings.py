from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import json
from typing import Any, Callable

from .config import Config
from .http_client import HttpClientError, request_json
from .ingestion import complete_query, log_api_usage, log_failed_query, start_query
from .supabase_client import SupabaseClient


VOYAGE_PROVIDER = "voyage"
VOYAGE_BASE_URL = "https://api.voyageai.com"
VOYAGE_EMBEDDINGS_ENDPOINT = "/v1/embeddings"
# Voyage accepts up to 1000 inputs per request; 128 keeps request bodies small.
EMBEDDING_BATCH_SIZE = 128

EMBEDDING_SPACES = ("icp", "search")
SEARCH_SPACE = "search"
ALL_SPACES = ("icp", "search")

# Columns the space builders read, selected from item_enrichments. The icp builder
# reads persona + target_demographic; the search builder reads ai_description, the
# SEARCH_TAG_FIELDS tag block, and the full transcript_text. item_id is the polymorphic
# key (= paid_ads.paid_ad_row_id or ugc_items.id).
ENRICHMENT_SELECT_COLUMNS = (
    "item_id,persona,target_demographic,ai_description,content_format,main_category,"
    "content_category,product_category,video_topic,niches,hook,setting,primary_emotion,"
    "brand_mentioned,transcript_text"
)


@dataclass
class EmbeddingCandidate:
    item_type: str
    item_id: str
    space: str
    source_text: str


@dataclass
class EmbedResult:
    candidates: int = 0
    attempted: int = 0
    written: int = 0
    skipped_existing: int = 0
    skipped_no_text: int = 0
    failed: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)


def embed_items(
    *,
    config: Config,
    supabase: SupabaseClient | None,
    run_id: str,
    source: str = "all",
    spaces: tuple[str, ...] | None = None,
    limit: int = 1000,
    dry_run: bool = False,
    model: str | None = None,
    input_json: Path | None = None,
    timeout: int = 120,
) -> EmbedResult:
    if supabase is None:
        raise RuntimeError("Supabase credentials are required to load embedding candidates.")
    if limit < 1:
        raise ValueError("--limit must be greater than 0.")
    if source not in {"paid", "ugc", "all"}:
        raise ValueError("--source must be one of paid, ugc, all.")
    target_spaces = spaces or EMBEDDING_SPACES
    unknown = [space for space in target_spaces if space not in SPACE_TEXT_BUILDERS]
    if unknown:
        raise ValueError(f"Unknown embedding space(s): {', '.join(unknown)}.")

    embedding_model = model or config.embedding_model
    existing = existing_embedding_keys(supabase, run_id=run_id, embedding_model=embedding_model)

    result = EmbedResult()
    candidates: list[EmbeddingCandidate] = []
    if source in {"paid", "all"}:
        rows = supabase.select(
            "item_enrichments",
            {
                "select": ENRICHMENT_SELECT_COLUMNS,
                "run_id": f"eq.{run_id}",
                "item_type": "eq.paid_ad",
                "order": "created_at.asc",
                "limit": str(limit),
            },
        )
        collect_candidates(rows, item_type="paid_ad", id_column="item_id", spaces=target_spaces, existing=existing, result=result, out=candidates)
    if source in {"ugc", "all"}:
        rows = supabase.select(
            "item_enrichments",
            {
                "select": ENRICHMENT_SELECT_COLUMNS,
                "run_id": f"eq.{run_id}",
                "item_type": "eq.ugc_item",
                "order": "created_at.asc",
                "limit": str(limit),
            },
        )
        collect_candidates(rows, item_type="ugc_item", id_column="item_id", spaces=target_spaces, existing=existing, result=result, out=candidates)

    result.candidates = len(candidates)
    if dry_run:
        result.details = [
            {
                "item_type": candidate.item_type,
                "item_id": candidate.item_id,
                "space": candidate.space,
                "source_text": candidate.source_text,
                "action": "would_embed",
            }
            for candidate in candidates
        ]
        return result

    if not config.voyage_api_key and input_json is None:
        raise RuntimeError("VOYAGE_API_KEY is required unless --input-json is used.")

    for batch in batched(candidates, EMBEDDING_BATCH_SIZE):
        result.attempted += len(batch)
        try:
            written = embed_batch(
                config=config,
                supabase=supabase,
                run_id=run_id,
                batch=batch,
                embedding_model=embedding_model,
                input_json=input_json,
                timeout=timeout,
            )
        except (HttpClientError, RuntimeError) as exc:
            result.failed += len(batch)
            result.details.append({"status": "failed", "batch_size": len(batch), "error": str(exc)})
            continue
        result.written += written

    return result


def collect_candidates(
    rows: list[dict[str, Any]],
    *,
    item_type: str,
    id_column: str,
    spaces: tuple[str, ...],
    existing: set[tuple[str, str, str]],
    result: EmbedResult,
    out: list[EmbeddingCandidate],
) -> None:
    for row in rows:
        item_id = str(row.get(id_column) or "")
        if not item_id:
            continue
        for space in spaces:
            if (item_type, item_id, space) in existing:
                result.skipped_existing += 1
                continue
            text = SPACE_TEXT_BUILDERS[space](row)
            if text is None:
                result.skipped_no_text += 1
                continue
            out.append(
                EmbeddingCandidate(
                    item_type=item_type,
                    item_id=item_id,
                    space=space,
                    source_text=text,
                )
            )


def existing_embedding_keys(
    supabase: SupabaseClient,
    *,
    run_id: str,
    embedding_model: str,
) -> set[tuple[str, str, str]]:
    try:
        rows = supabase.select(
            "item_embeddings",
            {
                "select": "item_type,item_id,space",
                "run_id": f"eq.{run_id}",
                "embedding_model": f"eq.{embedding_model}",
                "limit": "100000",
            },
        )
    except HttpClientError as exc:
        if exc.status == 404:
            raise RuntimeError(
                "item_embeddings table not found. Run supabase/migrations/013_item_embeddings.sql "
                "in the Supabase SQL editor first."
            ) from exc
        raise
    return {
        (str(row.get("item_type")), str(row.get("item_id")), str(row.get("space")))
        for row in rows
    }


def embed_batch(
    *,
    config: Config,
    supabase: SupabaseClient,
    run_id: str,
    batch: list[EmbeddingCandidate],
    embedding_model: str,
    input_json: Path | None,
    timeout: int,
) -> int:
    endpoint = VOYAGE_EMBEDDINGS_ENDPOINT
    provider = f"{VOYAGE_PROVIDER}:{embedding_model}"
    request_params = {
        "model": embedding_model,
        "input_count": len(batch),
        "spaces": sorted({candidate.space for candidate in batch}),
    }
    source_query_id = start_query(
        supabase=supabase,
        dry_run=False,
        run_id=run_id,
        provider=provider,
        endpoint=endpoint,
        method="POST",
        request_params=request_params,
    )
    response_headers: dict[str, str] = {}
    response_status: int | None = None
    try:
        if input_json:
            body = json.loads(input_json.read_text())
        else:
            response = request_json(
                "POST",
                f"{VOYAGE_BASE_URL}{endpoint}",
                headers={"Authorization": f"Bearer {config.voyage_api_key}"},
                body={
                    "input": [candidate.source_text for candidate in batch],
                    "model": embedding_model,
                    "input_type": "document",
                },
                timeout=timeout,
            )
            body = response.body
            response_headers = response.headers
            response_status = response.status

        embeddings = parse_voyage_response(body, expected_count=len(batch))
        log_api_usage(
            supabase=supabase,
            dry_run=False,
            run_id=run_id,
            provider=provider,
            endpoint=endpoint,
            status=response_status,
            response_count=len(embeddings),
            headers=response_headers,
            metadata={"model": embedding_model, "usage": voyage_usage(body)},
        )
        complete_query(
            supabase=supabase,
            dry_run=False,
            source_query_id=source_query_id,
            response_count=len(embeddings),
            http_status=response_status,
        )
    except (HttpClientError, RuntimeError) as exc:
        if isinstance(exc, HttpClientError) and response_status is None:
            log_api_usage(
                supabase=supabase,
                dry_run=False,
                run_id=run_id,
                provider=provider,
                endpoint=endpoint,
                status=exc.status,
                response_count=None,
                headers={},
                metadata={"model": embedding_model},
            )
        log_failed_query(
            supabase=supabase,
            dry_run=False,
            run_id=run_id,
            provider=provider,
            endpoint=endpoint,
            method="POST",
            request_params=request_params,
            source_query_id=source_query_id,
            http_status=getattr(exc, "status", None),
            error_message=str(exc),
        )
        raise

    payload = [
        {
            "run_id": run_id,
            "item_type": candidate.item_type,
            "item_id": candidate.item_id,
            "space": candidate.space,
            "embedding_model": embedding_model,
            "source_text": candidate.source_text,
            "embedding": vector_literal(vector),
        }
        for candidate, vector in zip(batch, embeddings)
    ]
    supabase.upsert("item_embeddings", payload, "item_type,item_id,space,embedding_model")
    return len(payload)


def parse_voyage_response(body: Any, *, expected_count: int) -> list[list[float]]:
    if not isinstance(body, dict) or not isinstance(body.get("data"), list):
        raise RuntimeError("Voyage response is missing the data array.")
    entries = [entry for entry in body["data"] if isinstance(entry, dict)]
    entries.sort(key=lambda entry: int(entry.get("index") or 0))
    embeddings: list[list[float]] = []
    for entry in entries:
        vector = entry.get("embedding")
        if not isinstance(vector, list) or not vector:
            raise RuntimeError("Voyage response contains an entry without an embedding.")
        embeddings.append([float(value) for value in vector])
    if len(embeddings) != expected_count:
        raise RuntimeError(
            f"Voyage returned {len(embeddings)} embeddings for {expected_count} inputs."
        )
    return embeddings


def voyage_usage(body: Any) -> dict[str, Any]:
    if isinstance(body, dict) and isinstance(body.get("usage"), dict):
        return body["usage"]
    return {}


def vector_literal(vector: list[float]) -> str:
    # pgvector's text input format, accepted by PostgREST for vector columns.
    return "[" + ",".join(repr(float(value)) for value in vector) + "]"


def batched(items: list[EmbeddingCandidate], size: int) -> list[list[EmbeddingCandidate]]:
    return [items[start : start + size] for start in range(0, len(items), size)]


def build_icp_text(row: dict[str, Any]) -> str | None:
    parts = [flatten_jsonish(row.get("persona")), clean_text(row.get("target_demographic"))]
    text = "; ".join(part for part in parts if part)
    return text or None


# The search space embeds the rich vision-generated ai_description plus a compact
# labeled tag block of the highest-value searchable fields, so the exact words users
# type (ASMR, before/after, cleanser) appear in the embedded text. The full transcript
# text is appended after the tag block (no truncation) so spoken-word queries match.
# Field order is fixed so cosine distances stay comparable.
SEARCH_TAG_FIELDS = (
    ("format", "content_format"),
    ("category", "main_category"),
    ("subcategory", "content_category"),
    ("product", "product_category"),
    ("topic", "video_topic"),
    ("niches", "niches"),
    ("hook", "hook"),
    ("setting", "setting"),
    ("emotion", "primary_emotion"),
    ("brands", "brand_mentioned"),
)


def build_search_text(row: dict[str, Any]) -> str | None:
    description = clean_text(row.get("ai_description"))
    if not description:
        return None
    tags = []
    for label, column in SEARCH_TAG_FIELDS:
        value = flatten_jsonish(row.get(column))
        if value:
            tags.append(f"{label}: {value}")
    text = description
    if tags:
        text = f"{text}\n\n{'; '.join(tags)}"
    transcript = clean_text(row.get("transcript_text"))
    if transcript:
        text = f"{text}\n\n{transcript}"
    return text


SPACE_TEXT_BUILDERS: dict[str, Callable[[dict[str, Any]], str | None]] = {
    "icp": build_icp_text,
    "search": build_search_text,
}


def embed_query(
    config: Config,
    query: str,
    *,
    model: str | None = None,
    timeout: int = 30,
) -> list[float]:
    """Embed a search query with Voyage using input_type='query' (asymmetric retrieval)."""
    embedding_model = model or config.embedding_model
    if not config.voyage_api_key:
        raise RuntimeError("VOYAGE_API_KEY is required to embed a search query.")
    response = request_json(
        "POST",
        f"{VOYAGE_BASE_URL}{VOYAGE_EMBEDDINGS_ENDPOINT}",
        headers={"Authorization": f"Bearer {config.voyage_api_key}"},
        body={"input": [query], "model": embedding_model, "input_type": "query"},
        timeout=timeout,
    )
    return parse_voyage_response(response.body, expected_count=1)[0]


def clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def flatten_jsonish(value: Any) -> str | None:
    if isinstance(value, str):
        return clean_text(value)
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        parts = [flatten_jsonish(item) for item in value]
        return ", ".join(part for part in parts if part) or None
    if isinstance(value, dict):
        parts = []
        for key in sorted(value):
            flat = flatten_jsonish(value[key])
            if flat:
                parts.append(f"{key}: {flat}")
        return "; ".join(parts) or None
    return None
