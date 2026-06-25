#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from instaagent_pipeline.apify_ads import APIFY_ADS_PROVIDER, ingest_apify_ads
from instaagent_pipeline.cli import build_supabase, ingest_allocated_keywords, init_run
from instaagent_pipeline.config import Config
from instaagent_pipeline.ad_enrichment import enrich_paid_ads
from instaagent_pipeline.ingestion import utc_now_iso
from instaagent_pipeline.keywords import generate_keyword_allocations, insert_keyword_allocations
from instaagent_pipeline.topyappers import ingest_topyappers_viral


def main() -> int:
    args = parse_args()
    if not args.confirm_live:
        raise SystemExit("Refusing to run live API/DB smoke test without --confirm-live.")

    config = Config.from_env()
    missing = required_env_missing(
        config,
        need_apify_ads=not args.skip_apify_ads,
        need_topyappers=not args.skip_topyappers,
        need_enrichment=not args.skip_apify_ads and not args.skip_enrichment,
    )
    if missing:
        raise SystemExit(f"Missing required env values: {', '.join(missing)}")

    supabase = build_supabase(config, dry_run=False)
    if supabase is None:
        raise SystemExit("Supabase client was not created.")

    run_id: str | None = None
    try:
        init_result = init_smoke_run(args, supabase, config)
        run_id = init_result["pipeline_run"]["id"]

        apify_ads_result = None
        enrichment_result = None
        topyappers_result = None
        if not args.skip_apify_ads:
            apify_ads_result = ingest_allocated_keywords(
                config=config,
                supabase=supabase,
                args=SimpleNamespace(
                    run_id=run_id,
                    dry_run=False,
                    input_json=None,
                    extra_param=args.extra_param,
                ),
                target_field="target_paid_count",
                ingest_func=ingest_apify_ads,
            )
            fetched = int(apify_ads_result.get("fetched") or 0)
            if not args.skip_enrichment and fetched > 0:
                enrichment_result = enrich_paid_ads(
                    config=config,
                    supabase=supabase,
                    run_id=run_id,
                    limit=fetched,
                    dry_run=False,
                )

        if not args.skip_topyappers:
            topyappers_result = ingest_allocated_keywords(
                config=config,
                supabase=supabase,
                args=SimpleNamespace(
                    run_id=run_id,
                    dry_run=False,
                    page_size=args.topyappers_page_size,
                    input_json=None,
                    extra_param=args.extra_param,
                ),
                target_field="target_ugc_count",
                ingest_func=ingest_topyappers_viral,
            )

        verification = verify_database_state(
            supabase=supabase,
            run_id=run_id,
            expected_paid_total=args.target_paid_count,
            expected_organic_total=args.target_ugc_count,
            expect_apify_ads=not args.skip_apify_ads,
            expect_topyappers=not args.skip_topyappers,
            expect_enrichment=enrichment_result is not None,
        )
        supabase.update_by_id("pipeline_runs", run_id, {"status": "completed", "updated_at": utc_now_iso()})
    except Exception:
        if run_id is not None:
            supabase.update_by_id("pipeline_runs", run_id, {"status": "failed", "updated_at": utc_now_iso()})
        raise

    summary = {
        "run_id": run_id,
        "product": init_result["product"],
        "keywords": verification["keywords"],
        "apify_ads": apify_ads_result,
        "enrichment": enrichment_result.__dict__ if enrichment_result is not None else None,
        "topyappers": topyappers_result,
        "database_counts": verification["counts"],
        "warnings": verification["warnings"],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Live smoke test for product -> Claude keywords -> provider ingestion -> Supabase rows.",
    )
    parser.add_argument("--confirm-live", action="store_true", help="Required. Writes to Supabase and calls paid APIs.")
    parser.add_argument("--product-id", help="Reuse an existing products.id row instead of creating a new product.")
    parser.add_argument("--product-name", default="Smoke test gentle cleanser", help="Used when --product-id is omitted.")
    parser.add_argument("--category", default="skincare", help="Used when --product-id is omitted.")
    parser.add_argument("--target-market", default="US skincare buyers", help="Used when --product-id is omitted.")
    parser.add_argument("--notes", default="Smoke test record. Safe to delete.", help="Used when --product-id is omitted.")
    parser.add_argument(
        "--campaign-guidelines",
        default="Find competitor paid ads and organic videos for a gentle cleanser launch.",
    )
    parser.add_argument("--target-paid-count", type=int, default=3)
    parser.add_argument("--target-ugc-count", type=int, default=3)
    parser.add_argument("--topyappers-page-size", type=int, default=1)
    parser.add_argument("--skip-apify-ads", action="store_true")
    parser.add_argument("--skip-enrichment", action="store_true", help="Skip the OpenRouter paid-ad transcript/metadata stage.")
    parser.add_argument("--skip-topyappers", action="store_true")
    parser.add_argument(
        "--extra-param",
        action="append",
        default=[],
        help="Extra provider API param as key=value. Passed to both provider ingestion stages.",
    )
    return parser.parse_args()


