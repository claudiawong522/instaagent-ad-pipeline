"""classify-formats: tag each viral format for product→trend matching.

One cheap text LLM call per viral_formats row, fed the format description plus the
ai_description/transcript of its example videos (from item_enrichments). The output is a
structured tag set: a coarse `versatility` bucket (universal/broad/niche), the `fit_niches`
the format suits, the concrete `product_requirements` a product must be able to show for it
to work, and the free-form `niche_constraint` prose (kept for display). All four land on
viral_formats. Each classified format is then embedded (Voyage document vector) into
item_embeddings (item_type='viral_format', space='trend') so a product query can recall it
before the LLM fit-judge. Text-only — no video, no Apify.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from .config import Config
from .embeddings import EMBEDDING_BATCH_SIZE, EmbeddingCandidate, batched, embed_batch
from .http_client import HttpClientError
from .ingestion import utc_now_iso
from .openrouter import openrouter_json_call
from .supabase_client import SupabaseClient

# Space + item_type for a viral format's own embedding (see migration 027).
TREND_EMBEDDING_SPACE = "trend"
VIRAL_FORMAT_ITEM_TYPE = "viral_format"

CONSTRAINT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "versatility": {"type": "string", "enum": ["universal", "broad", "niche"]},
        "fit_niches": {"type": "array", "items": {"type": "string"}},
        "product_requirements": {"type": "array", "items": {"type": "string"}},
        "niche_constraint": {"type": "string"},
    },
    "required": ["versatility", "fit_niches", "product_requirements", "niche_constraint"],
}

PROMPT_TEMPLATE = (
    "You advise marketers on whether a viral short-form video FORMAT can be reused to "
    "promote their product. Read the format and its example videos, then output four things:\n\n"
    "1. versatility — one word:\n"
    "   - \"universal\": works for almost any product\n"
    "   - \"broad\": works across several related niches\n"
    "   - \"niche\": only fits a specific niche or product type\n"
    "2. fit_niches — the product niches/industries this format suits, e.g. [\"beauty\","
    "\"skincare\"]. Use [] when versatility is \"universal\".\n"
    "3. product_requirements — the CONCRETE things a product must be able to SHOW on camera "
    "for this format to land, e.g. [\"a visible before/after\",\"a satisfying physical "
    "action\"]. Use [] when any product works. This is what decides whether a given product "
    "fits.\n"
    "4. niche_constraint — the same idea as a human-readable 1-2 sentence note (for display).\n\n"
    "Be concrete and honest. Respond with JSON only.\n\n"
    "FORMAT NAME: {format_name}\n"
    "FORMAT DESCRIPTION: {format_description}\n\n"
    "EXAMPLE VIDEOS:\n{examples}"
)


def build_trend_text(fmt: dict[str, Any]) -> str:
    """The document text embedded per trend for product→format recall: what the format is
    plus what product suits it, so a product query lands near it. Reads the classified
    fields, so call it after versatility/fit_niches/product_requirements are set."""
    head = f"{(fmt.get('format_name') or '').strip()}. {(fmt.get('format_description') or '').strip()}".strip()
    niches = ", ".join(fmt.get("fit_niches") or []) or "any product"
    versatility = fmt.get("versatility") or "broad"
    reqs = ", ".join(fmt.get("product_requirements") or []) or "no specific requirements"
    return (
        f"{head}\n"
        f"Works for: {niches}  ({versatility}).\n"
        f"Needs a product with: {reqs}."
    )


@dataclass
class ClassifyResult:
    candidates: int = 0
    written: int = 0
    embedded: int = 0
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
        "select": "id,run_id,format_name,format_description,niche_constraint,versatility,fit_niches,product_requirements",
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

    # (run_id, candidate) tuples collected across threads (list.append is atomic under the
    # GIL), embedded in a batched pass after classification so trends land in the 'trend' space.
    to_embed: list[tuple[str, EmbeddingCandidate]] = []

    def _one(fmt: dict[str, Any]) -> bool:
        try:
            examples = _example_context(supabase, str(fmt["id"]))
            tags = _call_llm(config, fmt, examples, timeout=timeout)
        except (HttpClientError, RuntimeError) as exc:
            result.failed += 1
            result.details.append({"id": fmt.get("id"), "error": str(exc)[:200]})
            return False
        supabase.update_by_id(
            "viral_formats",
            str(fmt["id"]),
            {
                "versatility": tags["versatility"],
                "fit_niches": tags["fit_niches"],
                "product_requirements": tags["product_requirements"],
                "niche_constraint": tags["niche_constraint"],
                "niche_constraint_model": config.openrouter_model,
                "classified_at": utc_now_iso(),
            },
        )
        run_id = fmt.get("run_id")
        if run_id:
            source_text = build_trend_text({**fmt, **tags})
            to_embed.append(
                (
                    str(run_id),
                    EmbeddingCandidate(
                        item_type=VIRAL_FORMAT_ITEM_TYPE,
                        item_id=str(fmt["id"]),
                        space=TREND_EMBEDDING_SPACE,
                        source_text=source_text,
                    ),
                )
            )
        return True

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as ex:
        for ok in ex.map(_one, pending):
            if ok:
                result.written += 1

    _embed_trends(config, supabase, to_embed, result, timeout=timeout)
    return result


def _embed_trends(
    config: Config,
    supabase: SupabaseClient,
    to_embed: list[tuple[str, EmbeddingCandidate]],
    result: ClassifyResult,
    *,
    timeout: int,
) -> None:
    """Embed newly-classified trends into item_embeddings (space='trend'). Best-effort: a
    Voyage failure records a detail but does not fail the classify run — the format is still
    tagged, it just won't be recallable until re-embedded. Skipped when no Voyage key."""
    if not to_embed:
        return
    if not config.voyage_api_key:
        result.details.append({"embed_skipped": "VOYAGE_API_KEY not set — trends not embedded"})
        return
    by_run: dict[str, list[EmbeddingCandidate]] = {}
    for run_id, candidate in to_embed:
        by_run.setdefault(run_id, []).append(candidate)
    for run_id, candidates in by_run.items():
        for group in batched(candidates, EMBEDDING_BATCH_SIZE):
            try:
                result.embedded += embed_batch(
                    config=config,
                    supabase=supabase,
                    run_id=run_id,
                    batch=group,
                    embedding_model=config.embedding_model,
                    input_json=None,
                    timeout=timeout,
                )
            except (HttpClientError, RuntimeError) as exc:
                result.details.append({"embed_error": str(exc)[:200]})


