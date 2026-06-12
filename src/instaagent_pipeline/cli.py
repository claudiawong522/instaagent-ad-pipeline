from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .apify_ads import ingest_apify_ads
from .apify_transcripts import (
    backfill_ugc_transcripts_from_provider_subtitles,
    backfill_ugc_transcripts_with_apify,
)
from .config import Config
from .ad_enrichment import enrich_paid_ads
from .embeddings import embed_items
from .keywords import (
    active_keyword_allocations,
    allocate_manual_keywords,
    generate_keyword_allocations,
    insert_keyword_allocations,
)
from .ingestion import utc_now_iso
from .supabase_client import SupabaseClient
from .topyappers import ingest_topyappers_videos, ingest_topyappers_viral


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = Config.from_env()
    dry_run = getattr(args, "dry_run", False)
    dry_run_needs_supabase = args.command in {"backfill-ugc-transcripts", "enrich-paid-ads", "embed-items"}
    supabase = build_supabase(config, dry_run=dry_run and not dry_run_needs_supabase)

    if args.command == "init-run":
        result = init_run(args, supabase, config)
    elif args.command == "ingest-apify-ads":
        if args.keyword:
            result = ingest_apify_ads(
                config=config,
                supabase=supabase,
                run_id=args.run_id,
                keyword=args.keyword,
                target_count=args.target_count,
                page_size=getattr(args, "page_size", args.target_count),
                dry_run=args.dry_run,
                input_json=args.input_json,
                extra_params=parse_extra_params(args.extra_param),
            )
        else:
            result = ingest_allocated_keywords(
                config=config,
                supabase=supabase,
                args=args,
                target_field="target_paid_count",
                ingest_func=ingest_apify_ads,
            )
        result = with_paid_ad_enrichment(
            result,
            config=config,
            supabase=supabase,
            args=args,
        )
    elif args.command == "ingest-topyappers-viral":
        if args.keyword:
            result = ingest_topyappers_viral(
                config=config,
                supabase=supabase,
                run_id=args.run_id,
                keyword=args.keyword,
                target_count=args.target_count,
                page_size=args.page_size,
                dry_run=args.dry_run,
                input_json=args.input_json,
                extra_params=parse_extra_params(args.extra_param),
            )
        else:
            result = ingest_allocated_keywords(
                config=config,
                supabase=supabase,
                args=args,
                target_field="target_ugc_count",
                ingest_func=ingest_topyappers_viral,
            )
        result = with_ugc_transcript_backfill(
            result,
            config=config,
            supabase=supabase,
            args=args,
        )
    elif args.command == "ingest-topyappers-videos":
        if args.keyword:
            result = ingest_topyappers_videos(
                config=config,
                supabase=supabase,
                run_id=args.run_id,
                keyword=args.keyword,
                target_count=args.target_count,
                page_size=args.page_size,
                dry_run=args.dry_run,
                input_json=args.input_json,
                extra_params=parse_extra_params(args.extra_param),
            )
        else:
            result = ingest_allocated_keywords(
                config=config,
                supabase=supabase,
                args=args,
                target_field="target_ugc_count",
                ingest_func=ingest_topyappers_videos,
            )
        result = with_ugc_transcript_backfill(
            result,
            config=config,
            supabase=supabase,
            args=args,
        )
    elif args.command == "backfill-ugc-transcripts":
        provider_subtitles = backfill_ugc_transcripts_from_provider_subtitles(
            supabase=supabase,
            run_id=args.run_id,
            limit=args.limit,
            dry_run=args.dry_run,
        )
        apify = None
        if not args.skip_apify:
            apify = backfill_ugc_transcripts_with_apify(
                config=config,
                supabase=supabase,
                run_id=args.run_id,
                limit=args.limit,
                dry_run=args.dry_run,
                input_json=args.input_json,
                timeout=args.timeout,
            )
        result = {
            "provider_subtitles": provider_subtitles,
            "apify": apify,
        }
    elif args.command == "enrich-paid-ads":
        result = enrich_paid_ads(
            config=config,
            supabase=supabase,
            run_id=args.run_id,
            limit=args.limit,
            dry_run=args.dry_run,
            input_json=args.input_json,
            timeout=args.timeout,
        )
    elif args.command == "embed-items":
        result = embed_items(
            config=config,
            supabase=supabase,
            run_id=args.run_id,
            source=args.source,
            limit=args.limit,
            dry_run=args.dry_run,
            model=args.model,
            input_json=args.input_json,
            timeout=args.timeout,
        )
    else:
        parser.error("Unknown command")
        return 2

    print(json.dumps(to_jsonable(result), indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="InstaAgent ad pipeline CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init-run", help="Create a product, pipeline run, and keywords.")
    init.add_argument("--product-name", required=True)
    init.add_argument("--category")
    init.add_argument("--target-market")
    init.add_argument("--notes")
    init.add_argument("--campaign-guidelines")
    init.add_argument("--keyword", action="append")
    init.add_argument("--keyword-type", default="seed")
    init.add_argument("--target-paid-count", type=int, default=1000)
    init.add_argument("--target-ugc-count", type=int, default=2500)
    init.add_argument("--top-k", type=int, default=3)
    init.add_argument("--config-json", default="{}")
    init.add_argument("--dry-run", action="store_true")

    apify_ads = subparsers.add_parser("ingest-apify-ads", help="Ingest Apify Meta Ad Library paid ad candidates.")
    add_ingest_common_args(apify_ads)
    add_paid_ad_enrichment_args(apify_ads)
    apify_ads.add_argument("--keyword", help="Optional manual keyword. Omit to use stored keyword allocations.")
    apify_ads.add_argument("--target-count", type=int, default=1000)

    viral = subparsers.add_parser(
        "ingest-topyappers-viral",
        help="Ingest URL-backed TopYappers viral-content candidates.",
    )
    add_ingest_common_args(viral)
    add_ugc_transcript_args(viral)
    viral.add_argument("--keyword", help="Optional manual keyword. Omit to use stored keyword allocations.")
    viral.add_argument("--target-count", type=int, default=2500)
    viral.add_argument("--page-size", type=int, default=100)

    videos = subparsers.add_parser(
        "ingest-topyappers-videos",
        help="Ingest TopYappers metadata-only video records. This endpoint does not return video URLs.",
    )
    add_ingest_common_args(videos)
    add_ugc_transcript_args(videos)
    videos.add_argument("--keyword", help="Optional manual keyword. Omit to use stored keyword allocations.")
    videos.add_argument("--target-count", type=int, default=2500)
    videos.add_argument("--page-size", type=int, default=100)

    transcripts = subparsers.add_parser(
        "backfill-ugc-transcripts",
        help="Backfill missing UGC transcripts from public social video URLs using Apify.",
    )
    transcripts.add_argument("--run-id", required=True)
    transcripts.add_argument("--limit", type=int, default=100)
    transcripts.add_argument("--timeout", type=int, default=300)
    transcripts.add_argument("--dry-run", action="store_true")
    transcripts.add_argument("--skip-apify", action="store_true")
    transcripts.add_argument(
        "--input-json",
        type=Path,
        help="Use a saved Apify dataset response instead of calling Apify. Intended for one-row tests.",
    )

    enrich = subparsers.add_parser(
        "enrich-paid-ads",
        help="Transcribe and analyze paid ad videos via OpenRouter into paid_ad_transcripts and paid_ads columns.",
    )
    enrich.add_argument("--run-id", required=True)
    enrich.add_argument("--limit", type=int, default=100)
    enrich.add_argument("--timeout", type=int, default=300)
    enrich.add_argument("--dry-run", action="store_true")
    enrich.add_argument(
        "--input-json",
        type=Path,
        help="Use a saved OpenRouter chat-completions response instead of calling OpenRouter. Intended for one-row tests.",
    )

    embed = subparsers.add_parser(
        "embed-items",
        help="Generate icp/format/hook embeddings for analyzed items via Voyage AI into item_embeddings.",
    )
    embed.add_argument("--run-id", required=True)
    embed.add_argument("--source", choices=["paid", "ugc", "all"], default="all")
    embed.add_argument("--limit", type=int, default=1000, help="Maximum items to fetch per source.")
    embed.add_argument("--model", help="Voyage embedding model. Defaults to EMBEDDING_MODEL or voyage-4-lite.")
    embed.add_argument("--timeout", type=int, default=120)
    embed.add_argument("--dry-run", action="store_true")
    embed.add_argument(
        "--input-json",
        type=Path,
        help="Use a saved Voyage embeddings response instead of calling Voyage. Intended for one-batch tests.",
    )

    return parser


def add_ingest_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--input-json", type=Path)
    parser.add_argument(
        "--extra-param",
        action="append",
        default=[],
        help="Extra API param as key=value. Repeatable. Values are JSON-decoded when possible.",
    )


def add_ugc_transcript_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--skip-transcript-backfill",
        action="store_true",
        help="Do not copy TopYappers subtitles or call Apify after live TopYappers ingestion.",
    )
    parser.add_argument(
        "--transcript-limit",
        type=int,
        help="Maximum number of rows to process in each transcript stage. Defaults to the number fetched.",
    )
    parser.add_argument(
        "--transcript-timeout",
        type=int,
        default=300,
        help="Apify actor timeout in seconds per video URL.",
    )


