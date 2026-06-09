from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import Config
from .http_client import HttpClientError, request_json
from .ingestion import IngestResult, log_failed_query, start_query, write_items
from .normalizers import normalize_foreplay_ad, result_items
from .supabase_client import SupabaseClient


DISCOVERY_ADS_PATH = "/api/discovery/ads"


def ingest_foreplay_ads(
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
    endpoint = f"{config.foreplay_base_url}{DISCOVERY_ADS_PATH}"
    fetched = 0
    written = 0
    offset = 0
    extra_params = extra_params or {}

    while fetched < target_count:
        current_limit = min(page_size, target_count - fetched)
        params: dict[str, Any] = {
            "query": keyword,
            "limit": current_limit,
            "offset": offset,
            "order": "longest_running",
            **extra_params,
        }
        source_query_id = start_query(
            supabase=supabase,
            dry_run=dry_run,
            run_id=run_id,
            provider="foreplay",
            endpoint=DISCOVERY_ADS_PATH,
            method="GET",
            request_params=params,
        )

        try:
            if input_json:
                body = json.loads(input_json.read_text())
            else:
                if not config.foreplay_api_key:
                    raise RuntimeError("FOREPLAY_API_KEY is required unless --input-json is used.")
                response = request_json(
                    "GET",
                    endpoint,
                    headers={"Authorization": f"Bearer {config.foreplay_api_key}"},
                    params=params,
                )
                body = response.body
            items = result_items(body)

            result = write_items(
                supabase=supabase,
                dry_run=dry_run,
                run_id=run_id,
                provider="foreplay",
                endpoint=DISCOVERY_ADS_PATH,
                method="GET",
                request_params=params,
                source_query_id=source_query_id,
                items=items,
                normalizer=normalize_foreplay_ad,
            )
            fetched += result.fetched
            written += result.written

            if not items:
                break
            if input_json or len(items) < current_limit:
                break
            offset += current_limit
        except (HttpClientError, RuntimeError) as exc:
            log_failed_query(
                supabase=supabase,
                dry_run=dry_run,
                run_id=run_id,
                provider="foreplay",
                endpoint=DISCOVERY_ADS_PATH,
                method="GET",
                request_params=params,
                source_query_id=source_query_id,
                http_status=getattr(exc, "status", None),
                error_message=str(exc),
            )
            raise

    return IngestResult(fetched=fetched, written=written)
