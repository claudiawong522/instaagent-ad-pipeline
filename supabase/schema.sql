create extension if not exists pgcrypto;
create extension if not exists vector;

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
  target_tiktok_count integer not null default 2500,
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
  target_paid_count integer not null default 0,
  target_ugc_count integer not null default 0,
  target_tiktok_count integer not null default 0,
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

create table if not exists paid_ads (
  paid_ad_row_id uuid primary key default gen_random_uuid(),
  run_id uuid not null references pipeline_runs(id) on delete cascade,
  raw_payload_id uuid references raw_payloads(id) on delete set null,
  id text not null,
  live boolean,
  name text,
  type text,
  ad_id text,
  cards jsonb,
  image text,
  video text,
  avatar text,
  brand_id text,
  cta_type text,
  headline text,
  link_url text,
  cta_title text,
  languages jsonb,
  thumbnail text,
  categories jsonb,
  description text,
  display_format text,
  video_duration numeric,
  started_running numeric,
  running_duration numeric,
  publisher_platform jsonb,
  storage_video_url text,
  storage_thumb_url text,
  -- Per-video enrichment outcome (see migration 021): 'enriched' (searchable),
  -- 'expired' (URL no longer serves video), 'failed' (analysis produced nothing).
  enrichment_status text,
  enrichment_error text,
  source_metrics jsonb not null default '{}'::jsonb,
  saved_to_supabase_at timestamptz not null default now(),
  unique (run_id, id)
);

-- Trend pipeline (see migrations/025): one row per viral format scraped from a web trend
-- page; example videos link via ugc_items.format_id. Defined before ugc_items for the FK.
create table if not exists viral_formats (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references pipeline_runs(id) on delete cascade,
  source_name text not null,
  source_url text,
  content_hash text,
  issue_date date,
  format_name text not null,
  format_description text,
  niche_constraint text,
  niche_constraint_model text,
  classified_at timestamptz,
  created_at timestamptz not null default now(),
  unique (source_name, format_name)
);

create table if not exists ugc_items (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references pipeline_runs(id) on delete cascade,
  raw_payload_id uuid references raw_payloads(id) on delete set null,
  external_id text not null,
  avatar text,
  comments bigint,
  cover text,
  date_created timestamptz,
  description text,
  followers bigint,
  handle text,
  hashtags jsonb,
  likes bigint,
  music jsonb,
  nickname text,
  shares bigint,
  source text,
  user_handle text,
  user_id text,
  video_id text,
  video_url text,
  views bigint,
  virality_score numeric,
  virality_tier text,
  storage_video_url text,
  storage_thumb_url text,
  -- Per-video enrichment outcome (see migration 021): 'enriched' (searchable),
  -- 'expired' (URL no longer serves video), 'failed' (analysis produced nothing).
  enrichment_status text,
  enrichment_error text,
  -- Trend-pipeline link (see migration 025): example videos of a viral_formats row.
  format_id uuid references viral_formats(id) on delete cascade,
  source_metrics jsonb not null default '{}'::jsonb,
  saved_to_supabase_at timestamptz not null default now(),
  unique (run_id, external_id)
);

create table if not exists item_enrichments (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references pipeline_runs(id) on delete cascade,
  item_type text not null check (item_type in ('paid_ad', 'ugc_item')),
  item_id uuid not null,
  transcript_text text,
  transcript_segments jsonb,
  ai_description text,
  hook text,
  main_category text,
  content_category text,
  content_format text,
  content_tone text,
  primary_emotion text,
  target_demographic text,
  video_topic text,
  visual_style text,
  production_quality text,
  setting text,
  product_category text,
  has_product boolean,
  has_text_overlay boolean,
  is_trending_format boolean,
  persona jsonb,
  niches jsonb,
  emotional_drivers jsonb,
  brand_mentioned jsonb,
  time_product_was_mentioned numeric,
  analysis_model text,
  analyzed_at timestamptz,
  created_at timestamptz not null default now(),
  unique (item_type, item_id)
);

create table if not exists item_embeddings (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references pipeline_runs(id) on delete cascade,
  item_type text not null check (item_type in ('paid_ad', 'ugc_item')),
  item_id uuid not null,
  space text not null check (space in ('icp', 'format', 'hook', 'search')),
  embedding_model text not null,
  source_text text not null,
  embedding vector(1024) not null,
  created_at timestamptz not null default now(),
  unique (item_type, item_id, space, embedding_model)
);

create table if not exists item_clusters (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references pipeline_runs(id) on delete cascade,
  item_type text not null check (item_type in ('paid_ad', 'ugc_item')),
  item_id uuid not null,
  space text not null check (space in ('icp', 'format', 'hook')),
  cluster_label integer not null,
  distance_to_centroid double precision,
  clustering_params text not null,
  created_at timestamptz not null default now(),
  unique (item_type, item_id, space)
);