def init_smoke_run(args: argparse.Namespace, supabase: Any, config: Config) -> dict[str, Any]:
    if args.product_id:
        return init_existing_product_run(args, supabase, config)

    return init_run(
        SimpleNamespace(
            product_name=args.product_name,
            category=args.category,
            target_market=args.target_market,
            notes=args.notes,
            campaign_guidelines=args.campaign_guidelines,
            keyword=None,
            keyword_type="seed",
            target_paid_count=args.target_paid_count,
            target_ugc_count=args.target_ugc_count,
            top_k=3,
            config_json="{}",
            dry_run=False,
        ),
        supabase,
        config,
    )


def init_existing_product_run(args: argparse.Namespace, supabase: Any, config: Config) -> dict[str, Any]:
    products = supabase.select(
        "products",
        {
            "select": "id,name,category,target_market,notes",
            "id": f"eq.{args.product_id}",
        },
    )
    if not products:
        raise RuntimeError(f"No product found for --product-id {args.product_id}.")

    product = products[0]
    run_config: dict[str, Any] = {}
    if args.campaign_guidelines:
        run_config["campaign_guidelines"] = args.campaign_guidelines
    run = supabase.insert(
        "pipeline_runs",
        {
            "product_id": product["id"],
            "status": "created",
            "config": run_config,
            "target_paid_count": args.target_paid_count,
            "target_ugc_count": args.target_ugc_count,
            "top_k": 3,
        },
    )
    try:
        generation_result = generate_keyword_allocations(
            config=config,
            supabase=supabase,
            dry_run=False,
            run_id=run["id"],
            product_name=str(product.get("name") or ""),
            category=product.get("category"),
            target_market=product.get("target_market"),
            notes=product.get("notes"),
            campaign_guidelines=args.campaign_guidelines,
            target_paid_count=args.target_paid_count,
            target_ugc_count=args.target_ugc_count,
        )
        keywords = insert_keyword_allocations(supabase, run_id=run["id"], allocations=generation_result.allocations)
    except Exception:
        supabase.update_by_id(
            "pipeline_runs",
            run["id"],
            {
                "status": "failed",
                "updated_at": utc_now_iso(),
            },
        )
        raise
    return {"product": product, "pipeline_run": run, "keywords": keywords}


def required_env_missing(
    config: Config,
    *,
    need_apify_ads: bool,
    need_topyappers: bool,
    need_enrichment: bool = False,
) -> list[str]:
    missing: list[str] = []
    if not config.supabase_url:
        missing.append("SUPABASE_URL")
    if not config.supabase_key:
        missing.append("SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY")
    if not config.claude_api_key:
        missing.append("CLAUDE_API_KEY")
    if need_apify_ads and not config.apify_api_key:
        missing.append("APIFY_API_KEY")
    if need_enrichment and not config.openrouter_api_key:
        missing.append("OPENROUTER_API_KEY")
    if need_topyappers and not config.topyappers_api_key:
        missing.append("TOPYAPPERS_API_KEY")
    return missing


