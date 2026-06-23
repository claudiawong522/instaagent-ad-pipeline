# InstaAgent Ad Pipeline

Lean ingestion and transcript-backfill foundation for InstaAgent's ad selection pipeline.

## What Exists Now

- `PLAN.md`: full future plan.
- `api-endpoints.md`: endpoint inputs, outputs, and storage mappings.
- `future-add-ons.md`: good ideas deferred for later.
- `supabase/schema.sql`: canonical fresh-project Supabase schema for the implemented pipeline.
- `supabase/migrations/`: incremental migrations for existing Supabase projects. Verify a live database against these before adding search/clustering on top of old data.
  - `001_split_paid_ads_and_ugc.sql`: split the obsolete shared creative table into paid ads and UGC tables.
  - `002_topyappers_columns.sql` and `003_ugc_saved_to_supabase_at.sql`: early UGC column patches, superseded by `004` for newer databases.
  - `004_topyappers_exact_shape.sql`: reset `ugc_items` to the TopYappers-shaped table.
  - `005_paid_ads_apify_shape.sql`: reset `paid_ads` to the Apify Meta Ad Library-shaped table.
  - `006_ugc_video_url.sql` through `012_paid_ads_analysis_columns.sql`: add URL, JSONB overflow, cleanup, allocation, transcript-upsert, and analysis columns/indexes.
  - `013_item_embeddings.sql`: add pgvector item embeddings.
  - `014_item_clusters.sql`: add ICP cluster assignments and cluster labels.
  - `015_search_space_descriptions_storage.sql`: add the `search` embedding space, `ai_description`/storage URL columns, UGC analysis parity columns, the `match_item_embeddings` RPC, and the `ad-videos` storage bucket.
  - `016_item_enrichments.sql`: add the polymorphic `item_enrichments` table (with backfill), and drop `paid_ad_transcripts`/`ugc_transcripts` plus migrated/unused analysis columns.
- Python CLI for:
  - creating products/runs and Claude-generated keyword allocations.
  - ingesting Apify Meta Ad Library paid ad candidates into `paid_ads` across stored keyword allocations.
  - ingesting Apify TikTok UGC candidates into `ugc_items` (with native follower counts) across stored keyword allocations.
  - ingesting Apify Instagram search reels into `ugc_items`, with follower counts backfilled via `backfill-ig-followers`.
  - transcribing + analyzing paid ads and UGC videos via OpenRouter vision into `item_enrichments` (auto-runs after ingestion).
  - embedding items (`icp` and `search` spaces) and clustering ICP embeddings for paid ads and UGC.

## Setup

1. Create or reuse a Supabase project.
2. For a clean database, run `supabase/schema.sql` in the Supabase SQL editor.
3. For an existing live database, verify the live schema matches `supabase/schema.sql` plus the committed migrations before building search or clustering on top of it. If manual edits or out-of-order migrations caused heavy drift, export anything you need, rebuild the schema cleanly in the same project from `supabase/schema.sql`, then start a fresh run as the canonical corpus. Use a second project later only when you need production isolation.
4. Copy `.env.example` to `.env` and fill in local secrets, or export the same variables in your shell.
5. Install the local package and Python dependencies:

```bash
python3 -m pip install -e .
```

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

Ingest Apify TikTok UGC:

```bash
PYTHONPATH=src python3 -m instaagent_pipeline.cli ingest-tiktok \
  --run-id "<pipeline_run_id>"
```

Ingest Apify Instagram search reels:

```bash
PYTHONPATH=src python3 -m instaagent_pipeline.cli ingest-instagram \
  --run-id "<pipeline_run_id>"
```

Like paid ads, UGC ingestion auto-runs vision enrichment (transcribe + analyze each video into `item_enrichments`). Pass `--skip-enrichment` to ingest only UGC rows without running the enrichment stage.

Backfill Instagram follower counts (via Apify):

