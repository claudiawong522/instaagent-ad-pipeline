# InstaAgent Ad Pipeline

Lean ingestion and transcript-backfill foundation for InstaAgent's ad selection pipeline.

## What Exists Now

- `PLAN.md`: full future plan.
- `api-endpoints.md`: endpoint inputs, outputs, and storage mappings.
- `future-add-ons.md`: good ideas deferred for later.
- `supabase/schema.sql`: Supabase tables for run setup and source ingestion.
- `supabase/migrations/001_split_paid_ads_and_ugc.sql`: migration for databases that already ran the first shared-table schema.
- `supabase/migrations/002_topyappers_columns.sql`: migration that adds columns matching TopYappers UGC JSON fields.
- `supabase/migrations/003_ugc_saved_to_supabase_at.sql`: migration that logs when each UGC video row was saved to Supabase.
- `supabase/migrations/004_topyappers_exact_shape.sql`: migration that resets `ugc_items` to columns matching TopYappers JSON fields.
- `supabase/migrations/005_paid_ads_apify_shape.sql`: migration that resets `paid_ads` to columns used by Apify Meta Ad Library paid ad JSON fields.
- `supabase/migrations/006_ugc_video_url.sql`: migration that adds the TopYappers video URL column if an existing project is missing it.
- `supabase/migrations/007_source_metrics_jsonb.sql`: migration that adds JSONB overflow fields for provider-specific metadata.
- `supabase/migrations/008_drop_creative_items.sql`: migration that removes obsolete shared-table schema tables from existing projects.
- `supabase/migrations/009_keyword_allocations.sql`: migration that adds per-keyword paid ad and UGC target allocations.
- `supabase/migrations/010_ugc_transcript_source_unique.sql`: migration that lets UGC transcript backfills upsert by item and transcript source.
- Python CLI for:
  - creating products/runs and Claude-generated keyword allocations.
  - ingesting Apify Meta Ad Library paid ad candidates into `paid_ads` across stored keyword allocations.
  - ingesting URL-backed TopYappers viral-content UGC candidates into `ugc_items` across stored keyword allocations.
  - optionally ingesting TopYappers videos metadata into `ugc_items` when URLs are not required.
  - backfilling missing UGC transcripts from public social video URLs through Apify.

## Setup

1. Create a Supabase project.
2. Run `supabase/schema.sql` in the Supabase SQL editor.
3. Copy `.env.example` to `.env` and fill in local secrets, or export the same variables in your shell.

No third-party Python packages are required.

`.env` is gitignored. Do not commit API keys or Supabase service role keys.

## Example Commands

Create a run:

```bash
PYTHONPATH=src python3 -m instaagent_pipeline.cli init-run \
  --product-name "QE cleanser" \
  --category "skincare" \
  --target-market "US skincare buyers" \
  --campaign-guidelines "Find competitor ads and UGC for a gentle cleanser launch." \
  --target-paid-count 1000 \
  --target-ugc-count 2500
```

Ingest Apify Meta Ad Library paid ads:

```bash
PYTHONPATH=src python3 -m instaagent_pipeline.cli ingest-apify-ads \
  --run-id "<pipeline_run_id>"
```

Ingest TopYappers URL-backed UGC:

```bash
PYTHONPATH=src python3 -m instaagent_pipeline.cli ingest-topyappers-viral \
  --run-id "<pipeline_run_id>" \
  --page-size 100
```

After live TopYappers ingestion, the CLI automatically copies TopYappers `subtitles` into `ugc_transcripts`, then uses Apify for supported public video URLs that still do not have a transcript. Pass `--skip-transcript-backfill` to ingest only UGC rows without running the transcript stage.

Optionally ingest TopYappers metadata-only video records:

```bash
PYTHONPATH=src python3 -m instaagent_pipeline.cli ingest-topyappers-videos \
  --run-id "<pipeline_run_id>" \
  --page-size 100
```

Omit `--keyword` to use stored keyword allocations. Pass `--keyword` and `--target-count` to run one manual keyword for debugging or backfills.

Use `--dry-run` to fetch/parse without writing to Supabase, or `--input-json path/to/response.json` to normalize a saved API payload. For ingestion commands, `--dry-run` with omitted `--keyword` is not supported because stored keywords must be loaded from Supabase.

