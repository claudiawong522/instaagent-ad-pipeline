"""Phase 4 — text-only audience/tone enrichment.

Derives the abstract attributes that literal vision descriptions don't capture
(target generation, price positioning, age groups, languages) by re-reading the
already-stored ai_description + transcript with a cheap text LLM. No video download.

The fields land on item_enrichments and feed: target_generation -> the icp embedding
space (build_icp_text); price_positioning/age_brackets/languages -> the categorical
search filters. Requires migration 018 to have added the columns.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from .ad_enrichment import (
    OPENROUTER_BASE_URL,
    OPENROUTER_CHAT_COMPLETIONS_ENDPOINT,
    parse_enrichment_response,
)
from .config import Config
from .http_client import HttpClientError, request_json
from .supabase_client import SupabaseClient

TARGET_GENERATIONS = ("gen_z", "millennial", "gen_x", "boomer", "mixed")
PRICE_TIERS = ("budget", "mid", "premium", "luxury")
AGE_BRACKETS = ("13-17", "18-24", "25-34", "35-44", "45-54", "55+")

AUDIENCE_SCHEMA = {
    "type": "object",
    "properties": {
        "target_generation": {"type": "string", "enum": list(TARGET_GENERATIONS)},
        "price_positioning": {"type": "string", "enum": list(PRICE_TIERS)},
        "age_brackets": {
            "type": "array",
            "items": {"type": "string", "enum": list(AGE_BRACKETS)},
        },
        "languages": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["target_generation", "price_positioning", "age_brackets", "languages"],
    "additionalProperties": False,
}

PROMPT_TEMPLATE = (
    "You analyze a short-form social video for a creative-search tool, using ONLY the "
    "description and transcript below (you cannot see the video). Infer the audience and "
    "positioning. Respond with JSON only.\n"
    "- target_generation: the single generation the content most targets — one of "
    f"{', '.join(TARGET_GENERATIONS)}.\n"
    "- price_positioning: the product's price tier — one of "
    f"{', '.join(PRICE_TIERS)}.\n"
    "- age_brackets: an array of EVERY age group the video targets or prominently "
    f"depicts (people on screen + intended audience), each one of {', '.join(AGE_BRACKETS)}.\n"
    "- languages: an array of the spoken/written languages, canonical English names "
    "(e.g. English, Cantonese, Mandarin).\n\n"
    "DESCRIPTION:\n{description}\n\nTRANSCRIPT:\n{transcript}"
)

# item_enrichments columns the pass reads. target_generation is included so already-done
# rows can be skipped; requires migration 018.
SELECT_COLUMNS = "item_id,item_type,ai_description,transcript_text,target_generation"


@dataclass
class AudienceResult:
    candidates: int = 0
    written: int = 0
    skipped_existing: int = 0
    skipped_no_text: int = 0
    failed: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)


def enrich_audience(
    *,
    config: Config,
    supabase: SupabaseClient | None,
    run_id: str,
    source: str = "all",
    limit: int = 1000,
    dry_run: bool = False,
    overwrite: bool = False,
    timeout: int = 60,
) -> AudienceResult:
    if supabase is None:
        raise RuntimeError("Supabase credentials are required for audience enrichment.")
    if source not in {"paid", "ugc", "all"}:
        raise ValueError("--source must be one of paid, ugc, all.")
    if not config.openrouter_api_key:
        raise RuntimeError("OPENROUTER_API_KEY is required for audience enrichment.")

    item_types = {"paid": ["paid_ad"], "ugc": ["ugc_item"], "all": ["paid_ad", "ugc_item"]}[source]
    result = AudienceResult()
    rows: list[dict[str, Any]] = []
    for item_type in item_types:
        rows.extend(
            supabase.select(
                "item_enrichments",
                {
                    "select": SELECT_COLUMNS,
                    "run_id": f"eq.{run_id}",
                    "item_type": f"eq.{item_type}",
                    "limit": str(limit),
                },
            )
        )

    pending: list[dict[str, Any]] = []
    for row in rows:
        if not overwrite and row.get("target_generation"):
            result.skipped_existing += 1
            continue
        description = (row.get("ai_description") or "").strip()
        if not description:
            result.skipped_no_text += 1
            continue
        pending.append(row)
    result.candidates = len(pending)

    if dry_run:
        result.details = [
            {"item_type": r.get("item_type"), "item_id": r.get("item_id"), "action": "would_enrich"}
            for r in pending
        ]
        return result

    def _one(row: dict[str, Any]) -> bool:
        try:
            analysis = _call_audience_llm(config, row, timeout=timeout)
        except (HttpClientError, RuntimeError) as exc:
            result.failed += 1
            result.details.append({"item_id": row.get("item_id"), "error": str(exc)[:200]})
            return False
        payload = {
            "run_id": run_id,
            "item_type": row.get("item_type"),
            "item_id": row.get("item_id"),
            **_normalize(analysis),
        }
        supabase.upsert("item_enrichments", [payload], "item_type,item_id")
        return True

    with ThreadPoolExecutor(max_workers=6) as ex:
        for ok in ex.map(_one, pending):
            if ok:
                result.written += 1
    return result


def _call_audience_llm(config: Config, row: dict[str, Any], *, timeout: int) -> dict[str, Any]:
    prompt = PROMPT_TEMPLATE.format(
        description=(row.get("ai_description") or "").strip(),
        transcript=(row.get("transcript_text") or "(none)").strip(),
    )
    response = request_json(
        "POST",
        f"{OPENROUTER_BASE_URL}{OPENROUTER_CHAT_COMPLETIONS_ENDPOINT}",
        headers={"Authorization": f"Bearer {config.openrouter_api_key}"},
        body={
            "model": config.openrouter_model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "audience", "strict": True, "schema": AUDIENCE_SCHEMA},
            },
            "max_tokens": 300,
        },
        timeout=timeout,
    )
    analysis = parse_enrichment_response(response.body)
    if analysis is None:
        raise RuntimeError("OpenRouter returned no audience analysis.")
    return analysis


def _normalize(analysis: dict[str, Any]) -> dict[str, Any]:
    """Coerce model output to the allowed vocab so filter values can't fragment."""
    def _enum(value: Any, allowed: tuple[str, ...]) -> str | None:
        if isinstance(value, str) and value.strip().lower() in allowed:
            return value.strip().lower()
        return None

    def _enum_list(value: Any, allowed: tuple[str, ...]) -> list[str]:
        if not isinstance(value, list):
            return []
        out = []
        for item in value:
            if isinstance(item, str) and item.strip().lower() in allowed and item.strip().lower() not in out:
                out.append(item.strip().lower())
        return out

    def _str_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        out = []
        for item in value:
            if isinstance(item, str) and item.strip():
                # Title-case canonical language names so "english"/"English" don't fragment.
                name = item.strip().title()
                if name not in out:
                    out.append(name)
        return out

    return {
        "target_generation": _enum(analysis.get("target_generation"), TARGET_GENERATIONS),
        "price_positioning": _enum(analysis.get("price_positioning"), PRICE_TIERS),
        "age_brackets": _enum_list(analysis.get("age_brackets"), AGE_BRACKETS),
        "languages": _str_list(analysis.get("languages")),
    }
