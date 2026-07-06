"""classify-formats: write a free-form marketing "niche constraint" per viral format.

One cheap text LLM call per viral_formats row, fed the format description plus the
ai_description/transcript of its example videos (from item_enrichments). The output is a
1-2 sentence free-form note on which marketing niches the format suits (universal, or
food-only / beauty-only / etc.). Stored on viral_formats.niche_constraint and shown on the
trends dashboard. Text-only — no video, no Apify.
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
from .ingestion import utc_now_iso
from .supabase_client import SupabaseClient

CONSTRAINT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"niche_constraint": {"type": "string"}},
    "required": ["niche_constraint"],
}

PROMPT_TEMPLATE = (
    "You advise marketers on whether a viral short-form video FORMAT can be reused to "
    "promote their product. Given the format and example videos below, write the format's "
    "marketing CONSTRAINT in 1-2 sentences: which product niches/industries this format "
    "works for. Say 'Universal' if it works for almost any product, otherwise name the "
    "specific niche(s) and why (e.g. 'Food/beverage only — the payoff is a satisfying "
    "eating shot', or 'Any product with a visible before/after — strongest for beauty, "
    "fitness, home reno'). Be concrete and concise. Respond with JSON only.\n\n"
    "FORMAT NAME: {format_name}\n"
    "FORMAT DESCRIPTION: {format_description}\n\n"
    "EXAMPLE VIDEOS:\n{examples}"
)


@dataclass
class ClassifyResult:
    candidates: int = 0
    written: int = 0
    skipped_existing: int = 0
    failed: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)


def classify_formats(
    *,
    config: Config,
    supabase: SupabaseClient | None,
    source_name: str | None = None,
    limit: int = 1000,
    overwrite: bool = False,
    dry_run: bool = False,
    timeout: int = 60,
    concurrency: int = 6,
) -> ClassifyResult:
    if supabase is None:
        raise RuntimeError("Supabase credentials are required to classify formats.")
    if not config.openrouter_api_key:
        raise RuntimeError("OPENROUTER_API_KEY is required to classify formats.")

    params = {
        "select": "id,format_name,format_description,niche_constraint",
        "order": "created_at.desc",
        "limit": str(limit),
    }
    if source_name:
        params["source_name"] = f"eq.{source_name}"
    formats = supabase.select("viral_formats", params)

    result = ClassifyResult()
    pending: list[dict[str, Any]] = []
    for fmt in formats:
        if not overwrite and (fmt.get("niche_constraint") or "").strip():
            result.skipped_existing += 1
            continue
        pending.append(fmt)
    result.candidates = len(pending)

    if dry_run:
        result.details = [{"id": f.get("id"), "format_name": f.get("format_name"), "action": "would_classify"} for f in pending]
        return result

    def _one(fmt: dict[str, Any]) -> bool:
        try:
            examples = _example_context(supabase, str(fmt["id"]))
            constraint = _call_llm(config, fmt, examples, timeout=timeout)
        except (HttpClientError, RuntimeError) as exc:
            result.failed += 1
            result.details.append({"id": fmt.get("id"), "error": str(exc)[:200]})
            return False
        supabase.update_by_id(
            "viral_formats",
            str(fmt["id"]),
            {
                "niche_constraint": constraint,
                "niche_constraint_model": config.openrouter_model,
                "classified_at": utc_now_iso(),
            },
        )
        return True

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as ex:
        for ok in ex.map(_one, pending):
            if ok:
                result.written += 1
    return result


def _example_context(supabase: SupabaseClient, format_id: str) -> str:
    """The ai_description/transcript of a format's example videos, for the LLM."""
    videos = supabase.select(
        "ugc_items", {"select": "id", "format_id": f"eq.{format_id}", "limit": "10"}
    )
    ids = [str(v["id"]) for v in videos if v.get("id")]
    if not ids:
        return "(no example videos enriched yet — infer from the format description alone)"
    enrichments = supabase.select(
        "item_enrichments",
        {
            "select": "ai_description,transcript_text",
            "item_type": "eq.ugc_item",
            "item_id": f"in.({','.join(ids)})",
        },
    )
    chunks: list[str] = []
    for i, row in enumerate(enrichments, 1):
        desc = (row.get("ai_description") or "").strip()
        transcript = (row.get("transcript_text") or "").strip()
        if not desc and not transcript:
            continue
        chunks.append(f"[Example {i}] {desc}\nTranscript: {transcript or '(none)'}")
    return "\n\n".join(chunks) or "(no enriched examples yet — infer from the format description alone)"


def _call_llm(config: Config, fmt: dict[str, Any], examples: str, *, timeout: int) -> str:
    prompt = PROMPT_TEMPLATE.format(
        format_name=fmt.get("format_name") or "",
        format_description=(fmt.get("format_description") or "").strip() or "(none)",
        examples=examples[:12000],
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
                "json_schema": {"name": "niche_constraint", "strict": True, "schema": CONSTRAINT_SCHEMA},
            },
            "max_tokens": 200,
        },
        timeout=timeout,
    )
    analysis = parse_enrichment_response(response.body)
    constraint = (analysis or {}).get("niche_constraint") if isinstance(analysis, dict) else None
    if not isinstance(constraint, str) or not constraint.strip():
        raise RuntimeError("OpenRouter returned no niche_constraint.")
    return constraint.strip()
