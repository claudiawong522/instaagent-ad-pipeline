from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .config import Config
from .http_client import HttpClientError, request_json
from .ingestion import complete_query, log_api_usage, log_failed_query, start_query
from .supabase_client import SupabaseClient


APIFY_PROVIDER = "apify"
ANOXVANZI_ACTOR_ID = "tictechid~anoxvanzi-transcriber"
ANOXVANZI_ACTOR_NAME = "tictechid/anoxvanzi-transcriber"
ANOXVANZI_ENDPOINT = f"/acts/{ANOXVANZI_ACTOR_ID}/run-sync-get-dataset-items"
ANOXVANZI_TRANSCRIPT_SOURCE = f"apify:{ANOXVANZI_ACTOR_NAME}"
TOPYAPPERS_TRANSCRIPT_SOURCE = "topyappers:subtitles"

SUPPORTED_VIDEO_HOSTS = {
    "instagram.com",
    "tiktok.com",
    "youtube.com",
    "youtu.be",
    "facebook.com",
    "fb.watch",
}

TIMESTAMPED_SEGMENT_RE = re.compile(
    r"\[(?P<start>\d+(?:\.\d+)?)s\s*-\s*(?P<end>\d+(?:\.\d+)?)s\]\s*"
    r"(?P<text>.*?)(?=\s*\[\d+(?:\.\d+)?s\s*-\s*\d+(?:\.\d+)?s\]|\s*$)",
    re.DOTALL,
)


@dataclass
class UGCTranscriptCandidate:
    ugc_item_id: str
    external_id: str
    video_url: str
    source: str | None


@dataclass
class TranscriptBackfillResult:
    candidates: int
    attempted: int = 0
    written: int = 0
    skipped_existing: int = 0
    skipped_unsupported: int = 0
    failed: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ProviderSubtitleBackfillResult:
    candidates: int
    written: int = 0
    skipped_existing: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)


def backfill_ugc_transcripts_from_provider_subtitles(
    *,
    supabase: SupabaseClient | None,
    run_id: str,
    limit: int,
    dry_run: bool,
) -> ProviderSubtitleBackfillResult:
    if supabase is None:
        raise RuntimeError("Supabase credentials are required to load UGC subtitle candidates.")
    if limit < 1:
        raise ValueError("--limit must be greater than 0.")

    existing_ids = existing_ugc_transcript_item_ids(
        supabase,
        transcript_source=TOPYAPPERS_TRANSCRIPT_SOURCE,
    )
    rows = supabase.select(
        "ugc_items",
        {
            "select": "id,external_id,subtitles",
            "run_id": f"eq.{run_id}",
            "subtitles": "not.is.null",
            "order": "saved_to_supabase_at.asc",
            "limit": str(limit * 5),
        },
    )

    result = ProviderSubtitleBackfillResult(candidates=0)
    for row in rows:
        ugc_item_id = str(row.get("id") or "")
        subtitles = str(row.get("subtitles") or "").strip()
        if not ugc_item_id or not subtitles:
            continue
        if ugc_item_id in existing_ids:
            result.skipped_existing += 1
            continue

        result.candidates += 1
        detail = {
            "ugc_item_id": ugc_item_id,
            "external_id": row.get("external_id"),
        }
        if dry_run:
            result.details.append({**detail, "action": "would_copy_provider_subtitles"})
        else:
            upsert_or_insert_transcript(
                supabase,
                {
                    "ugc_item_id": ugc_item_id,
                    "transcript_text": subtitles,
                    "transcript_segments": None,
                    "transcript_source": TOPYAPPERS_TRANSCRIPT_SOURCE,
                },
            )
            result.written += 1
            result.details.append({**detail, "status": "written"})

        if result.candidates >= limit:
            break

    return result


