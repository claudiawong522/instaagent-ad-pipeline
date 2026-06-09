-- Make ugc_items match the union of fields returned by the TopYappers endpoints
-- used by this pipeline. Extra columns are limited to DB bookkeeping/dedupe
-- plus source_metrics for provider-specific overflow fields.

alter table ugc_items
  drop constraint if exists ugc_items_run_id_source_provider_external_id_key,
  drop constraint if exists ugc_items_run_id_external_id_key;

drop index if exists ugc_items_external_idx;
drop index if exists ugc_items_video_id_idx;
drop index if exists ugc_items_video_topic_idx;
drop index if exists ugc_items_content_category_idx;
drop index if exists ugc_items_saved_to_supabase_at_idx;

alter table ugc_items
  add column if not exists external_id text,
  add column if not exists saved_to_supabase_at timestamptz not null default now(),
  add column if not exists topyappers_id text,
  add column if not exists iv_id text,
  add column if not exists account_type text,
  add column if not exists age integer,
  add column if not exists avatar text,
  add column if not exists bio text,
  add column if not exists brand_mentioned jsonb,
  add column if not exists categories jsonb,
  add column if not exists color_palette jsonb,
  add column if not exists comments bigint,
  add column if not exists comments_to_views_ratio numeric,
  add column if not exists content_category text,
  add column if not exists content_format text,
  add column if not exists content_tone text,
  add column if not exists country text,
  add column if not exists cover text,
  add column if not exists creator_avg_views numeric,
  add column if not exists creator_engagement_rate numeric,
  add column if not exists creator_language text,
  add column if not exists cta_type text,
  add column if not exists date_added timestamptz,
  add column if not exists date_created timestamptz,
  add column if not exists date_created_timestamp numeric,
  add column if not exists description text,
  add column if not exists face_count integer,
  add column if not exists follower_tier text,
  add column if not exists followers bigint,
  add column if not exists gender text,
  add column if not exists hair_color text,
  add column if not exists handle text,
  add column if not exists has_face boolean,
  add column if not exists has_product boolean,
  add column if not exists has_text_overlay boolean,
  add column if not exists hashtags jsonb,
  add column if not exists hook text,
  add column if not exists is_ai_generated boolean,
  add column if not exists is_branded boolean,
  add column if not exists is_promotional boolean,
  add column if not exists is_trending_format boolean,
  add column if not exists likes bigint,
  add column if not exists likes_to_views_ratio numeric,
  add column if not exists main_category text,
  add column if not exists music jsonb,
  add column if not exists nickname text,
  add column if not exists primary_emotion text,
  add column if not exists product_category text,
  add column if not exists production_quality text,
  add column if not exists race text,
  add column if not exists setting text,
  add column if not exists shares bigint,
  add column if not exists shares_to_views_ratio numeric,
  add column if not exists source text,
  add column if not exists subtitles text,
  add column if not exists target_demographic text,
  add column if not exists user_followers bigint,
  add column if not exists user_handle text,
  add column if not exists user_id text,
  add column if not exists video_id text,
  add column if not exists video_url text,
  add column if not exists video_ranges jsonb,
  add column if not exists video_topic text,
  add column if not exists views bigint,
  add column if not exists views_to_avg_ratio numeric,
  add column if not exists virality_score numeric,
  add column if not exists virality_tier text,
  add column if not exists visual_style text,
  add column if not exists source_metrics jsonb not null default '{}'::jsonb;

alter table ugc_items
  drop column if exists source_provider,
  drop column if exists url,
  drop column if exists media_url,
  drop column if exists thumbnail_url,
  drop column if exists creator_username,
  drop column if exists caption,
  drop column if exists platform,
  drop column if exists display_format,
  drop column if exists posted_at,
  drop column if exists category,
  drop column if exists music_title,
  drop column if exists endpoint_kind,
  drop column if exists created_at;

alter table ugc_items
  alter column external_id set not null;

create unique index if not exists ugc_items_run_external_unique
  on ugc_items(run_id, external_id);
create index if not exists ugc_items_external_idx on ugc_items(external_id);
create index if not exists ugc_items_video_id_idx on ugc_items(video_id);
create index if not exists ugc_items_video_topic_idx on ugc_items(video_topic);
create index if not exists ugc_items_content_category_idx on ugc_items(content_category);
create index if not exists ugc_items_virality_idx on ugc_items(virality_score desc);
create index if not exists ugc_items_saved_to_supabase_at_idx
  on ugc_items(saved_to_supabase_at desc);
