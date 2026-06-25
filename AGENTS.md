# Agent Instructions

This file applies to the whole repository.

## Project Shape

This repo is a lean Python ingestion foundation for InstaAgent's ad pipeline.

Primary areas:

- `src/instaagent_pipeline/`: CLI, provider clients, normalization, and Supabase REST writes.
- `supabase/schema.sql`: canonical Supabase schema for a clean project.
- `supabase/migrations/`: incremental database migrations for existing Supabase projects. Verify a live database against these before building search/clustering on top of old data.
- `database.md`: human-readable database/table documentation.
- `api-endpoints.md`: provider endpoint and mapping notes.
- `PLAN.md`: broader future plan; do not treat every item there as implemented.

Runtime dependencies are listed in `pyproject.toml`; `numpy` and `scikit-learn` are required for clustering.


## Secrets

The Supabase service role key is server-side only and bypasses row-level security. Do not put it in browser/client code.


## Implementation Notes

- Prefer existing helpers in `ingestion.py`, `normalizers.py`, and `supabase_client.py`.
- Preserve raw payload storage before normalized upserts.
- Paid ad upserts depend on `(run_id, id)` uniqueness; organic upserts depend on `(run_id, external_id)` uniqueness.
- Provider-specific fields that do not deserve first-class columns should live in `source_metrics`.
- Keep the CLI simple and dependency-light unless the user asks for a larger architecture change.

## Remember To-Do
- Update database.md when there are architectural changes
- Update future-add-ons.md when there are suggestions unused
