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

from instaagent_pipeline.cli import build_supabase, ingest_allocated_keywords, init_run
from instaagent_pipeline.config import Config
from instaagent_pipeline.foreplay import ingest_foreplay_ads
from instaagent_pipeline.topyappers import ingest_topyappers_viral


def main() -> int:
    args = parse_args()
    if not args.confirm_live:
        raise SystemExit("Refusing to run live API/DB smoke test without --confirm-live.")

    config = Config.from_env()
    missing = required_env_missing(config, need_foreplay=not args.skip_foreplay, need_topyappers=not args.skip_topyappers)
    if missing:
        raise SystemExit(f"Missing required env values: {', '.join(missing)}")

    supabase = build_supabase(config, dry_run=False)
    if supabase is None:
        raise SystemExit("Supabase client was not created.")

    init_result = init_run(
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
    run_id = init_result["pipeline_run"]["id"]

    foreplay_result = None
    topyappers_result = None
    if not args.skip_foreplay:
        foreplay_result = ingest_allocated_keywords(
            config=config,
            supabase=supabase,
            args=SimpleNamespace(
                run_id=run_id,
                dry_run=False,
                page_size=args.foreplay_page_size,
                input_json=None,
                extra_param=args.extra_param,
            ),
            target_field="target_paid_count",
            ingest_func=ingest_foreplay_ads,
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
        expected_ugc_total=args.target_ugc_count,
        expect_foreplay=not args.skip_foreplay,
        expect_topyappers=not args.skip_topyappers,
    )
    summary = {
        "run_id": run_id,
        "product": init_result["product"],
        "keywords": verification["keywords"],
        "foreplay": foreplay_result,
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
    parser.add_argument("--product-name", default="Smoke test gentle cleanser")
    parser.add_argument("--category", default="skincare")
    parser.add_argument("--target-market", default="US skincare buyers")
    parser.add_argument("--notes", default="Smoke test record. Safe to delete.")
    parser.add_argument(
        "--campaign-guidelines",
        default="Find competitor paid ads and UGC videos for a gentle cleanser launch.",
    )
    parser.add_argument("--target-paid-count", type=int, default=3)
    parser.add_argument("--target-ugc-count", type=int, default=3)
    parser.add_argument("--foreplay-page-size", type=int, default=1)
    parser.add_argument("--topyappers-page-size", type=int, default=1)
    parser.add_argument("--skip-foreplay", action="store_true")
    parser.add_argument("--skip-topyappers", action="store_true")
    parser.add_argument(
        "--extra-param",
        action="append",
        default=[],
        help="Extra provider API param as key=value. Passed to both provider ingestion stages.",
    )
    return parser.parse_args()


def required_env_missing(config: Config, *, need_foreplay: bool, need_topyappers: bool) -> list[str]:
    missing: list[str] = []
    if not config.supabase_url:
        missing.append("SUPABASE_URL")
    if not config.supabase_key:
        missing.append("SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY")
    if not config.claude_api_key:
        missing.append("CLAUDE_API_KEY")
    if need_foreplay and not config.foreplay_api_key:
        missing.append("FOREPLAY_API_KEY")
    if need_topyappers and not config.topyappers_api_key:
        missing.append("TOPYAPPERS_API_KEY")
    return missing


def verify_database_state(
    *,
    supabase: Any,
    run_id: str,
    expected_paid_total: int,
    expected_ugc_total: int,
    expect_foreplay: bool,
    expect_topyappers: bool,
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
    paid_ads = select_by_run(supabase, run_id, "paid_ads", "id,ad_id,headline,video,thumbnail")
    ugc_items = select_by_run(supabase, run_id, "ugc_items", "external_id,video_id,video_url,views,subtitles")

    paid_allocated = sum(int(row.get("target_paid_count") or 0) for row in keywords)
    ugc_allocated = sum(int(row.get("target_ugc_count") or 0) for row in keywords)
    failures: list[str] = []
    warnings: list[str] = []

    if not 3 <= len(keywords) <= 6:
        failures.append(f"expected 3-6 active keywords, got {len(keywords)}")
    if paid_allocated != expected_paid_total:
        failures.append(f"paid allocation {paid_allocated} != requested {expected_paid_total}")
    if ugc_allocated != expected_ugc_total:
        failures.append(f"UGC allocation {ugc_allocated} != requested {expected_ugc_total}")
    if not any(str(row.get("provider", "")).startswith("claude") for row in api_usage):
        failures.append("missing Claude keyword-generation row in api_usage")
    if expect_foreplay and not any(row.get("provider") == "foreplay" for row in source_queries):
        failures.append("missing Foreplay source_queries rows")
    if expect_topyappers and not any(row.get("provider") == "topyappers" for row in source_queries):
        failures.append("missing TopYappers source_queries rows")

    # Shortfalls are valid: provider APIs may return fewer rows than requested.
    if expect_foreplay and len(paid_ads) < expected_paid_total:
        warnings.append(f"Foreplay returned {len(paid_ads)} paid ads for target {expected_paid_total}")
    if expect_topyappers and len(ugc_items) < expected_ugc_total:
        warnings.append(f"TopYappers returned {len(ugc_items)} UGC items for target {expected_ugc_total}")

    if failures:
        raise RuntimeError("; ".join(failures))

    return {
        "keywords": keywords,
        "counts": {
            "source_queries": len(source_queries),
            "api_usage": len(api_usage),
            "raw_payloads": len(raw_payloads),
            "paid_ads": len(paid_ads),
            "ugc_items": len(ugc_items),
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