def add_paid_ad_enrichment_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--skip-enrichment",
        action="store_true",
        help="Do not transcribe and analyze paid ad videos via OpenRouter after live ingestion.",
    )
    parser.add_argument(
        "--enrichment-limit",
        type=int,
        help="Maximum number of paid ads to enrich. Defaults to the number fetched.",
    )
    parser.add_argument(
        "--enrichment-timeout",
        type=int,
        default=300,
        help="OpenRouter request timeout in seconds per ad video (covers the video download too).",
    )


def build_supabase(config: Config, *, dry_run: bool) -> SupabaseClient | None:
    if dry_run:
        return None
    if not config.supabase_url or not config.supabase_key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required unless --dry-run is used.")
    return SupabaseClient(config.supabase_url, config.supabase_key)


def with_ugc_transcript_backfill(
    ingestion_result: Any,
    *,
    config: Config,
    supabase: SupabaseClient | None,
    args: argparse.Namespace,
) -> Any:
    if args.dry_run or args.skip_transcript_backfill:
        return ingestion_result
    if supabase is None:
        raise RuntimeError("Supabase credentials are required for transcript backfill.")

    transcript_limit = args.transcript_limit or fetched_count(ingestion_result)
    if transcript_limit < 1:
        return {"ingestion": ingestion_result, "transcripts": None}

    provider_subtitles = backfill_ugc_transcripts_from_provider_subtitles(
        supabase=supabase,
        run_id=args.run_id,
        limit=transcript_limit,
        dry_run=False,
    )
    apify = backfill_ugc_transcripts_with_apify(
        config=config,
        supabase=supabase,
        run_id=args.run_id,
        limit=transcript_limit,
        dry_run=False,
        input_json=None,
        timeout=args.transcript_timeout,
    )
    return {
        "ingestion": ingestion_result,
        "transcripts": {
            "provider_subtitles": provider_subtitles,
            "apify": apify,
        },
    }


