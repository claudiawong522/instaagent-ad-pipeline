from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from .apify_client import ingest_actor_items
from .config import Config
from .ingestion import IngestResult
from .normalizers import normalize_apify_ad, result_items
from .supabase_client import SupabaseClient


APIFY_ADS_ACTOR_ID = "apify~facebook-ads-scraper"
APIFY_ADS_ACTOR_NAME = "apify/facebook-ads-scraper"
APIFY_ADS_PROVIDER = f"apify:{APIFY_ADS_ACTOR_NAME}"
META_AD_LIBRARY_URL = "https://www.facebook.com/ads/library/"


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
    return ingest_actor_items(
        config=config,
        supabase=supabase,
        run_id=run_id,
        provider=APIFY_ADS_PROVIDER,
        actor_id=APIFY_ADS_ACTOR_ID,
        actor_input=actor_input,
        request_params={
            "actor": APIFY_ADS_ACTOR_NAME,
            "keyword": keyword,
            "meta_ad_library_url": meta_ad_library_url,
            "page_size": page_size,
            "actor_input": actor_input,
        },
        prepare_items=apify_ad_items,
        destination_table="paid_ads",
        normalizer=normalize_apify_ad,
        conflict_columns="run_id,id",
        target_count=target_count,
        dry_run=dry_run,
        input_json=input_json,
    )


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
