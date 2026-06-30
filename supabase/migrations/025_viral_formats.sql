-- Viral-format trend pipeline (web sources). One row per trend/format scraped from a
-- web trend page (Ramdam, Newengen, ...); example videos hang off it via ugc_items.format_id.
-- A format is ranked on the dashboard by its videos' aggregate live views. The free-form
-- niche_constraint (which marketing niches the format suits) is written by classify-formats.
create table if not exists viral_formats (
  id uuid primary key default gen_random_uuid(),
  -- One persistent "trends" pipeline_run per source (config->>'trend_source'); the dashboard
  -- aggregates across re-fetches and dedups on (source_name, format_name).
  run_id uuid not null references pipeline_runs(id) on delete cascade,
  source_name text not null,              -- e.g. ramdam, newengen
  source_url text,                        -- the page the format was parsed from
  content_hash text,                      -- sha256 of the fetched page; skip re-parse when unchanged
  issue_date date,                        -- the page's publish/update date when known
  format_name text not null,
  format_description text,                -- the trend description as written on the page
  niche_constraint text,                  -- free-form, LLM-written (classify-formats)
  niche_constraint_model text,
  classified_at timestamptz,
  created_at timestamptz not null default now(),
  unique (source_name, format_name)       -- idempotent re-ingest
);

create index if not exists viral_formats_run_idx on viral_formats(run_id, created_at desc);

-- Example videos live in ugc_items (source='trend'); link each to its format.
alter table ugc_items
  add column if not exists format_id uuid references viral_formats(id) on delete cascade;

create index if not exists ugc_items_format_idx on ugc_items(format_id);
