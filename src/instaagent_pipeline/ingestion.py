from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable, Iterator

from .http_client import HttpClientError
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
    run_id: str | None,
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


def complete_query(
    *,
    supabase: SupabaseClient | None,
    dry_run: bool,
    source_query_id: str | None,
    response_count: int | None,
    http_status: int | None = None,
) -> None:
    if dry_run or supabase is None or source_query_id is None:
        return
    payload: dict[str, Any] = {
        "status": "completed",
        "response_count": response_count,
        "completed_at": utc_now_iso(),
    }
    if http_status is not None:
        payload["http_status"] = http_status
    supabase.update_by_id("source_queries", source_query_id, payload)


def log_api_usage(
    *,
    supabase: SupabaseClient | None,
    dry_run: bool,
    run_id: str | None,
    provider: str,
    endpoint: str,
    status: int | None,
    response_count: int | None,
    headers: dict[str, str] | None,
    metadata: dict[str, Any] | None = None,
) -> None:
    if dry_run or supabase is None or status is None:
        return
    rate_limit: dict[str, Any] = {
        "http_status": status,
        "response_count": response_count,
        "headers": usage_headers(headers or {}),
    }
    if metadata:
        rate_limit.update(metadata)
    supabase.insert(
        "api_usage",
        {
            "run_id": run_id,
            "provider": provider,
            "endpoint": endpoint,
            "credits_used": credits_used_from_headers(headers or {}),
            "rate_limit": rate_limit,
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
    response_status: int | None = None,
) -> IngestResult:
    if dry_run:
        for item in items:
            normalizer(item, run_id, None)
        return IngestResult(fetched=len(items), written=0)

    if supabase is None:
        raise RuntimeError("Supabase credentials are required unless --dry-run is used.")

    if source_query_id:
        complete_query(
            supabase=supabase,
            dry_run=dry_run,
            source_query_id=source_query_id,
            response_count=len(items),
            http_status=response_status,
        )
    else:
        payload: dict[str, Any] = {
            "run_id": run_id,
            "provider": provider,
            "endpoint": endpoint,
            "method": method,
            "request_params": request_params,
            "status": "completed",
            "response_count": len(items),
            "completed_at": utc_now_iso(),
        }
        if response_status is not None:
            payload["http_status"] = response_status
        source_query = supabase.insert("source_queries", payload)
        source_query_id = source_query.get("id")

    written = 0
    for item in items:
        external_id = str(
            item.get("id")
            or item.get("adArchiveID")
            or item.get("adArchiveId")
            or item.get("ad_id")
            or item.get("adId")
            or item.get("video_id")
            or item.get("iv_id")
            or ""
        )
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


@dataclass
class QueryLog:
    """Mutable record of one provider call, managed by `logged_query`.

    The caller fills in what it learns as the call proceeds (status, headers,
    response_count, metadata, and — when the provider is resolved late — provider/
    endpoint); the context manager writes the bookkeeping rows on exit. Set
    `live=False` when replaying a --input-json fixture so an error is not logged
    as live-API usage."""

    supabase: SupabaseClient | None
    dry_run: bool
    run_id: str | None
    provider: str
    endpoint: str
    method: str
    request_params: dict[str, Any]
    source_query_id: str | None = None
    status: int | None = None
    headers: dict[str, str] = field(default_factory=dict)
    response_count: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    live: bool = True

    def log_usage(self) -> None:
        """Write the api_usage row now (e.g. before further Supabase writes that could
        fail); the context manager then skips its own usage write on exit."""
        log_api_usage(
            supabase=self.supabase,
            dry_run=self.dry_run,
            run_id=self.run_id,
            provider=self.provider,
            endpoint=self.endpoint,
            status=self.status,
            response_count=self.response_count,
            headers=self.headers,
            metadata=self.metadata or None,
        )
        self._usage_logged = True

    _usage_logged: bool = False


@contextmanager
def logged_query(
    *,
    supabase: SupabaseClient | None,
    dry_run: bool = False,
    run_id: str | None,
    provider: str,
    endpoint: str,
    method: str = "POST",
    request_params: dict[str, Any],
) -> Iterator[QueryLog]:
    """Bookkeep one provider call in source_queries/api_usage.

    Opens a source_queries row, yields a QueryLog for the caller to fill in, and on
    exit logs api_usage + completes the query — or, on HttpClientError/RuntimeError,
    marks it failed (logging the error status as usage when the call never got a
    response). This is the shared try/except that every provider call used to
    hand-roll."""
    log = QueryLog(
        supabase=supabase,
        dry_run=dry_run,
        run_id=run_id,
        provider=provider,
        endpoint=endpoint,
        method=method,
        request_params=request_params,
        source_query_id=start_query(
            supabase=supabase,
            dry_run=dry_run,
            run_id=run_id,
            provider=provider,
            endpoint=endpoint,
            method=method,
            request_params=request_params,
        ),
    )
    try:
        yield log
    except (HttpClientError, RuntimeError) as exc:
        if isinstance(exc, HttpClientError) and log.status is None and log.live:
            log_api_usage(
                supabase=supabase,
                dry_run=dry_run,
                run_id=run_id,
                provider=log.provider,
                endpoint=log.endpoint,
                status=exc.status,
                response_count=None,
                headers={},
                metadata=log.metadata or None,
            )
        log_failed_query(
            supabase=supabase,
            dry_run=dry_run,
            run_id=run_id or "",
            provider=log.provider,
            endpoint=log.endpoint,
            method=method,
            request_params=request_params,
            source_query_id=log.source_query_id,
            http_status=getattr(exc, "status", None),
            error_message=str(exc),
        )
        raise
    if not log._usage_logged:
        log.log_usage()
    complete_query(
        supabase=supabase,
        dry_run=dry_run,
        source_query_id=log.source_query_id,
        response_count=log.response_count,
        http_status=log.status,
    )


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
