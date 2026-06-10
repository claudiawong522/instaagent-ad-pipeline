from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .config import Config
from .foreplay import ingest_foreplay_ads
from .supabase_client import SupabaseClient
from .topyappers import ingest_topyappers_videos, ingest_topyappers_viral


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = Config.from_env()
    supabase = build_supabase(config, dry_run=getattr(args, "dry_run", False))

    if args.command == "init-run":
        result = init_run(args, supabase)
    elif args.command == "ingest-foreplay":
        result = ingest_foreplay_ads(
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
    elif args.command == "ingest-topyappers-viral":
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
    elif args.command == "ingest-topyappers-videos":
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
        parser.error("Unknown command")
        return 2

    print(json.dumps(to_jsonable(result), indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="InstaAgent ad pipeline Step 1/2 CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init-run", help="Create a product, pipeline run, and keywords.")
    init.add_argument("--product-name", required=True)
    init.add_argument("--category")
    init.add_argument("--target-market")
    init.add_argument("--notes")
    init.add_argument("--keyword", action="append", required=True)
    init.add_argument("--keyword-type", default="seed")
    init.add_argument("--target-paid-count", type=int, default=1000)
    init.add_argument("--target-ugc-count", type=int, default=2500)
    init.add_argument("--top-k", type=int, default=3)
    init.add_argument("--config-json", default="{}")
    init.add_argument("--dry-run", action="store_true")

    foreplay = subparsers.add_parser("ingest-foreplay", help="Ingest Foreplay paid ad candidates.")
    add_ingest_common_args(foreplay)
    foreplay.add_argument("--keyword", required=True)
    foreplay.add_argument("--target-count", type=int, default=1000)
    foreplay.add_argument("--page-size", type=int, default=250)

    viral = subparsers.add_parser(
        "ingest-topyappers-viral",
        help="Ingest URL-backed TopYappers viral-content candidates.",
    )
    add_ingest_common_args(viral)
    viral.add_argument("--keyword", required=True)
    viral.add_argument("--target-count", type=int, default=2500)
    viral.add_argument("--page-size", type=int, default=100)

    videos = subparsers.add_parser(
        "ingest-topyappers-videos",
        help="Ingest TopYappers metadata-only video records. This endpoint does not return video URLs.",
    )
    add_ingest_common_args(videos)
    videos.add_argument("--keyword", required=True)
    videos.add_argument("--target-count", type=int, default=2500)
    videos.add_argument("--page-size", type=int, default=100)

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


def build_supabase(config: Config, *, dry_run: bool) -> SupabaseClient | None:
    if dry_run:
        return None
    if not config.supabase_url or not config.supabase_key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required unless --dry-run is used.")
    return SupabaseClient(config.supabase_url, config.supabase_key)


def init_run(args: argparse.Namespace, supabase: SupabaseClient | None) -> dict[str, Any]:
    config = json.loads(args.config_json)
    product_payload = {
        "name": args.product_name,
        "category": args.category,
        "target_market": args.target_market,
        "notes": args.notes,
    }
    run_payload = {
        "status": "created",
        "config": config,
        "target_paid_count": args.target_paid_count,
        "target_ugc_count": args.target_ugc_count,
        "top_k": args.top_k,
    }

    if args.dry_run:
        return {
            "product": product_payload,
            "pipeline_run": run_payload,
            "keywords": [
                {"keyword_text": keyword, "keyword_type": args.keyword_type, "source": "manual", "active": True}
                for keyword in args.keyword
            ],
        }

    if supabase is None:
        raise RuntimeError("Supabase credentials are required unless --dry-run is used.")

    product = supabase.insert("products", product_payload)
    run_payload["product_id"] = product["id"]
    run = supabase.insert("pipeline_runs", run_payload)
    keywords = [
        supabase.insert(
            "keywords",
            {
                "run_id": run["id"],
                "keyword_text": keyword,
                "keyword_type": args.keyword_type,
                "source": "manual",
                "active": True,
            },
        )
        for keyword in args.keyword
    ]
    return {"product": product, "pipeline_run": run, "keywords": keywords}


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
    if hasattr(value, "__dict__"):
        return value.__dict__
    return value


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - CLI boundary
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
