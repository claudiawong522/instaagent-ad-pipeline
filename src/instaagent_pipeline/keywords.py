from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .config import Config
from .http_client import HttpClientError, request_json
from .ingestion import complete_query, log_api_usage, log_failed_query, start_query
from .supabase_client import SupabaseClient


CLAUDE_MESSAGES_PATH = "/v1/messages"
CLAUDE_BASE_URL = "https://api.anthropic.com"


@dataclass(frozen=True)
class KeywordAllocation:
    keyword_text: str
    target_paid_count: int
    target_ugc_count: int  # reels (Instagram)
    target_tiktok_count: int = 0
    source: str = "llm"
    keyword_type: str = "seed"


@dataclass(frozen=True)
class KeywordGenerationResult:
    allocations: list[KeywordAllocation]
    model: str
    status: int
    headers: dict[str, str]
    usage: dict[str, Any]


def generate_keyword_allocations(
    *,
    config: Config,
    supabase: SupabaseClient | None = None,
    dry_run: bool = False,
    run_id: str | None = None,
    product_name: str,
    category: str | None,
    target_market: str | None,
    notes: str | None,
    campaign_guidelines: str | None,
    target_paid_count: int,
    target_ugc_count: int,
    target_tiktok_count: int = 0,
) -> KeywordGenerationResult:
    if not config.claude_api_key:
        raise RuntimeError("CLAUDE_API_KEY is required when --keyword is not provided.")

    provider = claude_provider(config.claude_model)
    body = {
        "model": config.claude_model,
        "max_tokens": 1200,
        "temperature": 0.2,
        "system": (
            "You create search keywords for paid ad and organic discovery. "
            "Generate 3-5 keywords and aim for 4. "
            "Every keyword_text must be exactly ONE word with no spaces: the discovery APIs match the keyword "
            "as a substring of short video topics, so multi-word phrases return zero results. "
            "Choose CONCRETE, common single-word nouns that name the product, its category, or a key "
            "ingredient (e.g. cleanser, moisturizer, serum, toner, niacinamide, acne). Never concatenate "
            "multiple words into one token: write 'cleanser', never 'facewash' or 'skincareroutine' (invented "
            "compounds appear in no video topics and return zero results). Do NOT use adjectives or generic "
            "descriptors (e.g. gentle, clean, fresh, natural, glow) — as standalone words their search results "
            "are dominated by unrelated trending content. "
            "For a gentle cleanser: 'cleanser' is good (it names the product); 'skincare' is acceptable (an "
            "on-domain category); 'acne' is good (the core problem the product solves — adjacent results like "
            "acne-treatment ads are still useful inspiration); 'gentle' is BAD because it matches 'gentle giant' "
            "animal videos and 'gentleman' memes; 'asmr' is BAD because it is a format, not the product. "
            "Aim for the sweet spot: broad enough that the discovery APIs return results, specific enough that "
            "those results stay on-topic (adjacent items — a face-wash or moisturizer ad for 'cleanser' — are fine "
            "as references). Cover DISTINCT angles — the product, its category, and its core problem or benefit — "
            "not synonyms of one word. Lean toward broad, widely-searched category-level nouns (e.g. "
            "'skincare', 'cleanser', 'acne') rather than narrow niche terms (e.g. 'niacinamide', 'azelaic'); "
            "a slightly broader noun returns more discovery results while staying on-topic. "
            "Return strict JSON only. Do not include markdown."
        ),
        "messages": [
            {
                "role": "user",
                "content": keyword_prompt(
                    product_name=product_name,
                    category=category,
                    target_market=target_market,
                    notes=notes,
                    campaign_guidelines=campaign_guidelines,
                    target_paid_count=target_paid_count,
                    target_ugc_count=target_ugc_count,
                    target_tiktok_count=target_tiktok_count,
                ),
            }
        ],
    }
    source_query_id = (
        start_query(
            supabase=supabase,
            dry_run=dry_run,
            run_id=run_id,
            provider=provider,
            endpoint=CLAUDE_MESSAGES_PATH,
            method="POST",
            request_params=body,
        )
        if run_id is not None
        else None
    )
    api_usage_attempted = False

    try:
        response = request_json(
            "POST",
            f"{CLAUDE_BASE_URL}{CLAUDE_MESSAGES_PATH}",
            headers={
                "x-api-key": config.claude_api_key,
                "anthropic-version": "2023-06-01",
            },
            body=body,
        )
        usage = response.body.get("usage", {}) if isinstance(response.body, dict) else {}
        api_usage_attempted = True
        log_api_usage(
            supabase=supabase,
            dry_run=dry_run,
            run_id=run_id,
            provider=provider,
            endpoint=CLAUDE_MESSAGES_PATH,
            status=response.status,
            response_count=1,
            headers=response.headers,
            metadata={"model": config.claude_model, "usage": usage},
        )
        text = claude_text(response.body)
        allocations = parse_keyword_allocations(
            text,
            expected_paid_total=target_paid_count,
            expected_organic_total=target_ugc_count,
            expected_tiktok_total=target_tiktok_count,
        )
        complete_query(
            supabase=supabase,
            dry_run=dry_run,
            source_query_id=source_query_id,
            response_count=len(allocations),
            http_status=response.status,
        )
        return KeywordGenerationResult(
            allocations=allocations,
            model=config.claude_model,
            status=response.status,
            headers=response.headers,
            usage=usage,
        )
    except (HttpClientError, RuntimeError) as exc:
        if isinstance(exc, HttpClientError) and not api_usage_attempted:
            log_api_usage(
                supabase=supabase,
                dry_run=dry_run,
                run_id=run_id,
                provider=provider,
                endpoint=CLAUDE_MESSAGES_PATH,
                status=exc.status,
                response_count=None,
                headers={},
                metadata={"model": config.claude_model},
            )
        if run_id is not None:
            log_failed_query(
                supabase=supabase,
                dry_run=dry_run,
                run_id=run_id,
                provider=provider,
                endpoint=CLAUDE_MESSAGES_PATH,
                method="POST",
                request_params=body,
                source_query_id=source_query_id,
                http_status=getattr(exc, "status", None),
                error_message=str(exc),
            )
        raise


