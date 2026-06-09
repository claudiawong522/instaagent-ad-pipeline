# InstaAgent Ad Pipeline

Lean Step 1/2 implementation for InstaAgent's ad selection pipeline.

## What Exists Now

- `PLAN.md`: full future plan.
- `api-endpoints.md`: endpoint inputs, outputs, and storage mappings.
- `future-add-ons.md`: good ideas deferred for later.
- `supabase/schema.sql`: Supabase tables for run setup and source ingestion.
- Python CLI for:
  - creating products/runs/keywords.
  - ingesting Foreplay paid ad candidates.
  - ingesting TopYappers viral-content UGC candidates.
  - ingesting TopYappers videos for hydration.

## Setup

1. Create a Supabase project.
2. Run `supabase/schema.sql` in the Supabase SQL editor.
3. Copy `.env.example` values into your shell environment.

No third-party Python packages are required.

## Example Commands

Create a run:

```bash
PYTHONPATH=src python3 -m instaagent_pipeline.cli init-run \
  --product-name "QE cleanser" \
  --category "skincare" \
  --target-market "US skincare buyers" \
  --keyword "cleanser" \
  --keyword "gentle cleanser" \
  --keyword "gentle cleansing"
```

Ingest Foreplay paid ads:

```bash
PYTHONPATH=src python3 -m instaagent_pipeline.cli ingest-foreplay \
  --run-id "<pipeline_run_id>" \
  --keyword "gentle cleanser" \
  --target-count 1000 \
  --page-size 250
```

Ingest TopYappers viral UGC:

```bash
PYTHONPATH=src python3 -m instaagent_pipeline.cli ingest-topyappers-viral \
  --run-id "<pipeline_run_id>" \
  --keyword "gentle cleanser" \
  --target-count 2500 \
  --page-size 100
```

Hydrate TopYappers videos:

```bash
PYTHONPATH=src python3 -m instaagent_pipeline.cli ingest-topyappers-videos \
  --run-id "<pipeline_run_id>" \
  --target-count 2500 \
  --page-size 100
```

Use `--dry-run` to fetch/parse without writing to Supabase, or `--input-json path/to/response.json` to normalize a saved API payload.

## Required Environment Variables

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `FOREPLAY_API_KEY`
- `TOPYAPPERS_API_KEY`

Optional:

- `FOREPLAY_BASE_URL`
- `TOPYAPPERS_BASE_URL`