def with_paid_ad_enrichment(
    ingestion_result: Any,
    *,
    config: Config,
    supabase: SupabaseClient | None,
    args: argparse.Namespace,
) -> Any:
    if args.dry_run or args.skip_enrichment:
        return ingestion_result
    if supabase is None:
        raise RuntimeError("Supabase credentials are required for paid ad enrichment.")

    enrichment_limit = args.enrichment_limit or fetched_count(ingestion_result)
    if enrichment_limit < 1:
        return {"ingestion": ingestion_result, "enrichment": None}

    enrichment = enrich_paid_ads(
        config=config,
        supabase=supabase,
        run_id=args.run_id,
        limit=enrichment_limit,
        dry_run=False,
        input_json=None,
        timeout=args.enrichment_timeout,
    )
    return {"ingestion": ingestion_result, "enrichment": enrichment}


def fetched_count(result: Any) -> int:
    if isinstance(result, dict):
        return int(result.get("fetched") or 0)
    return int(getattr(result, "fetched", 0) or 0)


def init_run(args: argparse.Namespace, supabase: SupabaseClient | None, config: Config) -> dict[str, Any]:
    run_config = json.loads(args.config_json)
    if args.campaign_guidelines:
        run_config["campaign_guidelines"] = args.campaign_guidelines
    product_payload = {
        "name": args.product_name,
        "category": args.category,
        "target_market": args.target_market,
        "notes": args.notes,
    }
    run_payload = {
        "status": "created",
        "config": run_config,
        "target_paid_count": args.target_paid_count,
        "target_ugc_count": args.target_ugc_count,
        "top_k": args.top_k,
    }
    if args.dry_run:
        if args.keyword:
            allocations = allocate_manual_keywords(
                args.keyword,
                target_paid_count=args.target_paid_count,
                target_ugc_count=args.target_ugc_count,
                keyword_type=args.keyword_type,
            )
        else:
            generation_result = generate_keyword_allocations(
                config=config,
                dry_run=True,
                product_name=args.product_name,
                category=args.category,
                target_market=args.target_market,
                notes=args.notes,
                campaign_guidelines=args.campaign_guidelines,
                target_paid_count=args.target_paid_count,
                target_ugc_count=args.target_ugc_count,
            )
            allocations = generation_result.allocations
        return {
            "product": product_payload,
            "pipeline_run": run_payload,
            "keywords": [allocation.__dict__ for allocation in allocations],
        }

    if supabase is None:
        raise RuntimeError("Supabase credentials are required unless --dry-run is used.")

    product = supabase.insert("products", product_payload)
    run_payload["product_id"] = product["id"]
    run = supabase.insert("pipeline_runs", run_payload)
    try:
        if args.keyword:
            allocations = allocate_manual_keywords(
                args.keyword,
                target_paid_count=args.target_paid_count,
                target_ugc_count=args.target_ugc_count,
                keyword_type=args.keyword_type,
            )
        else:
            generation_result = generate_keyword_allocations(
                config=config,
                supabase=supabase,
                dry_run=args.dry_run,
                run_id=run["id"],
                product_name=args.product_name,
                category=args.category,
                target_market=args.target_market,
                notes=args.notes,
                campaign_guidelines=args.campaign_guidelines,
                target_paid_count=args.target_paid_count,
                target_ugc_count=args.target_ugc_count,
            )
            allocations = generation_result.allocations
        keywords = insert_keyword_allocations(supabase, run_id=run["id"], allocations=allocations)
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


