# InstaAgent Ad Pipeline

[![CI](https://github.com/claudiawong522/instaagent-ad-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/claudiawong522/instaagent-ad-pipeline/actions/workflows/ci.yml)

Finds winning ad creative for a product. Scrapes competitor paid ads and organic video, enriches each with vision AI, then clusters and surfaces the results in a dashboard.

**Live demo → _(add Vercel URL after deploy)_**

---

## What it does

```
scrape → enrich → embed → cluster → dashboard
```

- **Scrape** — paid ads from the Meta Ad Library (via Apify) plus organic TikTok & Instagram video.
- **Enrich** — transcribe and analyze every video with vision AI.
- **Embed & cluster** — group creative by ICP so patterns are searchable.
- **Trends** — a daily job pulls viral video *formats* from marketing trend pages.
- **Dashboard** — a Next.js app to search, discover, and browse trends.

## Stack

| Layer | Tech |
|-------|------|
| Pipeline | Python CLI |
| Data | Supabase (Postgres + pgvector) |
| AI | Claude · OpenRouter vision · Voyage embeddings |
| Sources | Apify (Meta Ad Library, TikTok, Instagram) |
| Frontend | Next.js 14 + Tailwind → Vercel |

## Quickstart

```bash
# 1. install
python3 -m pip install -e .

# 2. configure — copy .env.example to .env and fill in secrets
cp .env.example .env

# 3. set up the database
# run supabase/schema.sql in the Supabase SQL editor

# 4. run the pipeline
PYTHONPATH=src python3 -m instaagent_pipeline.cli init-run \
  --product-name "QE cleanser" --category "skincare" \
  --target-market "US skincare buyers" \
  --campaign-guidelines "Competitor ads for a gentle cleanser launch." \
  --target-paid-count 1000 --target-organic-count 2500

PYTHONPATH=src python3 -m instaagent_pipeline.cli ingest-apify-ads --run-id "<run_id>"
PYTHONPATH=src python3 -m instaagent_pipeline.cli ingest-tiktok    --run-id "<run_id>"
PYTHONPATH=src python3 -m instaagent_pipeline.cli embed-items      --run-id "<run_id>"
PYTHONPATH=src python3 -m instaagent_pipeline.cli cluster-items    --run-id "<run_id>"
```

Ingestion auto-runs vision enrichment. Add `--dry-run` to any command to preview without writing.

## Environment

Required: `SUPABASE_URL` · `SUPABASE_SERVICE_ROLE_KEY` · `CLAUDE_API_KEY` · `APIFY_API_KEY` · `OPENROUTER_API_KEY` · `VOYAGE_API_KEY`

The service role key is **server-side only** — it bypasses row-level security, so never ship it to the browser. `.env` is gitignored; don't commit keys.

## More

- **`AGENTS.md`** — project shape and implementation notes.
- **`database.md`** — schema and table docs.
- **`supabase/migrations/`** — run in numeric order on existing databases before search/clustering work.
- **`frontend/`** — the dashboard (`npm run dev`).