def backfill_ugc_transcripts_with_apify(
    *,
    config: Config,
    supabase: SupabaseClient | None,
    run_id: str,
    limit: int,
    dry_run: bool,
    input_json: Path | None = None,
    timeout: int = 300,
) -> TranscriptBackfillResult:
    if supabase is None:
        raise RuntimeError("Supabase credentials are required to load UGC transcript candidates.")
    if limit < 1:
        raise ValueError("--limit must be greater than 0.")

    candidates, skipped_existing, skipped_unsupported = ugc_transcript_candidates(
        supabase,
        run_id=run_id,
        limit=limit,
    )
    result = TranscriptBackfillResult(
        candidates=len(candidates),
        skipped_existing=skipped_existing,
        skipped_unsupported=skipped_unsupported,
    )

    if dry_run:
        result.details = [
            {
                "ugc_item_id": candidate.ugc_item_id,
                "external_id": candidate.external_id,
                "source": candidate.source,
                "video_url": candidate.video_url,
                "action": "would_transcribe",
            }
            for candidate in candidates
        ]
        return result

    if not config.apify_api_key and input_json is None:
        raise RuntimeError("APIFY_API_KEY is required unless --input-json is used.")

    for candidate in candidates:
        result.attempted += 1
        try:
            written = transcribe_candidate(
                config=config,
                supabase=supabase,
                run_id=run_id,
                candidate=candidate,
                input_json=input_json,
                timeout=timeout,
            )
        except (HttpClientError, RuntimeError) as exc:
            result.failed += 1
            result.details.append(
                {
                    "ugc_item_id": candidate.ugc_item_id,
                    "external_id": candidate.external_id,
                    "status": "failed",
                    "error": str(exc),
                }
            )
            continue

        if written:
            result.written += 1
            status = "written"
        else:
            result.failed += 1
            status = "no_transcript"
        result.details.append(
            {
                "ugc_item_id": candidate.ugc_item_id,
                "external_id": candidate.external_id,
                "status": status,
            }
        )

    return result


def ugc_transcript_candidates(
    supabase: SupabaseClient,
    *,
    run_id: str,
    limit: int,
) -> tuple[list[UGCTranscriptCandidate], int, int]:
    rows = supabase.select(
        "ugc_items",
        {
            "select": "id,external_id,source,video_url,subtitles",
            "run_id": f"eq.{run_id}",
            "video_url": "not.is.null",
            "or": "(subtitles.is.null,subtitles.eq.)",
            "order": "saved_to_supabase_at.asc",
            "limit": str(max(limit * 5, limit)),
        },
    )
    existing_ids = existing_ugc_transcript_item_ids(supabase)

    candidates: list[UGCTranscriptCandidate] = []
    skipped_existing = 0
    skipped_unsupported = 0
    for row in rows:
        ugc_item_id = str(row.get("id") or "")
        video_url = str(row.get("video_url") or "")
        if not ugc_item_id or not video_url:
            continue
        if ugc_item_id in existing_ids:
            skipped_existing += 1
            continue
        if not is_supported_social_video_url(video_url):
            skipped_unsupported += 1
            continue

        candidates.append(
            UGCTranscriptCandidate(
                ugc_item_id=ugc_item_id,
                external_id=str(row.get("external_id") or ""),
                video_url=video_url,
                source=row.get("source"),
            )
        )
        if len(candidates) >= limit:
            break

    return candidates, skipped_existing, skipped_unsupported


def existing_ugc_transcript_item_ids(
    supabase: SupabaseClient,
    transcript_source: str | None = None,
) -> set[str]:
    params: dict[str, Any] = {
        "select": "ugc_item_id",
        "limit": "10000",
    }
    if transcript_source is not None:
        params["transcript_source"] = f"eq.{transcript_source}"
    rows = supabase.select("ugc_transcripts", params)
    return {str(row.get("ugc_item_id")) for row in rows if row.get("ugc_item_id")}