def ingest_allocated_keywords(
    *,
    config: Config,
    supabase: SupabaseClient | None,
    args: argparse.Namespace,
    target_field: str,
    ingest_func: Any,
) -> dict[str, Any]:
    if args.dry_run:
        raise RuntimeError("--keyword is required with --dry-run because dry-run cannot load stored keywords.")
    if supabase is None:
        raise RuntimeError("Supabase credentials are required to load stored keyword allocations.")

    rows = active_keyword_allocations(supabase, args.run_id)
    if not rows:
        raise RuntimeError(f"No active keywords found for run {args.run_id}.")

    details: list[dict[str, Any]] = []
    fetched = 0
    written = 0
    extra_params = parse_extra_params(args.extra_param)
    for row in rows:
        keyword = str(row.get("keyword_text") or "").strip()
        target_count = int(row.get(target_field) or 0)
        if not keyword or target_count <= 0:
            continue
        result = ingest_func(
            config=config,
            supabase=supabase,
            run_id=args.run_id,
            keyword=keyword,
            target_count=target_count,
            page_size=int(getattr(args, "page_size", target_count) or target_count),
            dry_run=False,
            input_json=args.input_json,
            extra_params=extra_params,
        )
        fetched += result.fetched
        written += result.written
        details.append(
            {
                "keyword": keyword,
                "target_count": target_count,
                "fetched": result.fetched,
                "written": result.written,
            }
        )

    return {"fetched": fetched, "written": written, "keywords": details}


def parse_extra_params(values: list[str]) -> dict[str, Any]:
    params: dict[str, Any] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"Expected --extra-param key=value, got {value!r}")
        key, raw = value.split("=", 1)
        try:
            params[key] = json.loads(raw)
        except json.JSONDecodeError:
            params[key] = raw
    return params


def to_jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if hasattr(value, "__dict__"):
        return {key: to_jsonable(item) for key, item in value.__dict__.items()}
    return value


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - CLI boundary
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