def claude_provider(model: str) -> str:
    """Provider string for bookkeeping rows, in the same "<provider>:<model>" shape every
    other provider uses (openrouter:…, voyage:…, gemini:…)."""
    cleaned = model.strip()
    if not cleaned:
        return "claude"
    return f"claude:{cleaned}"


def keyword_prompt(
    *,
    product_name: str,
    category: str | None,
    target_market: str | None,
    notes: str | None,
    campaign_guidelines: str | None,
    target_paid_count: int,
    target_ugc_count: int,
    target_tiktok_count: int = 0,
) -> str:
    return f"""
Product name: {product_name}
Category: {category or ""}
Target market: {target_market or ""}
Product notes: {notes or ""}
Campaign guidelines: {campaign_guidelines or ""}

Target paid ads: {target_paid_count}
Target reels (Instagram): {target_ugc_count}
Target tiktoks: {target_tiktok_count}

Create 3-5 single-word search keywords for provider API discovery.
Aim for 4 keywords. Each keyword_text must be exactly one word with no spaces.
Use concrete, common single-word nouns (e.g. cleanser, moisturizer, serum, toner, acne).
Never concatenate words into one token (write "cleanser", never "facewash" or "skincareroutine").
Avoid adjectives and generic descriptors (e.g. gentle, clean, fresh, natural, glow) — as single words they
match unrelated trending content. Favor broad, common category-level nouns (e.g. skincare, cleanser, acne)
over narrow niche terms (e.g. niacinamide).

Allocate target_paid_count, target_ugc_count, and target_tiktok_count across the keywords.
The sum of all target_paid_count values must equal {target_paid_count}.
The sum of all target_ugc_count values must equal {target_ugc_count}.
The sum of all target_tiktok_count values must equal {target_tiktok_count}.
Use non-negative integers only.

Return exactly this JSON shape:
{{
  "keywords": [
    {{
      "keyword_text": "cleanser",
      "target_paid_count": 250,
      "target_ugc_count": 625,
      "target_tiktok_count": 625
    }}
  ]
}}
""".strip()


def claude_text(body: Any) -> str:
    if not isinstance(body, dict):
        raise RuntimeError("Claude response was not a JSON object.")
    chunks: list[str] = []
    for content in body.get("content", []):
        if isinstance(content, dict) and content.get("type") == "text":
            chunks.append(str(content.get("text", "")))
    text = "\n".join(chunks).strip()
    if not text:
        raise RuntimeError("Claude response did not include text content.")
    return text


