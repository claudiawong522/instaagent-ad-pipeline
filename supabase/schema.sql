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
  niches jsonb,
  persona jsonb,
  brand_id text,
  cta_type text,
  headline text,
  link_url text,
  cta_title text,
  languages jsonb,
  thumbnail text,
  categories jsonb,
  description text,
  market_target text,
  content_filter jsonb,
  display_format text,
  video_duration numeric,
  started_running numeric,
  product_category text,
  running_duration numeric,
  emotional_drivers jsonb,
  creative_targeting text,
  full_transcription text,
  publisher_platform jsonb,
  timestamped_transcription jsonb,
  time_product_was_mentioned numeric,
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
  color_palette jsonb,
  has_face boolean,
  face_count integer,
  gender text,
  age integer,
  race text,
  hair_color text,
  has_product boolean,
  has_text_overlay boolean,
  is_ai_generated boolean,
  is_trending_format boolean,
  brand_mentioned jsonb,
  analysis_model text,
  analyzed_at timestamptz,
  source_metrics jsonb not null default '{}'::jsonb,
  saved_to_supabase_at timestamptz not null default now(),
  unique (run_id, id)
);

create table if not exists ugc_items (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references pipeline_runs(id) on delete cascade,
  raw_payload_id uuid references raw_payloads(id) on delete set null,
  external_id text not null,
  topyappers_id text,
  iv_id text,
  account_type text,
  age integer,
  avatar text,
  bio text,
  brand_mentioned jsonb,
  categories jsonb,
  color_palette jsonb,
  comments bigint,
  comments_to_views_ratio numeric,
  content_category text,
  content_format text,
  content_tone text,
  country text,
  cover text,
  creator_avg_views numeric,
  creator_engagement_rate numeric,
  creator_language text,
  cta_type text,
  date_added timestamptz,
  date_created timestamptz,
  date_created_timestamp numeric,
  description text,
  face_count integer,
  follower_tier text,
  followers bigint,
  gender text,
  hair_color text,
  handle text,
  has_face boolean,
  has_product boolean,
  has_text_overlay boolean,
  hashtags jsonb,
  hook text,
  is_ai_generated boolean,
  is_branded boolean,
  is_promotional boolean,
  is_trending_format boolean,
  likes bigint,
  likes_to_views_ratio numeric,
  main_category text,
  music jsonb,
  nickname text,
  primary_emotion text,
  product_category text,
  production_quality text,
  race text,
  setting text,
  shares bigint,
  shares_to_views_ratio numeric,
  source text,
  subtitles text,
  target_demographic text,
  user_followers bigint,
  user_handle text,
  user_id text,
  video_id text,
  video_url text,
  video_ranges jsonb,
  video_topic text,
  views bigint,
  views_to_avg_ratio numeric,
  virality_score numeric,
  virality_tier text,
  visual_style text,
  source_metrics jsonb not null default '{}'::jsonb,
  saved_to_supabase_at timestamptz not null default now(),
  unique (run_id, external_id)
);

create table if not exists paid_ad_transcripts (
  id uuid primary key default gen_random_uuid(),
  paid_ad_row_id uuid not null references paid_ads(paid_ad_row_id) on delete cascade,
  transcript_text text,
  transcript_segments jsonb,
  transcript_source text,
  created_at timestamptz not null default now()
);

create table if not exists ugc_transcripts (
  id uuid primary key default gen_random_uuid(),
  ugc_item_id uuid not null references ugc_items(id) on delete cascade,
  transcript_text text,
  transcript_segments jsonb,
  transcript_source text,
  created_at timestamptz not null default now()
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

create index if not exists keywords_run_id_idx on keywords(run_id);
create index if not exists source_queries_run_id_idx on source_queries(run_id);
create index if not exists raw_payloads_run_id_idx on raw_payloads(run_id);
create index if not exists paid_ads_run_id_idx on paid_ads(run_id);
create index if not exists paid_ads_id_idx on paid_ads(id);
create index if not exists paid_ads_ad_id_idx on paid_ads(ad_id);
create index if not exists paid_ads_brand_id_idx on paid_ads(brand_id);
create index if not exists paid_ads_saved_to_supabase_at_idx on paid_ads(saved_to_supabase_at desc);
create index if not exists paid_ads_product_category_idx on paid_ads(product_category);
create index if not exists paid_ads_analyzed_at_idx on paid_ads(analyzed_at);
create index if not exists paid_ads_content_category_idx on paid_ads(content_category);
create index if not exists paid_ads_video_topic_idx on paid_ads(video_topic);
create index if not exists ugc_items_run_id_idx on ugc_items(run_id);
create index if not exists ugc_items_external_idx on ugc_items(external_id);
create index if not exists ugc_items_video_id_idx on ugc_items(video_id);
create index if not exists ugc_items_video_topic_idx on ugc_items(video_topic);
create index if not exists ugc_items_content_category_idx on ugc_items(content_category);
create index if not exists ugc_items_virality_idx on ugc_items(virality_score desc);
create index if not exists ugc_items_saved_to_supabase_at_idx on ugc_items(saved_to_supabase_at desc);
create unique index if not exists ugc_transcripts_item_source_idx on ugc_transcripts(ugc_item_id, transcript_source);
create unique index if not exists paid_ad_transcripts_row_source_idx on paid_ad_transcripts(paid_ad_row_id, transcript_source);
create index if not exists item_embeddings_run_idx on item_embeddings(run_id);
create index if not exists item_embeddings_space_idx on item_embeddings(item_type, space);
create index if not exists item_clusters_run_idx on item_clusters(run_id);
create index if not exists item_clusters_cluster_idx on item_clusters(item_type, space, cluster_label);
create index if not exists clusters_run_idx on clusters(run_id);
create index if not exists clusters_lookup_idx on clusters(item_type, space);

-- Search layer (see migrations/015): vision-generated description, persisted media,
-- analysis-column parity for ugc_items, a cosine KNN index + function for query search.
alter table paid_ads add column if not exists ai_description text;
alter table paid_ads add column if not exists storage_video_url text;
alter table paid_ads add column if not exists storage_thumb_url text;
alter table ugc_items add column if not exists ai_description text;
alter table ugc_items add column if not exists storage_video_url text;
alter table ugc_items add column if not exists storage_thumb_url text;
alter table ugc_items add column if not exists persona jsonb;
alter table ugc_items add column if not exists niches jsonb;
alter table ugc_items add column if not exists emotional_drivers jsonb;
alter table ugc_items add column if not exists time_product_was_mentioned numeric;
alter table ugc_items add column if not exists analyzed_at timestamptz;
alter table ugc_items add column if not exists analysis_model text;

create index if not exists item_embeddings_search_hnsw
  on item_embeddings using hnsw (embedding vector_cosine_ops)
  where space = 'search';

create or replace function match_item_embeddings(
  p_query vector(1024),
  p_space text default 'search',
  p_item_type text default null,
  p_model text default 'voyage-4-lite',
  p_run_id uuid default null,
  p_limit int default 20
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
  order by ie.embedding <=> p_query
  limit p_limit;
$$;
