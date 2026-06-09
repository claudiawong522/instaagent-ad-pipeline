# Agent Instructions

This file applies to the whole repository.

## Project Shape

This repo is a lean Python ingestion foundation for InstaAgent's ad pipeline.

Primary areas:

- `src/instaagent_pipeline/`: CLI, provider clients, normalization, and Supabase REST writes.
- `supabase/schema.sql`: current intended Supabase schema.
- `supabase/migrations/`: incremental database migrations for existing Supabase projects.
- `database.md`: human-readable database/table documentation.
- `api-endpoints.md`: provider endpoint and mapping notes.
- `PLAN.md`: broader future plan; do not treat every item there as implemented.

There are no required third-party Python dependencies in `pyproject.toml`.


## Secrets

The Supabase service role key is server-side only and bypasses row-level security. Do not put it in browser/client code.


## Implementation Notes

- Prefer existing helpers in `ingestion.py`, `normalizers.py`, and `supabase_client.py`.
- Preserve raw payload storage before normalized upserts.
- Upserts currently depend on `(run_id, source_provider, external_id)` uniqueness for normalized item tables.
- Provider-specific fields that do not deserve first-class columns should live in `source_metrics`.
- Keep the CLI simple and dependency-light unless the user asks for a larger architecture change.

## Remember To-Do
- Update database.md when there are architectural changes
- Update future-add-ons.md when there are suggestions unused