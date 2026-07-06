#!/usr/bin/env python3
"""Live end-to-end smoke test: init-run → tiny ingest → enrich → embed → search.

Hits the REAL Apify / OpenRouter / Voyage / Supabase APIs and spends real money
(a few cents at the default counts), so it refuses to run without --confirm-live.
Creates its own throwaway run; nothing existing is touched. Stages can be skipped
individually to isolate a failure (e.g. --skip-paid to smoke only the organic leg).

    PYTHONPATH=src python3 scripts/smoke_pipeline.py --confirm-live
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from instaagent_pipeline.api.search import search_ads
from instaagent_pipeline.apify_ads import ingest_apify_ads
from instaagent_pipeline.apify_organic import ingest_tiktok
from instaagent_pipeline.audience_enrichment import enrich_audience
from instaagent_pipeline.cli import build_supabase
from instaagent_pipeline.config import Config
from instaagent_pipeline.embeddings import ALL_SPACES, embed_items
from instaagent_pipeline.orchestration import init_run
from instaagent_pipeline.organic_enrichment import enrich_organic_items
from instaagent_pipeline.paid_enrichment import enrich_paid_ads


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-live", action="store_true", help="Required: this spends real API credits.")
    parser.add_argument("--keyword", default="skincare", help="Single search keyword for both ingests.")
    parser.add_argument("--count", type=int, default=3, help="Items to fetch per platform (keep tiny).")
    parser.add_argument("--enrich-limit", type=int, default=2, help="Videos to enrich per kind.")
    parser.add_argument("--skip-paid", action="store_true", help="Skip the Meta Ad Library leg.")
    parser.add_argument("--skip-organic", action="store_true", help="Skip the TikTok leg.")
    parser.add_argument("--skip-enrichment", action="store_true", help="Ingest only; no vision/embed/search.")
    parser.add_argument("--query", default="skincare routine", help="Search query for the final check.")
    return parser.parse_args()


def stage(name: str, result: object) -> None:
    print(f"\n=== {name} ===")
    print(json.dumps(result, indent=2, default=lambda o: getattr(o, "__dict__", str(o)))[:2000])


def main() -> int:
    args = parse_args()
    if not args.confirm_live:
        raise SystemExit("Refusing to run a live API/DB smoke test without --confirm-live.")

    config = Config.from_env()
    required = {"SUPABASE_URL/KEY": config.supabase_url and config.supabase_key}
    if not (args.skip_paid and args.skip_organic):
        required["APIFY_API_KEY"] = config.apify_api_key
    if not args.skip_enrichment:
        required["OPENROUTER_API_KEY"] = config.openrouter_api_key
        required["VOYAGE_API_KEY"] = config.voyage_api_key
        required["CLAUDE_API_KEY (keyword gen)"] = config.claude_api_key
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise SystemExit(f"Missing required env values: {', '.join(missing)}")

    supabase = build_supabase(config, dry_run=False)

    init = init_run(
        config=config,
        supabase=supabase,
        product_name="Smoke Test Product",
        category="skincare",
        target_market="US",
        notes="throwaway smoke-test run; safe to delete",
        campaign_guidelines=None,
        keywords=[args.keyword],  # manual keyword — no Claude call needed for seeding
        keyword_type="seed",
        target_paid_count=args.count,
        target_organic_count=args.count,
        target_tiktok_count=args.count,
        top_k=1,
        run_config={"smoke_test": True},
        dry_run=False,
    )
    run_id = str(init["pipeline_run"]["id"])
    stage("init-run", {"run_id": run_id, "keywords": [k.get("keyword_text") for k in init["keywords"]]})

    if not args.skip_paid:
        stage("ingest paid ads", ingest_apify_ads(
            config=config, supabase=supabase, run_id=run_id, keyword=args.keyword,
            target_count=args.count, page_size=args.count, dry_run=False,
        ))
    if not args.skip_organic:
        stage("ingest tiktok", ingest_tiktok(
            config=config, supabase=supabase, run_id=run_id, keyword=args.keyword,
            target_count=args.count, dry_run=False,
        ))

    if args.skip_enrichment:
        print(f"\nDone (ingest only). run_id={run_id}")
        return 0

    if not args.skip_paid:
        stage("enrich paid", enrich_paid_ads(
            config=config, supabase=supabase, run_id=run_id, limit=args.enrich_limit, dry_run=False,
        ))
    if not args.skip_organic:
        stage("enrich organic", enrich_organic_items(
            config=config, supabase=supabase, run_id=run_id, limit=args.enrich_limit, dry_run=False,
        ))
    stage("enrich audience", enrich_audience(
        config=config, supabase=supabase, run_id=run_id, source="all", dry_run=False,
    ))
    stage("embed", embed_items(
        config=config, supabase=supabase, run_id=run_id, spaces=ALL_SPACES, dry_run=False,
    ))
    results = search_ads(config, supabase, query=args.query, run_id=run_id)
    stage("search", {"query": args.query, "count": len(results), "top": results[:2]})

    print(f"\nSmoke test finished. run_id={run_id} (delete its pipeline_runs row to clean up; cascades).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