def parse_keyword_allocations(
    text: str,
    *,
    expected_paid_total: int,
    expected_organic_total: int,
    expected_tiktok_total: int = 0,
) -> list[KeywordAllocation]:
    parsed = json.loads(extract_json_object(text))
    rows = parsed.get("keywords") if isinstance(parsed, dict) else None
    if not isinstance(rows, list):
        raise RuntimeError("Claude keyword response must contain a keywords list.")
    if not 3 <= len(rows) <= 5:
        raise RuntimeError("Claude must return 3-5 keywords.")

    allocations: list[KeywordAllocation] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise RuntimeError("Each Claude keyword row must be an object.")
        keyword = str(row.get("keyword_text", "")).strip()
        normalized = keyword.lower()
        if not keyword:
            raise RuntimeError("Claude returned an empty keyword.")
        if normalized in seen:
            raise RuntimeError(f"Claude returned duplicate keyword: {keyword}")
        seen.add(normalized)
        paid_count = as_nonnegative_int(row.get("target_paid_count"), "target_paid_count")
        organic_count = as_nonnegative_int(row.get("target_ugc_count"), "target_ugc_count")
        tiktok_count = as_nonnegative_int(row.get("target_tiktok_count"), "target_tiktok_count")
        allocations.append(
            KeywordAllocation(
                keyword_text=keyword,
                target_paid_count=paid_count,
                target_ugc_count=organic_count,
                target_tiktok_count=tiktok_count,
            )
        )

    paid_total = sum(row.target_paid_count for row in allocations)
    organic_total = sum(row.target_ugc_count for row in allocations)
    tiktok_total = sum(row.target_tiktok_count for row in allocations)
    if paid_total != expected_paid_total:
        raise RuntimeError(f"Claude paid allocation total {paid_total} != target {expected_paid_total}.")
    if organic_total != expected_organic_total:
        raise RuntimeError(f"Claude organic allocation total {organic_total} != target {expected_organic_total}.")
    if tiktok_total != expected_tiktok_total:
        raise RuntimeError(f"Claude tiktok allocation total {tiktok_total} != target {expected_tiktok_total}.")
    return allocations


def extract_json_object(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.removeprefix("```json").removeprefix("```").strip()
        stripped = stripped.removesuffix("```").strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise RuntimeError("Claude keyword response did not contain a JSON object.")
    return stripped[start : end + 1]


def as_nonnegative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool):
        raise RuntimeError(f"{field_name} must be a non-negative integer.")
    if isinstance(value, int):
        number = value
    elif isinstance(value, float) and value.is_integer():
        number = int(value)
    elif isinstance(value, str) and value.strip().isdigit():
        number = int(value.strip())
    else:
        raise RuntimeError(f"{field_name} must be a non-negative integer.")
    if number < 0:
        raise RuntimeError(f"{field_name} must be a non-negative integer.")
    return number


def allocate_manual_keywords(
    keywords: list[str],
    *,
    target_paid_count: int,
    target_ugc_count: int,
    target_tiktok_count: int = 0,
    keyword_type: str,
) -> list[KeywordAllocation]:
    cleaned = [keyword.strip() for keyword in keywords if keyword.strip()]
    if not cleaned:
        raise RuntimeError("At least one keyword is required.")
    paid_counts = split_evenly(target_paid_count, len(cleaned))
    organic_counts = split_evenly(target_ugc_count, len(cleaned))
    tiktok_counts = split_evenly(target_tiktok_count, len(cleaned))
    return [
        KeywordAllocation(
            keyword_text=keyword,
            target_paid_count=paid_counts[index],
            target_ugc_count=organic_counts[index],
            target_tiktok_count=tiktok_counts[index],
            source="manual",
            keyword_type=keyword_type,
        )
        for index, keyword in enumerate(cleaned)
    ]


def split_evenly(total: int, parts: int) -> list[int]:
    if total < 0:
        raise RuntimeError("Target counts must be non-negative.")
    base = total // parts
    remainder = total % parts
    return [base + (1 if index < remainder else 0) for index in range(parts)]


def split_proportionally(total: int, weights: list[int]) -> list[int]:
    """Distribute `total` across len(weights) buckets proportional to weights, assigning the
    rounding remainder to the largest fractional parts. Falls back to an even split when all
    weights are zero. The result always sums to `total`."""
    if total < 0:
        raise RuntimeError("Target counts must be non-negative.")
    parts = len(weights)
    if parts == 0:
        return []
    weight_total = sum(weights)
    if weight_total <= 0:
        return split_evenly(total, parts)
    raw = [total * weight / weight_total for weight in weights]
    floors = [int(value) for value in raw]
    remainder = total - sum(floors)
    for index in sorted(range(parts), key=lambda i: raw[i] - floors[i], reverse=True)[:remainder]:
        floors[index] += 1
    return floors


def insert_keyword_allocations(
    supabase: SupabaseClient,
    *,
    run_id: str,
    allocations: list[KeywordAllocation],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for allocation in allocations:
        rows.append(
            supabase.insert(
                "keywords",
                {
                    "run_id": run_id,
                    "keyword_text": allocation.keyword_text,
                    "keyword_type": allocation.keyword_type,
                    "source": allocation.source,
                    "active": True,
                    "target_paid_count": allocation.target_paid_count,
                    "target_ugc_count": allocation.target_ugc_count,
                    "target_tiktok_count": allocation.target_tiktok_count,
                },
            )
        )
    return rows


def active_keyword_allocations(supabase: SupabaseClient, run_id: str) -> list[dict[str, Any]]:
    rows = supabase.select(
        "keywords",
        {
            "select": "keyword_text,target_paid_count,target_ugc_count,target_tiktok_count",
            "run_id": f"eq.{run_id}",
            "active": "eq.true",
            "order": "created_at.asc",
        },
    )
    return [row for row in rows if isinstance(row, dict)]
