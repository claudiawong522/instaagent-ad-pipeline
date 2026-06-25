-- One row per UI scrape trigger, so the campaigns page can show the cost of each scrape.
-- A "scrape" is one click of Scrape / Scrape more for a platform; it runs the full chain
-- (Apify ingest -> LLM enrichment -> embeddings). estimated_cost_usd is computed before the
-- scrape (blended $/item x new items, see costs.py); actual_cost_usd is reconciled from the
-- run's api_usage rows after the scrape finishes (Apify usageTotalUsd + token-priced LLM/embeds).
-- Per-provider breakdown is intentionally not stored -- the UI only shows the summed total.
create table if not exists scrape_events (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references pipeline_runs(id) on delete cascade,
  platform text not null,                 -- facebook | instagram | tiktok
  target_count integer,                   -- new total requested for the platform
  items_ingested integer,                 -- rows actually written (filled on completion)
  estimated_cost_usd numeric,             -- pre-scrape estimate
  actual_cost_usd numeric,                -- reconciled after the scrape finishes (null until done)
  status text not null default 'running', -- running | done | failed
  started_at timestamptz not null default now(),
  finished_at timestamptz
);

create index if not exists scrape_events_run_idx on scrape_events(run_id, started_at desc);
