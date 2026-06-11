create table if not exists paid_ads (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references pipeline_runs(id) on delete cascade,
  raw_payload_id uuid references raw_payloads(id) on delete set null,
  source_provider text not null default 'apify:apify/facebook-ads-scraper',
  external_id text not null,
  url text,
  media_url text,
  thumbnail_url text,
  brand_name text,
  page_name text,
  caption text,
  platform text,
  display_format text,
  started_running_at timestamptz,
  running_duration_days numeric,
  live boolean,
  cta_type text,
  cta_title text,
  full_transcription text,
  timestamped_transcription jsonb,
  cards jsonb,
  source_metrics jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (run_id, source_provider, external_id)
);

create table if not exists ugc_items (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references pipeline_runs(id) on delete cascade,
  raw_payload_id uuid references raw_payloads(id) on delete set null,
  source_provider text not null default 'topyappers',
  external_id text not null,
  url text,
  media_url text,
  thumbnail_url text,
  creator_username text,
  caption text,
  platform text,
  display_format text not null default 'video',
  posted_at timestamptz,
  views bigint,
  likes bigint,
  comments bigint,
  shares bigint,
  followers bigint,
  virality_score numeric,
  hook text,
  country text,
  category text,
  music_title text,
  hashtags jsonb,
  subtitles text,
  source_metrics jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (run_id, source_provider, external_id)
);

create table if not exists paid_ad_transcripts (
  id uuid primary key default gen_random_uuid(),
  paid_ad_id uuid not null references paid_ads(id) on delete cascade,
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

create index if not exists paid_ads_run_id_idx on paid_ads(run_id);
create index if not exists paid_ads_external_idx on paid_ads(source_provider, external_id);
create index if not exists paid_ads_longevity_idx on paid_ads(running_duration_days desc);
create index if not exists ugc_items_run_id_idx on ugc_items(run_id);
create index if not exists ugc_items_external_idx on ugc_items(source_provider, external_id);
create index if not exists ugc_items_virality_idx on ugc_items(virality_score desc);
