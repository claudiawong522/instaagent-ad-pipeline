"""Shared Apify actor runtime: start a run, poll it, read its dataset, ingest its items.

Every Apify-backed source (Meta Ad Library, TikTok, Instagram, trend-page rendering)
goes through the same run→poll→dataset flow; this module owns it so feature modules
only supply the actor id, input, and how to filter/normalize the items.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from .config import Config
from .http_client import request_json
from .ingestion import IngestResult, logged_query, write_items
from .normalizers import result_items
from .supabase_client import SupabaseClient


APIFY_API_BASE_URL = "https://api.apify.com/v2"
APIFY_RUN_WAIT_SECONDS = 60
APIFY_RUN_TIMEOUT_SECONDS = 900
APIFY_SUCCEEDED_STATUS = "SUCCEEDED"
APIFY_TRANSITIONAL_STATUSES = {"READY", "RUNNING"}


def actor_runs_endpoint(actor_id: str) -> str:
    return f"/acts/{actor_id}/runs"


def apify_data(body: Any) -> dict[str, Any]:
    if isinstance(body, dict):
        data = body.get("data")
        if isinstance(data, dict):
            return data
        return body
    return {}


def wait_for_apify_run(api_key: str, run: dict[str, Any]) -> dict[str, Any]:
    run_id = run.get("id")
    if not run_id:
        raise RuntimeError("Apify did not return an actor run id.")

    deadline = time.monotonic() + APIFY_RUN_TIMEOUT_SECONDS
    while str(run.get("status") or "") in APIFY_TRANSITIONAL_STATUSES:
        remaining = int(deadline - time.monotonic())
        if remaining <= 0:
            raise RuntimeError(f"Apify run {run_id} did not finish within {APIFY_RUN_TIMEOUT_SECONDS} seconds.")
        wait_for_finish = min(APIFY_RUN_WAIT_SECONDS, remaining)
        response = request_json(
            "GET",
            f"{APIFY_API_BASE_URL}/actor-runs/{run_id}",
            params={"token": api_key, "waitForFinish": wait_for_finish},
            timeout=wait_for_finish + 30,
        )
        run = apify_data(response.body)

    status = str(run.get("status") or "")
    if status != APIFY_SUCCEEDED_STATUS:
        raise RuntimeError(f"Apify run {run_id} ended with status {status}: {run.get('statusMessage')}")
    return run


def run_apify_actor_items(
    *,
    api_key: str,
    actor_id: str,
    actor_input: dict[str, Any],
    target_count: int,
) -> tuple[list[dict[str, Any]], int, dict[str, str], dict[str, Any]]:
    """Start an actor run, wait for it, and return its dataset items plus
    (status, headers, run metadata) for bookkeeping."""
    run_response = request_json(
        "POST",
        f"{APIFY_API_BASE_URL}{actor_runs_endpoint(actor_id)}",
        params={"token": api_key, "waitForFinish": APIFY_RUN_WAIT_SECONDS},
        body=actor_input,
        timeout=APIFY_RUN_WAIT_SECONDS + 30,
    )
    run = wait_for_apify_run(api_key, apify_data(run_response.body))
    dataset_id = run.get("defaultDatasetId")
    if not dataset_id:
        raise RuntimeError(f"Apify run {run.get('id')} did not return a defaultDatasetId.")
    dataset_response = request_json(
        "GET",
        f"{APIFY_API_BASE_URL}/datasets/{dataset_id}/items",
        params={"token": api_key, "format": "json", "clean": "1", "limit": target_count},
        timeout=180,
    )
    metadata = {
        "actor_run_id": run.get("id"),
        "actor_run_status": run.get("status"),
        "actor_default_dataset_id": dataset_id,
        "actor_usage_total_usd": run.get("usageTotalUsd"),
    }
    return result_items(dataset_response.body), dataset_response.status, dataset_response.headers, metadata


def ingest_actor_items(
    *,
    config: Config,
    supabase: SupabaseClient | None,
    run_id: str,
    provider: str,
    actor_id: str,
    actor_input: dict[str, Any],
    request_params: dict[str, Any],
    prepare_items: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
    destination_table: str,
    normalizer: Callable[[dict[str, Any], str, str | None], dict[str, Any]],
    conflict_columns: str,
    target_count: int,
    dry_run: bool,
    input_json: Path | None,
) -> IngestResult:
    """Run one actor (or replay --input-json), filter its items via `prepare_items`,
    and write them through the standard raw-payload + normalized-upsert path, with
    source_queries/api_usage bookkeeping handled by `logged_query`."""
    endpoint = actor_runs_endpoint(actor_id)
    with logged_query(
        supabase=supabase,
        dry_run=dry_run,
        run_id=run_id,
        provider=provider,
        endpoint=endpoint,
        request_params=request_params,
    ) as log:
        log.live = not input_json
        log.metadata = {"actor": actor_id}
        if input_json:
            items = result_items(json.loads(input_json.read_text()))
        else:
            if not config.apify_api_key:
                raise RuntimeError("APIFY_API_KEY is required unless --input-json is used.")
            items, log.status, log.headers, run_metadata = run_apify_actor_items(
                api_key=config.apify_api_key,
                actor_id=actor_id,
                actor_input=actor_input,
                target_count=target_count,
            )
            log.metadata.update(run_metadata)
        items = prepare_items(items)[:target_count]
        log.response_count = len(items)
        # api_usage is written before the row-by-row Supabase writes so a mid-write
        # failure can't lose the run's recorded (real-USD) cost.
        log.log_usage()
        return write_items(
            supabase=supabase,
            dry_run=dry_run,
            run_id=run_id,
            provider=provider,
            endpoint=endpoint,
            method="POST",
            request_params=request_params,
            source_query_id=log.source_query_id,
            destination_table=destination_table,
            items=items,
            normalizer=normalizer,
            conflict_columns=conflict_columns,
            response_status=log.status,
        )
