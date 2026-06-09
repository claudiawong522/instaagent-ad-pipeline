create extension if not exists pgcrypto;

create table if not exists products (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  category text,
  target_market text,
  notes text,
  created_at timestamptz not null default now()
);

create table if not exists pipeline_runs (
  id uuid primary key default gen_random_uuid(),
  product_id uuid not null references products(id) on delete cascade,
  status text not null default 'created',
  config jsonb not null default '{}'::jsonb,
  target_paid_count integer not null default 1000,
  target_ugc_count integer not null default 2500,
  top_k integer not null default 3,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists keywords (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references pipeline_runs(id) on delete cascade,
  keyword_text text not null,
  keyword_type text not null default 'seed',
  source text not null default 'manual',
  active boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists source_queries (
  id uuid primary key default gen_random_uuid(),
  run_id uuid references pipeline_runs(id) on delete cascade,
  provider text not null,
  endpoint text not null,
  method text not null,
  request_params jsonb not null default '{}'::jsonb,
  page_cursor text,
  status text not null default 'started',
  http_status integer,
  response_count integer,
  error_message text,
  started_at timestamptz not null default now(),
  completed_at timestamptz
);

create table if not exists api_usage (
  id uuid primary key default gen_random_uuid(),
  run_id uuid references pipeline_runs(id) on delete set null,
  provider text not null,
  endpoint text not null,
  credits_used numeric,
  rate_limit jsonb not null default '{}'::jsonb,
  request_timestamp timestamptz not null default now()
);

create table if not exists raw_payloads (
  id uuid primary key default gen_random_uuid(),
  run_id uuid references pipeline_runs(id) on delete cascade,
  source_query_id uuid references source_queries(id) on delete set null,
  provider text not null,
  endpoint text not null,
  external_id text,
  payload_json jsonb not null,
  payload_storage_path text,
  fetched_at timestamptz not null default now()
);

create table if not exists creative_items (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references pipeline_runs(id) on delete cascade,
  raw_payload_id uuid references raw_payloads(id) on delete set null,
  source_type text not null,
  source_provider text not null,
  external_id text not null,
  url text,
  media_url text,
  thumbnail_url text,
  creator_or_brand text,
  caption text,
  platform text,
  display_format text,
  posted_at timestamptz,
  started_running_at timestamptz,
  running_duration_days numeric,
  source_metrics jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (run_id, source_provider, external_id)
);

create table if not exists transcripts (
  id uuid primary key default gen_random_uuid(),
  creative_item_id uuid not null references creative_items(id) on delete cascade,
  transcript_text text,
  transcript_segments jsonb,
  transcript_source text,
  created_at timestamptz not null default now()
);

create index if not exists keywords_run_id_idx on keywords(run_id);
create index if not exists source_queries_run_id_idx on source_queries(run_id);
create index if not exists raw_payloads_run_id_idx on raw_payloads(run_id);
create index if not exists creative_items_run_id_idx on creative_items(run_id);
create index if not exists creative_items_source_idx on creative_items(source_provider, source_type);
create index if not exists creative_items_external_idx on creative_items(source_provider, external_id);