Backfill or rerun UGC transcript extraction:

```bash
PYTHONPATH=src python3 -m instaagent_pipeline.cli backfill-ugc-transcripts \
  --run-id "<pipeline_run_id>" \
  --limit 25
```

This first copies TopYappers `subtitles` into `ugc_transcripts`, then calls Apify for supported public social video URLs that remain missing a transcript. Use `--skip-apify` to copy only provider subtitles.

Preview candidates without calling Apify or writing transcripts:

```bash
PYTHONPATH=src python3 -m instaagent_pipeline.cli backfill-ugc-transcripts \
  --run-id "<pipeline_run_id>" \
  --limit 25 \
  --dry-run
```

Generate icp/format/hook embeddings for analyzed items into `item_embeddings` (run `supabase/migrations/013_item_embeddings.sql` first):

```bash
PYTHONPATH=src python3 -m instaagent_pipeline.cli embed-items \
  --run-id "<pipeline_run_id>" \
  --source all \
  --limit 1000
```

## Required Environment Variables

- `SUPABASE_URL`
  - Either `https://your-project.supabase.co` or `https://your-project.supabase.co/rest/v1/` works.
- `SUPABASE_SERVICE_ROLE_KEY` or `SUPABASE_ANON_KEY`
- `TOPYAPPERS_API_KEY`
- `CLAUDE_API_KEY`
- `APIFY_API_KEY`
  - Required for `ingest-apify-ads` and Apify-backed UGC transcript fallback.
- `VOYAGE_API_KEY`
  - Required for `embed-items`.

Optional:

- `TOPYAPPERS_BASE_URL`
- `CLAUDE_MODEL`
  - Defaults to `claude-haiku-4-5`.
- `EMBEDDING_MODEL`
  - Defaults to `voyage-4-lite` (1024-dim vectors; the `item_embeddings.embedding` column is `vector(1024)`).
- `INSTAAGENT_INSECURE_SSL=1`
  - Local dev workaround only if this Python install cannot verify HTTPS certificates.
  - Do not use this in production.

## Supabase Key Choice

Use the service role key for this local/server-side ingestion CLI when possible. It bypasses row-level security, which makes batch writes to `products`, `pipeline_runs`, `source_queries`, `api_usage`, `raw_payloads`, `paid_ads`, and `ugc_items` straightforward.

Use the anon public key only if you intentionally enable RLS policies that allow this CLI to insert/update the needed tables. The anon key is designed for browser/client usage and should not have broad write permissions to ingestion tables.

The service role key can write rows through the Supabase REST API after tables exist. It cannot create this schema through PostgREST, so run `supabase/schema.sql` in the Supabase SQL editor first.

## Existing Database Migration

If you already ran the first shared-table version, run this migration in the Supabase SQL editor too:

```bash
cat supabase/migrations/001_split_paid_ads_and_ugc.sql | pbcopy
```

Then paste and run it in Supabase.

After that, run the TopYappers exact-shape migration. This supersedes the earlier TopYappers column migrations and removes old normalized UGC columns:

```bash
cat supabase/migrations/004_topyappers_exact_shape.sql | pbcopy
```

Then paste and run it in Supabase.

Then run the Apify paid ad shape migration:

```bash
cat supabase/migrations/005_paid_ads_apify_shape.sql | pbcopy
```

Then paste and run it in Supabase.

Then run the UGC video URL patch migration if your existing `ugc_items` table is missing `video_url`:

```bash
cat supabase/migrations/006_ugc_video_url.sql | pbcopy
```

Then paste and run it in Supabase.

Then run the JSONB source metrics migration:

```bash
cat supabase/migrations/007_source_metrics_jsonb.sql | pbcopy
```

Then paste and run it in Supabase.

Then remove obsolete shared-table schema tables:

```bash
cat supabase/migrations/008_drop_creative_items.sql | pbcopy
```

Then paste and run it in Supabase.

Then add keyword allocation columns:

```bash
cat supabase/migrations/009_keyword_allocations.sql | pbcopy
```

Then paste and run it in Supabase.

Then add the UGC transcript source uniqueness index:

```bash
cat supabase/migrations/010_ugc_transcript_source_unique.sql | pbcopy
```

Then paste and run it in Supabase.
