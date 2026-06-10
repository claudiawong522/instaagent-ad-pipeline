from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable

from .supabase_client import SupabaseClient


@dataclass
class IngestResult:
    fetched: int
    written: int


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def start_query(
    *,
    supabase: SupabaseClient | None,
    dry_run: bool,
    run_id: str,
    provider: str,
    endpoint: str,
    method: str,
    request_params: dict[str, Any],
) -> str | None:
    if dry_run or supabase is None:
        return None
    row = supabase.insert(
        "source_queries",
        {
            "run_id": run_id,
            "provider": provider,
            "endpoint": endpoint,
            "method": method,
            "request_params": request_params,
            "status": "started",
        },
    )
    return row.get("id")


def log_api_usage(
    *,
    supabase: SupabaseClient | None,
    dry_run: bool,
    run_id: str,
    provider: str,
    endpoint: str,
    status: int | None,
    response_count: int | None,
    headers: dict[str, str] | None,
) -> None:
    if dry_run or supabase is None or status is None:
        return
    supabase.insert(
        "api_usage",
        {
            "run_id": run_id,
            "provider": provider,
            "endpoint": endpoint,
            "credits_used": credits_used_from_headers(headers or {}),
            "rate_limit": {
                "http_status": status,
                "response_count": response_count,
                "headers": usage_headers(headers or {}),
            },
        },
    )


def credits_used_from_headers(headers: dict[str, str]) -> float | None:
    for name, value in headers.items():
        normalized = name.lower()
        if normalized in {"x-credits-used", "x-credit-used", "x-api-credits-used", "x-usage-credits"}:
            try:
                return float(value)
            except ValueError:
                return None
    return None


def usage_headers(headers: dict[str, str]) -> dict[str, str]:
    return {
        name: value
        for name, value in headers.items()
        if any(token in name.lower() for token in ("limit", "remaining", "reset", "credit", "usage", "quota"))
    }


def write_items(
    *,
    supabase: SupabaseClient | None,
    dry_run: bool,
    run_id: str,
    provider: str,
    endpoint: str,
    method: str,
    request_params: dict[str, Any],
    source_query_id: str | None,
    destination_table: str,
    items: list[dict[str, Any]],
    normalizer: Callable[[dict[str, Any], str, str | None], dict[str, Any]],
    conflict_columns: str = "run_id,source_provider,external_id",
) -> IngestResult:
    if dry_run:
        for item in items:
            normalizer(item, run_id, None)
        return IngestResult(fetched=len(items), written=0)

    if supabase is None:
        raise RuntimeError("Supabase credentials are required unless --dry-run is used.")

    if source_query_id:
        supabase.update_by_id(
            "source_queries",
            source_query_id,
            {
                "status": "completed",
                "response_count": len(items),
                "completed_at": utc_now_iso(),
            },
        )
    else:
        source_query = supabase.insert(
            "source_queries",
            {
                "run_id": run_id,
                "provider": provider,
                "endpoint": endpoint,
                "method": method,
                "request_params": request_params,
                "status": "completed",
                "response_count": len(items),
                "completed_at": utc_now_iso(),
            },
        )
        source_query_id = source_query.get("id")

    written = 0
    for item in items:
        external_id = str(item.get("id") or item.get("ad_id") or item.get("video_id") or item.get("iv_id") or "")
        raw_payload = supabase.insert(
            "raw_payloads",
            {
                "run_id": run_id,
                "source_query_id": source_query_id,
                "provider": provider,
                "endpoint": endpoint,
                "external_id": external_id,
                "payload_json": item,
            },
        )
        normalized = normalizer(item, run_id, raw_payload.get("id"))
        supabase.upsert(destination_table, normalized, conflict_columns)
        written += 1

    return IngestResult(fetched=len(items), written=written)


def log_failed_query(
    *,
    supabase: SupabaseClient | None,
    dry_run: bool,
    run_id: str,
    provider: str,
    endpoint: str,
    method: str,
    request_params: dict[str, Any],
    source_query_id: str | None = None,
    http_status: int | None,
    error_message: str,
) -> None:
    if dry_run or supabase is None:
        return
    if source_query_id:
        supabase.update_by_id(
            "source_queries",
            source_query_id,
            {
                "status": "failed",
                "http_status": http_status,
                "error_message": error_message,
                "completed_at": utc_now_iso(),
            },
        )
        return
    supabase.insert(
        "source_queries",
        {
            "run_id": run_id,
            "provider": provider,
            "endpoint": endpoint,
            "method": method,
            "request_params": request_params,
            "status": "failed",
            "http_status": http_status,
            "error_message": error_message,
            "completed_at": utc_now_iso(),
        },
    )
