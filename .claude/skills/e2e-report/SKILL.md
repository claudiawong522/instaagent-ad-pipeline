---
name: e2e-report
description: Present end-to-end pipeline test results in the fixed report format. Use whenever reporting the outcome of an e2e test run of the instaagent pipeline (init-run → ingest → enrich → transcripts → embed), or any multi-stage pipeline test. The structure is identical every time; test-specific commentary goes last.
---

# E2E Test Report Format

When presenting end-to-end test results, ALWAYS use the exact section structure below, in this order, with these headings. Never improvise a different layout. Sections 1–5 are pure facts with fixed shape; anything interpretive, surprising, or specific to this particular test goes ONLY in section 6.

Rules that override everything else:

- Report every stage in section 2 even if it ran with 0 items or was skipped — write "skipped (reason)" rather than omitting it.
- Every count must come from a command output or a database query, never from memory. If a number wasn't captured, query for it before writing the report.
- No analysis, no praise, no "the kicker is..." before section 6.
- Use the run's short id (first 8 chars) and today's date in the title.

## Where the numbers come from

| Number | Source |
| --- | --- |
| Targets, keywords, allocations | `init-run` output (`pipeline_run`, `keywords`) |
| Fetched/written per keyword | ingestion command output (`keywords` details array) |
| Distinct rows (after cross-keyword dedupe) | `select paid_ads/ugc_items where run_id eq ...` row count |
| Enrichment counts | `enrich-paid-ads` output (`candidates/attempted/written/failed`) |
| Transcript outcomes | backfill output (`provider_subtitles`, `apify`) + `paid_ad_transcripts`/`ugc_transcripts` row counts |
| Embedding counts per type/space | `select item_embeddings where run_id eq ...` grouped in Python |
| API call ledger | `select source_queries where run_id eq ...` grouped by provider and status |
| Failure causes | `source_queries.error_message` for `status=eq.failed` rows |

## Template

```markdown
# E2E Test Report — run `<short-id>` (<YYYY-MM-DD>)

## 1. Inputs (verbatim)

<fenced block: every CLI command executed, in order, full flags>

**Targets:** <N> total = <N> paid + <N> organic
**Keywords:** <count> (<manual | Claude-generated>)

| Keyword | Paid allocation | Organic allocation |
|---|---|---|
| ... | ... | ... |

## 2. Stage-by-stage

For each stage, one block in pipeline order. Stages: init-run, paid ingestion,
paid enrichment, organic ingestion, organic transcript backfill, embeddings. Format:

**Stage <n> — <name> (<provider/model>)** · API calls: <count> (<breakdown: completed/failed>)
→ <inputs consumed> → <outputs produced with counts, per keyword where applicable>, failures: <n>.

The embeddings stage always ends with the per-type/per-space table:

| | icp | format | hook | total |
|---|---|---|---|---|
| paid_ad (<n> items) | | | | |
| ugc_item (<n> items) | | | | |

## 3. Funnel

| | Targeted | Fetched | Distinct rows | Analyzed/with metadata | Embedded (items) |
|---|---|---|---|---|---|
| Paid | | | | | |
| Organic | | | | | |

## 4. API call ledger (from `source_queries`)

| Provider | Calls | Completed | Failed |
|---|---|---|---|
| ... | | | |
| **Total external calls** | | | |

## 5. Verification checks

Checklist with ✅/⚠️/❌. Always include at minimum:
- all distinct items embedded (items × 3 spaces = vector count, dims)
- idempotency re-run (expect 0 written)
- skipped_no_text count
- any failed API calls, with one-line cause from error_message and whether they have downstream impact

## 6. Observations (test-specific)

Only here: anything interpretive — similarity findings, data-quality notes,
anomalies, follow-up suggestions.
```

## Worked example

A complete rendered example from a real run lives in the conversation that created this skill; the key properties to reproduce: section 1 shows the exact commands a reader could copy-paste to repeat the test; section 2 answers "how many X at stage Y" for every stage without the reader asking; sections 3–4 are the cross-checkable totals; section 5 is pass/fail; section 6 is the only place opinions live.
