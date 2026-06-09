drop table if exists paid_ad_transcripts;
drop table if exists paid_ads;

create table paid_ads (
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
  source_metrics jsonb not null default '{}'::jsonb,
  saved_to_supabase_at timestamptz not null default now(),
  unique (run_id, id)
);

create table paid_ad_transcripts (
  id uuid primary key default gen_random_uuid(),
  paid_ad_row_id uuid not null references paid_ads(paid_ad_row_id) on delete cascade,
  transcript_text text,
  transcript_segments jsonb,
  transcript_source text,
  created_at timestamptz not null default now()
);

create index if not exists paid_ads_run_id_idx on paid_ads(run_id);
create index if not exists paid_ads_id_idx on paid_ads(id);
create index if not exists paid_ads_ad_id_idx on paid_ads(ad_id);
create index if not exists paid_ads_brand_id_idx on paid_ads(brand_id);
create index if not exists paid_ads_product_category_idx on paid_ads(product_category);
create index if not exists paid_ads_saved_to_supabase_at_idx on paid_ads(saved_to_supabase_at desc);
