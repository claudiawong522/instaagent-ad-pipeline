from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from .config import Config
from .http_client import HttpClientError, request_json
from .ingestion import IngestResult, log_api_usage, log_failed_query, start_query, write_items
from .normalizers import normalize_apify_ad, result_items
from .supabase_client import SupabaseClient


APIFY_ADS_ACTOR_ID = "apify~facebook-ads-scraper"
APIFY_ADS_ACTOR_NAME = "apify/facebook-ads-scraper"
APIFY_ADS_PROVIDER = f"apify:{APIFY_ADS_ACTOR_NAME}"
APIFY_ADS_ENDPOINT = f"/actors/{APIFY_ADS_ACTOR_ID}/runs"
APIFY_API_BASE_URL = "https://api.apify.com/v2"
APIFY_RUN_WAIT_SECONDS = 60
APIFY_RUN_TIMEOUT_SECONDS = 900
META_AD_LIBRARY_URL = "https://www.facebook.com/ads/library/"
APIFY_SUCCEEDED_STATUS = "SUCCEEDED"
APIFY_TRANSITIONAL_STATUSES = {"READY", "RUNNING"}


def ingest_apify_ads(
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
    meta_ad_library_url = build_meta_ad_library_url(keyword)
    actor_input = apify_ads_actor_input(
        meta_ad_library_url=meta_ad_library_url,
        target_count=target_count,
        overrides=extra_params,
    )
    request_params = {
        "actor": APIFY_ADS_ACTOR_NAME,
        "keyword": keyword,
        "meta_ad_library_url": meta_ad_library_url,
        "page_size": page_size,
        "actor_input": actor_input,
    }
    source_query_id = start_query(
        supabase=supabase,
        dry_run=dry_run,
        run_id=run_id,
        provider=APIFY_ADS_PROVIDER,
        endpoint=APIFY_ADS_ENDPOINT,
        method="POST",
        request_params=request_params,
    )
    response_headers: dict[str, str] = {}
    response_status: int | None = None
    run_metadata: dict[str, Any] = {}

    try:
        if input_json:
            body = json.loads(input_json.read_text())
            items = apify_ad_items(body)[:target_count]
        else:
            if not config.apify_api_key:
                raise RuntimeError("APIFY_API_KEY is required unless --input-json is used.")
            items, response_status, response_headers, run_metadata = fetch_apify_actor_dataset_items(
                api_key=config.apify_api_key,
                actor_input=actor_input,
                target_count=target_count,
            )
        log_api_usage(
            supabase=supabase,
            dry_run=dry_run,
            run_id=run_id,
            provider=APIFY_ADS_PROVIDER,
            endpoint=APIFY_ADS_ENDPOINT,
            status=response_status,
            response_count=len(items),
            headers=response_headers,
            metadata={"actor": APIFY_ADS_ACTOR_NAME, **run_metadata},
        )
        return write_items(
            supabase=supabase,
            dry_run=dry_run,
            run_id=run_id,
            provider=APIFY_ADS_PROVIDER,
            endpoint=APIFY_ADS_ENDPOINT,
            method="POST",
            request_params=request_params,
            source_query_id=source_query_id,
            destination_table="paid_ads",
            items=items,
            normalizer=normalize_apify_ad,
            conflict_columns="run_id,id",
            response_status=response_status,
        )
    except (HttpClientError, RuntimeError) as exc:
        if isinstance(exc, HttpClientError) and response_status is None and not input_json:
            log_api_usage(
                supabase=supabase,
                dry_run=dry_run,
                run_id=run_id,
                provider=APIFY_ADS_PROVIDER,
                endpoint=APIFY_ADS_ENDPOINT,
                status=exc.status,
                response_count=None,
                headers={},
                metadata={"actor": APIFY_ADS_ACTOR_NAME},
            )
        log_failed_query(
            supabase=supabase,
            dry_run=dry_run,
            run_id=run_id,
            provider=APIFY_ADS_PROVIDER,
            endpoint=APIFY_ADS_ENDPOINT,
            method="POST",
            request_params=request_params,
            source_query_id=source_query_id,
            http_status=getattr(exc, "status", None),
            error_message=str(exc),
        )
        raise


def apify_ads_actor_input(
    *,
    meta_ad_library_url: str,
    target_count: int,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    actor_input: dict[str, Any] = {
        "startUrls": [{"url": meta_ad_library_url}],
        "resultsLimit": target_count,
        "activeStatus": "",
        "onlyTotal": False,
        "includeAboutPage": False,
        "isDetailsPerAd": False,
    }
    if overrides:
        actor_input.update(overrides)
    return actor_input


def fetch_apify_actor_dataset_items(
    *,
    api_key: str,
    actor_input: dict[str, Any],
    target_count: int,
) -> tuple[list[dict[str, Any]], int, dict[str, str], dict[str, Any]]:
    run_response = request_json(
        "POST",
        f"{APIFY_API_BASE_URL}{APIFY_ADS_ENDPOINT}",
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
        timeout=120,
    )
    metadata = {
        "actor_run_id": run.get("id"),
        "actor_run_status": run.get("status"),
        "actor_default_dataset_id": dataset_id,
        "actor_usage_total_usd": run.get("usageTotalUsd"),
    }
    return apify_ad_items(dataset_response.body)[:target_count], dataset_response.status, dataset_response.headers, metadata


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


def apify_data(body: Any) -> dict[str, Any]:
    if isinstance(body, dict):
        data = body.get("data")
        if isinstance(data, dict):
            return data
        return body
    return {}


def apify_ad_items(body: Any) -> list[dict[str, Any]]:
    return [item for item in result_items(body) if apify_ad_external_id(item)]


def apify_ad_external_id(item: dict[str, Any]) -> Any:
    return item.get("adArchiveID") or item.get("adArchiveId") or item.get("id") or item.get("adId")


def build_meta_ad_library_url(keyword: str) -> str:
    params: dict[str, str] = {
        "active_status": "all",
        "ad_type": "all",
        "country": "ALL",
        "is_targeted_country": "false",
        "media_type": "video",
        "publisher_platforms[0]": "instagram",
        "publisher_platforms[1]": "facebook",
        "search_type": "keyword_unordered",
        "q": keyword,
    }
    return f"{META_AD_LIBRARY_URL}?{urlencode(params)}"