create table if not exists clusters (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references pipeline_runs(id) on delete cascade,
  item_type text not null check (item_type in ('paid_ad', 'ugc_item')),
  space text not null check (space in ('icp', 'format', 'hook')),
  cluster_label integer not null,
  name text,
  label_json jsonb,
  label_text text,
  centroid vector(1024),
  member_count integer not null,
  exemplar_item_ids jsonb,
  silhouette double precision,
  label_model text,
  clustering_params text not null,
  created_at timestamptz not null default now(),
  unique (run_id, item_type, space, cluster_label)
);

-- One row per UI scrape trigger; powers the per-scrape cost shown on the campaigns page.
-- estimated_cost_usd is set before the scrape; actual_cost_usd is reconciled from api_usage after
-- it finishes (Apify usageTotalUsd + token-priced LLM/embeds). See src/instaagent_pipeline/costs.py.
create table if not exists scrape_events (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references pipeline_runs(id) on delete cascade,
  platform text not null,
  target_count integer,
  items_ingested integer,
  estimated_cost_usd numeric,
  actual_cost_usd numeric,
  status text not null default 'running',
  error_message text,                     -- out-of-credits detail for the UI (null = no billing problem)
  started_at timestamptz not null default now(),
  finished_at timestamptz
);

create index if not exists keywords_run_id_idx on keywords(run_id);
create index if not exists source_queries_run_id_idx on source_queries(run_id);
create index if not exists raw_payloads_run_id_idx on raw_payloads(run_id);
create index if not exists paid_ads_run_id_idx on paid_ads(run_id);
create index if not exists paid_ads_id_idx on paid_ads(id);
create index if not exists paid_ads_ad_id_idx on paid_ads(ad_id);
create index if not exists paid_ads_brand_id_idx on paid_ads(brand_id);
create index if not exists paid_ads_saved_to_supabase_at_idx on paid_ads(saved_to_supabase_at desc);
create index if not exists ugc_items_run_id_idx on ugc_items(run_id);
create index if not exists ugc_items_external_idx on ugc_items(external_id);
create index if not exists ugc_items_video_id_idx on ugc_items(video_id);
create index if not exists ugc_items_virality_idx on ugc_items(virality_score desc);
create index if not exists ugc_items_saved_to_supabase_at_idx on ugc_items(saved_to_supabase_at desc);
create index if not exists paid_ads_enrichment_status_idx on paid_ads(run_id, enrichment_status);
create index if not exists ugc_items_enrichment_status_idx on ugc_items(run_id, enrichment_status);
create index if not exists item_enrichments_run_idx on item_enrichments(run_id);
create index if not exists item_enrichments_item_idx on item_enrichments(item_type, item_id);
create index if not exists item_embeddings_run_idx on item_embeddings(run_id);
create index if not exists item_embeddings_space_idx on item_embeddings(item_type, space);
create index if not exists item_clusters_run_idx on item_clusters(run_id);
create index if not exists item_clusters_cluster_idx on item_clusters(item_type, space, cluster_label);
create index if not exists clusters_run_idx on clusters(run_id);
create index if not exists clusters_lookup_idx on clusters(item_type, space);
create index if not exists scrape_events_run_idx on scrape_events(run_id, started_at desc);
create index if not exists viral_formats_run_idx on viral_formats(run_id, created_at desc);
create index if not exists ugc_items_format_idx on ugc_items(format_id);

-- Search layer (see migrations/015): a cosine KNN index + function for query search.
-- Enrichment (description, transcript, analysis tags) lives in item_enrichments
-- (see migrations/016); persisted media URLs live on paid_ads/ugc_items directly.
create index if not exists item_embeddings_search_hnsw
  on item_embeddings using hnsw (embedding vector_cosine_ops)
  where space = 'search';

-- The search path also queries the 'icp' space (see api/search.py); index it too so
-- that KNN stays sub-linear instead of a full scan (see migrations/019).
create index if not exists item_embeddings_icp_hnsw
  on item_embeddings using hnsw (embedding vector_cosine_ops)
  where space = 'icp';

create or replace function match_item_embeddings(
  p_query vector(1024),
  p_space text default 'search',
  p_item_type text default null,
  p_model text default 'voyage-4-lite',
  p_run_id uuid default null,
  p_limit int default 20,
  p_min_similarity double precision default 0.0
)
returns table (
  item_type text,
  item_id uuid,
  source_text text,
  similarity double precision
)
language sql
stable
as $$
  select
    ie.item_type,
    ie.item_id,
    ie.source_text,
    1 - (ie.embedding <=> p_query) as similarity
  from item_embeddings ie
  where ie.space = p_space
    and ie.embedding_model = p_model
    and (p_item_type is null or ie.item_type = p_item_type)
    and (p_run_id is null or ie.run_id = p_run_id)
    and (1 - (ie.embedding <=> p_query)) >= p_min_similarity
  order by ie.embedding <=> p_query
  limit p_limit;
$$;
