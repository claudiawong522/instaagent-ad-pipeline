from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import Config
from .http_client import HttpClientError, request_json
from .ingestion import IngestResult, log_api_usage, log_failed_query, start_query, write_items
from .normalizers import normalize_topyappers_item, result_items
from .supabase_client import SupabaseClient


VIRAL_CONTENT_PATH = "/api/v1/viral-content"
VIDEOS_PATH = "/api/v1/videos"


def ingest_topyappers_viral(
    *,
    config: Config,
    supabase: SupabaseClient | None,
    run_id: str,
    keyword: str,
    target_count: int,
    page_size: int,
    dry_run: bool,
    input_json: Path | None = None,
    extra_params: dict[str, Any] | None = None,
) -> IngestResult:
    endpoint = f"{config.topyappers_base_url}{VIRAL_CONTENT_PATH}"
    fetched = 0
    written = 0
    page = 1
    extra_params = extra_params or {}

    while fetched < target_count:
        current_limit = min(page_size, target_count - fetched)
        body_params: dict[str, Any] = {
            "videoTopicContains": keyword,
            "page": page,
            "pageSize": current_limit,
            **extra_params,
        }
        source_query_id = start_query(
            supabase=supabase,
            dry_run=dry_run,
            run_id=run_id,
            provider="topyappers",
            endpoint=VIRAL_CONTENT_PATH,
            method="POST",
            request_params=body_params,
        )
        try:
            if input_json:
                body = json.loads(input_json.read_text())
                response_headers = {}
                response_status = None
            else:
                if not config.topyappers_api_key:
                    raise RuntimeError("TOPYAPPERS_API_KEY is required unless --input-json is used.")
                response = request_json(
                    "POST",
                    endpoint,
                    headers={"x-ty-api-key": config.topyappers_api_key},
                    body=body_params,
                )
                body = response.body
                response_headers = response.headers
                response_status = response.status
            items = result_items(body)
            items_to_write = items[:current_limit]
            log_api_usage(
                supabase=supabase,
                dry_run=dry_run,
                run_id=run_id,
                provider="topyappers",
                endpoint=VIRAL_CONTENT_PATH,
                status=response_status,
                response_count=len(items),
                headers=response_headers,
            )

            result = write_items(
                supabase=supabase,
                dry_run=dry_run,
                run_id=run_id,
                provider="topyappers",
                endpoint=VIRAL_CONTENT_PATH,
                method="POST",
                request_params=body_params,
                source_query_id=source_query_id,
                destination_table="ugc_items",
                items=items_to_write,
                normalizer=lambda item, rid, raw_id: normalize_topyappers_item(
                    item,
                    rid,
                    raw_id,
                    endpoint_kind="viral-content",
                ),
                conflict_columns="run_id,external_id",
            )
            fetched += result.fetched
            written += result.written

            if not items:
                break
            if input_json or len(items) < current_limit:
                break
            page += 1
        except (HttpClientError, RuntimeError) as exc:
            log_failed_query(
                supabase=supabase,
                dry_run=dry_run,
                run_id=run_id,
                provider="topyappers",
                endpoint=VIRAL_CONTENT_PATH,
                method="POST",
                request_params=body_params,
                source_query_id=source_query_id,
                http_status=getattr(exc, "status", None),
                error_message=str(exc),
            )
            raise

    return IngestResult(fetched=fetched, written=written)


def ingest_topyappers_videos(
    *,
    config: Config,
    supabase: SupabaseClient | None,
    run_id: str,
    keyword: str,
    target_count: int,
    page_size: int,
    dry_run: bool,
    input_json: Path | None = None,
    extra_params: dict[str, Any] | None = None,
) -> IngestResult:
    endpoint = f"{config.topyappers_base_url}{VIDEOS_PATH}"
    fetched = 0
    written = 0
    page = 1
    extra_params = extra_params or {}

    while fetched < target_count:
        current_limit = min(page_size, target_count - fetched)
        params: dict[str, Any] = {
            "page": page,
            "perPage": current_limit,
            "textSearch": keyword,
            "sortBy": "views",
            "sortOrder": "desc",
            **extra_params,
        }
        source_query_id = start_query(
            supabase=supabase,
            dry_run=dry_run,
            run_id=run_id,
            provider="topyappers",
            endpoint=VIDEOS_PATH,
            method="GET",
            request_params=params,
        )
        try:
            if input_json:
                body = json.loads(input_json.read_text())
                response_headers = {}
                response_status = None
            else:
                if not config.topyappers_api_key:
                    raise RuntimeError("TOPYAPPERS_API_KEY is required unless --input-json is used.")
                response = request_json(
                    "GET",
                    endpoint,
                    headers={"x-ty-api-key": config.topyappers_api_key},
                    params=params,
                )
                body = response.body
                response_headers = response.headers
                response_status = response.status
            items = result_items(body)
            items_to_write = items[:current_limit]
            log_api_usage(
                supabase=supabase,
                dry_run=dry_run,
                run_id=run_id,
                provider="topyappers",
                endpoint=VIDEOS_PATH,
                status=response_status,
                response_count=len(items),
                headers=response_headers,
            )

            result = write_items(
                supabase=supabase,
                dry_run=dry_run,
                run_id=run_id,
                provider="topyappers",
                endpoint=VIDEOS_PATH,
                method="GET",
                request_params=params,
                source_query_id=source_query_id,
                destination_table="ugc_items",
                items=items_to_write,
                normalizer=lambda item, rid, raw_id: normalize_topyappers_item(
                    item,
                    rid,
                    raw_id,
                    endpoint_kind="videos",
                ),
                conflict_columns="run_id,external_id",
            )
            fetched += result.fetched
            written += result.written

            if not items:
                break
            if input_json or len(items) < current_limit:
                break
            page += 1
        except (HttpClientError, RuntimeError) as exc:
            log_failed_query(
                supabase=supabase,
                dry_run=dry_run,
                run_id=run_id,
                provider="topyappers",
                endpoint=VIDEOS_PATH,
                method="GET",
                request_params=params,
                source_query_id=source_query_id,
                http_status=getattr(exc, "status", None),
                error_message=str(exc),
            )
            raise

    return IngestResult(fetched=fetched, written=written)