def _example_context(supabase: SupabaseClient, format_id: str) -> str:
    """The ai_description/transcript of a format's example videos, for the LLM."""
    videos = supabase.select(
        "organic_items", {"select": "id", "format_id": f"eq.{format_id}", "limit": "10"}
    )
    ids = [str(v["id"]) for v in videos if v.get("id")]
    if not ids:
        return "(no example videos enriched yet — infer from the format description alone)"
    enrichments = supabase.select(
        "item_enrichments",
        {
            "select": "ai_description,transcript_text",
            "item_type": "eq.organic_item",
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


def _call_llm(config: Config, fmt: dict[str, Any], examples: str, *, timeout: int) -> dict[str, Any]:
    prompt = PROMPT_TEMPLATE.format(
        format_name=fmt.get("format_name") or "",
        format_description=(fmt.get("format_description") or "").strip() or "(none)",
        examples=examples[:12000],
    )
    analysis = openrouter_json_call(
        config,
        prompt=prompt,
        schema=CONSTRAINT_SCHEMA,
        schema_name="format_tags",
        max_tokens=400,
        timeout=timeout,
        empty_error="OpenRouter returned no format tags.",
    )
    constraint = analysis.get("niche_constraint")
    versatility = analysis.get("versatility")
    if not isinstance(constraint, str) or not constraint.strip():
        raise RuntimeError("OpenRouter returned no niche_constraint.")
    if versatility not in ("universal", "broad", "niche"):
        raise RuntimeError(f"OpenRouter returned an invalid versatility: {versatility!r}.")
    return {
        "versatility": versatility,
        "fit_niches": [s.strip() for s in (analysis.get("fit_niches") or []) if isinstance(s, str) and s.strip()],
        "product_requirements": [
            s.strip() for s in (analysis.get("product_requirements") or []) if isinstance(s, str) and s.strip()
        ],
        "niche_constraint": constraint.strip(),
    }
