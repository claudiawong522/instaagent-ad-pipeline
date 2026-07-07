# Agent Instructions

This file applies to the whole repository.

## Project Shape

This repo is a lean Python ingestion foundation for InstaAgent's ad pipeline.

Primary areas:

- `src/instaagent_pipeline/`: CLI, provider clients, normalization, and Supabase REST writes.
- `supabase/schema.sql`: canonical Supabase schema for a clean project.
- `supabase/migrations/`: incremental database migrations for existing Supabase projects. Verify a live database against these before building search/clustering on top of old data.
- `database.md`: human-readable database/table documentation.
- `docs/archive/`: superseded plans and one-off notes (`PLAN.md`, `api-endpoints.md`, …); historical context only — do not treat items there as implemented.
- `experiments/`: standalone analysis/visualization scripts; not part of the package.
- `app/`, `components/`, `lib/`: the Next.js dashboard (at the repo root so it shares one Vercel project with the API).
- `api/index.py` + `vercel.json`: Vercel Python entry — mounts the FastAPI app (`src/instaagent_pipeline/api/app.py`) as serverless functions under `/api` (13-min `maxDuration`).

Runtime dependencies are listed in `pyproject.toml`; `numpy` and `scikit-learn` are required for clustering.

## Deployment

Frontend + backend deploy as a **single Vercel project**: the Next.js UI and the FastAPI backend (as Python serverless functions). Push to `main` auto-deploys production via `.github/workflows/deploy-vercel.yml`. Secrets (Supabase + provider keys) are Vercel Environment Variables, server-side only. The scrape pipeline runs inline within the request (no background threads — serverless kills them on response); a single scrape must finish within the 13-min function limit. Locally the two run as separate processes (`uvicorn … :8000` + `npm run dev`), since Next's dev server can't serve the Python functions.


## Secrets

The Supabase service role key is server-side only and bypasses row-level security. Do not put it in browser/client code.


## Implementation Notes

- Prefer existing helpers in `ingestion.py` (incl. the `logged_query` bookkeeping context
  manager), `normalizers.py`, and `supabase_client.py`. Shared infrastructure lives in
  dedicated modules — `openrouter.py` (LLM call envelope/parsing), `media.py` (video/thumbnail
  fetch + Storage persist), `apify_client.py` (actor run/poll/ingest), `video_enrichment.py`
  (the paid+organic vision flow, parametrized by `ItemKind`) — don't re-hand-roll these in
  feature modules.
- Preserve raw payload storage before normalized upserts.
- Paid ad upserts depend on `(run_id, id)` uniqueness; organic upserts depend on `(run_id, external_id)` uniqueness.
- Provider-specific fields that do not deserve first-class columns should live in `source_metrics`.
- Keep the CLI simple and dependency-light unless the user asks for a larger architecture change.

## Remember To-Do
- Update database.md when there are architectural changes
- Update future-add-ons.md when there are suggestions unused
