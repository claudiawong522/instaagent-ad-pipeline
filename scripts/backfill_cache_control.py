#!/usr/bin/env python3
"""One-off backfill: re-stamp existing Supabase Storage media with a long Cache-Control.

Objects uploaded before the `Cache-Control: public, max-age=..., immutable` change carry
Supabase's default `no-cache`, so every `<video>` play (and every range request within a
play) cold-fetches the slow origin — slow to start and laggy mid-playback. Supabase Storage
has no "set metadata only" call, so we re-download each object and re-upload it (upsert),
which now stamps the cache header via SupabaseClient.upload_object.

Usage:
    python scripts/backfill_cache_control.py            # backfill everything
    python scripts/backfill_cache_control.py --limit 20 # first N rows per table (smoke test)
    python scripts/backfill_cache_control.py --dry-run  # list what would change, upload nothing
"""
from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from instaagent_pipeline.config import Config
from instaagent_pipeline.media import STORAGE_BUCKET
from instaagent_pipeline.supabase_client import HttpClientError, SupabaseClient, ssl_context

IMMUTABLE_CC = "public, max-age=31536000, immutable"
# The storage endpoint sits behind a load balancer that transiently 404s on stale replicas
# (same reason SupabaseClient retries RPCs); re-attempt before giving up on an object.
RETRY_STATUSES = frozenset({404, 502, 503, 504})

# (table, video_url_column, thumb_url_column)
TABLES = [
    ("organic_items", "storage_video_url", "storage_thumb_url"),
    ("paid_ads", "storage_video_url", "storage_thumb_url"),
]
PUBLIC_MARKER = f"/storage/v1/object/public/{STORAGE_BUCKET}/"


def storage_path(public_url: str) -> str | None:
    """Extract the in-bucket object path from a Supabase public URL, or None if not one."""
    idx = public_url.find(PUBLIC_MARKER)
    if idx == -1:
        return None
    return public_url[idx + len(PUBLIC_MARKER):]


def download(url: str, timeout: int = 120) -> bytes:
    req = Request(url, headers={"User-Agent": "instaagent-backfill/0.1"})
    with urlopen(req, timeout=timeout, context=ssl_context()) as resp:
        return resp.read()


def already_immutable(public_url: str) -> bool:
    """True if the object's ORIGIN already serves the immutable cache header. A cache-busting
    query forces a fresh origin fetch (CDN edge copies can lag), making the check reliable so
    re-runs skip finished objects."""
    try:
        req = Request(f"{public_url}?cbchk=1", method="HEAD")
        with urlopen(req, timeout=30, context=ssl_context()) as resp:
            return "immutable" in (resp.headers.get("cache-control") or "")
    except HTTPError:
        return False


def restamp(sb: SupabaseClient, public_url: str, content_type: str, *, dry_run: bool) -> str:
    path = storage_path(public_url)
    if path is None:
        return "skip (not a storage URL)"
    if already_immutable(public_url):
        return "skip (already immutable)"
    if dry_run:
        return f"would re-upload {path}"
    data = download(public_url)
    last: Exception | None = None
    for attempt in range(6):  # transient 404/5xx from a stale storage replica
        try:
            sb.upload_object(STORAGE_BUCKET, path, data, content_type)
            return f"ok {path} ({len(data)} bytes)"
        except HttpClientError as exc:
            if exc.status in RETRY_STATUSES and attempt < 5:
                last = exc
                time.sleep(0.5 * (attempt + 1))
                continue
            raise
    raise last  # unreachable, but keeps the type checker happy


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="max rows per table")
    ap.add_argument("--workers", type=int, default=12, help="concurrent download/upload workers")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg = Config.from_env()
    if not cfg.supabase_url or not cfg.supabase_key:
        print("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set in env", file=sys.stderr)
        return 1
    sb = SupabaseClient(cfg.supabase_url, cfg.supabase_key)

    # Each object is one (id, column, content_type, url) job. Downloads dominate wall-clock and
    # the origin is slow, so run them concurrently — the work is entirely I/O-bound.
    jobs: list[tuple[str, str, str, str]] = []
    for table, video_col, thumb_col in TABLES:
        params = {
            "select": f"id,{video_col},{thumb_col}",
            video_col: "not.is.null",
            "limit": str(args.limit or 100000),
        }
        rows = sb.select(table, params)
        print(f"== {table}: {len(rows)} rows with a stored video ==", flush=True)
        for row in rows:
            for col, ctype in ((video_col, "video/mp4"), (thumb_col, "image/jpeg")):
                if row.get(col):
                    jobs.append((row["id"], col, ctype, row[col]))

    done = failed = 0

    def work(job: tuple[str, str, str, str]) -> tuple[str, bool]:
        rid, col, ctype, url = job
        try:
            return f"  {rid} {col}: {restamp(sb, url, ctype, dry_run=args.dry_run)}", True
        except Exception as exc:  # resilient: log + continue
            return f"  {rid} {col}: FAILED {exc}", False

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for msg, ok in pool.map(work, jobs):
            print(msg, file=sys.stdout if ok else sys.stderr, flush=True)
            if ok:
                done += 1
            else:
                failed += 1

    print(f"\nDone. {done} object(s) processed, {failed} failed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