```bash
PYTHONPATH=src python3 -m instaagent_pipeline.cli backfill-ig-followers \
  --run-id "<pipeline_run_id>"
```

Omit `--keyword` to use stored keyword allocations. Pass `--keyword` and `--target-count` to run one manual keyword for debugging or backfills.

Use `--dry-run` to fetch/parse without writing to Supabase, or `--input-json path/to/response.json` to normalize a saved API payload. For ingestion commands, `--dry-run` with omitted `--keyword` is not supported because stored keywords must be loaded from Supabase.

Generate icp and search embeddings for analyzed items into `item_embeddings` (on existing databases, run `supabase/migrations/013_item_embeddings.sql` first):

```bash
PYTHONPATH=src python3 -m instaagent_pipeline.cli embed-items \
  --run-id "<pipeline_run_id>" \
  --source all \
  --limit 1000
```

Cluster ICP embeddings into `item_clusters` and `clusters` (on existing databases, run `supabase/migrations/014_item_clusters.sql` first):

```bash
PYTHONPATH=src python3 -m instaagent_pipeline.cli cluster-items \
  --run-id "<pipeline_run_id>" \
  --source all \
  --min-cluster-size 5
```

## Required Environment Variables

- `SUPABASE_URL`
  - Either `https://your-project.supabase.co` or `https://your-project.supabase.co/rest/v1/` works.
- `SUPABASE_SERVICE_ROLE_KEY` or `SUPABASE_ANON_KEY`
- `CLAUDE_API_KEY`
- `APIFY_API_KEY`
  - Required for paid-ad ingestion (`ingest-apify-ads`), UGC ingestion (`ingest-tiktok`/`ingest-instagram`), and Instagram follower backfill (`backfill-ig-followers`).
- `OPENROUTER_API_KEY`
  - Required for paid-ad and UGC enrichment, and cluster labeling.
- `VOYAGE_API_KEY`
  - Required for `embed-items`.

Optional:

- `CLAUDE_MODEL`
  - Defaults to `claude-haiku-4-5`.
- `OPENROUTER_MODEL`
  - Defaults to `google/gemini-3-flash-preview`.
- `EMBEDDING_MODEL`
  - Defaults to `voyage-4-lite` (1024-dim vectors; the `item_embeddings.embedding` column is `vector(1024)`).
- `INSTAAGENT_INSECURE_SSL=1`
  - Local dev workaround only if this Python install cannot verify HTTPS certificates.
  - Do not use this in production.

## Supabase Key Choice

Use the service role key for this local/server-side ingestion CLI when possible. It bypasses row-level security, which makes batch writes to `products`, `pipeline_runs`, `source_queries`, `api_usage`, `raw_payloads`, `paid_ads`, `ugc_items`, `item_enrichments`, `item_embeddings`, `item_clusters`, and `clusters` straightforward.

Use the anon public key only if you intentionally enable RLS policies that allow this CLI to insert/update the needed tables. The anon key is designed for browser/client usage and should not have broad write permissions to ingestion tables.

The service role key can write rows through the Supabase REST API after tables exist. It cannot create this schema through PostgREST, so run `supabase/schema.sql` in the Supabase SQL editor first.

## Existing Database Migration

`supabase/schema.sql` is the canonical schema for a clean database. Existing databases should be checked against the committed migration set before search or clustering work continues. If the live schema has only normal pending migrations, run the pending files in `supabase/migrations/` in numeric order from the last migration you know was applied. The current set is `001` through `016`; do not apply superseded early UGC patches after `004_topyappers_exact_shape.sql` unless you are intentionally replaying the full history from an older state.

If the live database has heavy drift from manual edits or out-of-order migration attempts, prefer a clean rebuild in the same Supabase project from `supabase/schema.sql`, then start a fresh run and treat that run as the canonical corpus. Add a separate project later only for production isolation, not just to avoid cleaning up development drift.

To copy one migration for the Supabase SQL editor:

```bash
cat supabase/migrations/016_item_enrichments.sql | pbcopy
```