def transcribe_candidate(
    *,
    config: Config,
    supabase: SupabaseClient,
    run_id: str,
    candidate: UGCTranscriptCandidate,
    input_json: Path | None,
    timeout: int,
) -> bool:
    request_params = {
        "actor": ANOXVANZI_ACTOR_NAME,
        "ugc_item_id": candidate.ugc_item_id,
        "external_id": candidate.external_id,
        "video_url": candidate.video_url,
    }
    source_query_id = start_query(
        supabase=supabase,
        dry_run=False,
        run_id=run_id,
        provider=APIFY_PROVIDER,
        endpoint=ANOXVANZI_ENDPOINT,
        method="POST",
        request_params=request_params,
    )
    response_headers: dict[str, str] = {}
    response_status: int | None = None
    try:
        if input_json:
            body = json.loads(input_json.read_text())
        else:
            response = request_json(
                "POST",
                f"https://api.apify.com/v2{ANOXVANZI_ENDPOINT}",
                params={"token": config.apify_api_key},
                body={"start_urls": candidate.video_url},
                timeout=timeout,
            )
            body = response.body
            response_headers = response.headers
            response_status = response.status

        items = apify_dataset_items(body)
        log_api_usage(
            supabase=supabase,
            dry_run=False,
            run_id=run_id,
            provider=ANOXVANZI_TRANSCRIPT_SOURCE,
            endpoint=ANOXVANZI_ENDPOINT,
            status=response_status,
            response_count=len(items),
            headers=response_headers,
            metadata={"actor": ANOXVANZI_ACTOR_NAME},
        )
        complete_query(
            supabase=supabase,
            dry_run=False,
            source_query_id=source_query_id,
            response_count=len(items),
            http_status=response_status,
        )
    except (HttpClientError, RuntimeError) as exc:
        if isinstance(exc, HttpClientError) and response_status is None:
            log_api_usage(
                supabase=supabase,
                dry_run=False,
                run_id=run_id,
                provider=ANOXVANZI_TRANSCRIPT_SOURCE,
                endpoint=ANOXVANZI_ENDPOINT,
                status=exc.status,
                response_count=None,
                headers={},
                metadata={"actor": ANOXVANZI_ACTOR_NAME},
            )
        log_failed_query(
            supabase=supabase,
            dry_run=False,
            run_id=run_id,
            provider=APIFY_PROVIDER,
            endpoint=ANOXVANZI_ENDPOINT,
            method="POST",
            request_params=request_params,
            source_query_id=source_query_id,
            http_status=getattr(exc, "status", None),
            error_message=str(exc),
        )
        raise

    item = first_transcript_item(items)
    raw_item = item or (items[0] if items else None)
    if raw_item is not None:
        supabase.insert(
            "raw_payloads",
            {
                "run_id": run_id,
                "source_query_id": source_query_id,
                "provider": APIFY_PROVIDER,
                "endpoint": ANOXVANZI_ENDPOINT,
                "external_id": candidate.external_id or raw_item.get("videoId") or candidate.ugc_item_id,
                "payload_json": raw_item,
            },
        )
    if item is None:
        return False

    transcript_text, transcript_segments = transcript_text_and_segments(item)
    if not transcript_text:
        return False

    payload: dict[str, Any] = {
        "ugc_item_id": candidate.ugc_item_id,
        "transcript_text": transcript_text,
        "transcript_segments": transcript_segments,
        "transcript_source": ANOXVANZI_TRANSCRIPT_SOURCE,
    }

    upsert_or_insert_transcript(supabase, payload)
    return True


def upsert_or_insert_transcript(supabase: SupabaseClient, payload: dict[str, Any]) -> None:
    upsert_or_insert(supabase, "ugc_transcripts", payload, "ugc_item_id,transcript_source")


def upsert_or_insert(
    supabase: SupabaseClient,
    table: str,
    payload: dict[str, Any],
    conflict_columns: str,
) -> None:
    try:
        supabase.upsert(table, payload, conflict_columns)
    except HttpClientError as exc:
        if exc.status != 400 or not is_missing_upsert_constraint_error(exc):
            raise
        supabase.insert(table, payload)


def apify_dataset_items(body: Any) -> list[dict[str, Any]]:
    if isinstance(body, list):
        return [item for item in body if isinstance(item, dict)]
    if isinstance(body, dict):
        for key in ("items", "data", "results"):
            value = body.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [body]
    return []


def first_transcript_item(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in items:
        if str(item.get("status") or "").lower() == "failed":
            continue
        transcript = item.get("transcript")
        if isinstance(transcript, str) and transcript.strip():
            return item
    return None


def transcript_text_and_segments(item: dict[str, Any]) -> tuple[str | None, Any]:
    transcript = item.get("transcript")
    if not isinstance(transcript, str) or not transcript.strip():
        return None, None

    segments = parse_timestamped_transcript(transcript)
    if not segments:
        return transcript.strip(), None

    text = " ".join(segment["text"] for segment in segments if segment.get("text")).strip()
    return text or transcript.strip(), segments


def parse_timestamped_transcript(transcript: str) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    for match in TIMESTAMPED_SEGMENT_RE.finditer(transcript):
        text = " ".join(match.group("text").split())
        if not text:
            continue
        segments.append(
            {
                "start": float(match.group("start")),
                "end": float(match.group("end")),
                "text": text,
            }
        )
    return segments


def is_missing_upsert_constraint_error(exc: HttpClientError) -> bool:
    body_text = json.dumps(exc.body).lower() if exc.body is not None else str(exc).lower()
    return "on conflict" in body_text or "unique" in body_text or "constraint" in body_text


def is_supported_social_video_url(url: str) -> bool:
    hostname = urlparse(url).hostname
    if not hostname:
        return False
    normalized = hostname.lower().removeprefix("www.")
    return any(normalized == host or normalized.endswith(f".{host}") for host in SUPPORTED_VIDEO_HOSTS)