def verify_database_state(
    *,
    supabase: Any,
    run_id: str,
    expected_paid_total: int,
    expected_organic_total: int,
    expect_apify_ads: bool,
    expect_topyappers: bool,
    expect_enrichment: bool = False,
) -> dict[str, Any]:
    keywords = supabase.select(
        "keywords",
        {
            "select": "keyword_text,source,target_paid_count,target_ugc_count",
            "run_id": f"eq.{run_id}",
            "active": "eq.true",
            "order": "created_at.asc",
        },
    )
    source_queries = select_by_run(supabase, run_id, "source_queries", "provider,endpoint,status,response_count")
    api_usage = select_by_run(supabase, run_id, "api_usage", "provider,endpoint,rate_limit")
    raw_payloads = select_by_run(supabase, run_id, "raw_payloads", "provider,endpoint,external_id")
    paid_ads = select_by_run(supabase, run_id, "paid_ads", "paid_ad_row_id,id,ad_id,headline,video,thumbnail,hook,analyzed_at")
    organic_items = select_by_run(supabase, run_id, "ugc_items", "external_id,video_id,video_url,views,subtitles")
    paid_ad_transcripts: list[dict[str, Any]] = []
    paid_ad_row_ids = [str(row.get("paid_ad_row_id")) for row in paid_ads if row.get("paid_ad_row_id")]
    if paid_ad_row_ids:
        paid_ad_transcripts = supabase.select(
            "paid_ad_transcripts",
            {
                "select": "paid_ad_row_id,transcript_source",
                "paid_ad_row_id": f"in.({','.join(paid_ad_row_ids)})",
            },
        )
    analyzed_paid_ads = [row for row in paid_ads if row.get("analyzed_at")]

    paid_allocated = sum(int(row.get("target_paid_count") or 0) for row in keywords)
    organic_allocated = sum(int(row.get("target_ugc_count") or 0) for row in keywords)
    failures: list[str] = []
    warnings: list[str] = []

    if not 3 <= len(keywords) <= 6:
        failures.append(f"expected 3-6 active keywords, got {len(keywords)}")
    if paid_allocated != expected_paid_total:
        failures.append(f"paid allocation {paid_allocated} != requested {expected_paid_total}")
    if organic_allocated != expected_organic_total:
        failures.append(f"organic allocation {organic_allocated} != requested {expected_organic_total}")
    if not any(str(row.get("provider", "")).startswith("claude") for row in api_usage):
        failures.append("missing Claude keyword-generation row in api_usage")
    if expect_apify_ads and not any(row.get("provider") == APIFY_ADS_PROVIDER for row in source_queries):
        failures.append("missing Apify paid-ad source_queries rows")
    if expect_topyappers and not any(row.get("provider") == "topyappers" for row in source_queries):
        failures.append("missing TopYappers source_queries rows")

    # Shortfalls are valid: provider APIs may return fewer rows than requested.
    if expect_apify_ads and len(paid_ads) < expected_paid_total:
        warnings.append(f"Apify returned {len(paid_ads)} paid ads for target {expected_paid_total}")
    if expect_topyappers and len(organic_items) < expected_organic_total:
        warnings.append(f"TopYappers returned {len(organic_items)} organic items for target {expected_organic_total}")
    if expect_enrichment and paid_ads and not analyzed_paid_ads:
        failures.append("enrichment ran but no paid_ads rows have analyzed_at set")
    if expect_enrichment and paid_ads and not paid_ad_transcripts:
        warnings.append("no paid_ad_transcripts rows were written (ads may have no speech or video fetch failed)")

    if failures:
        raise RuntimeError("; ".join(failures))

    return {
        "keywords": keywords,
        "counts": {
            "source_queries": len(source_queries),
            "api_usage": len(api_usage),
            "raw_payloads": len(raw_payloads),
            "paid_ads": len(paid_ads),
            "paid_ads_analyzed": len(analyzed_paid_ads),
            "paid_ad_transcripts": len(paid_ad_transcripts),
            "organic_items": len(organic_items),
        },
        "warnings": warnings,
    }


def select_by_run(supabase: Any, run_id: str, table: str, select: str) -> list[dict[str, Any]]:
    return supabase.select(
        table,
        {
            "select": select,
            "run_id": f"eq.{run_id}",
        },
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"smoke test failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
