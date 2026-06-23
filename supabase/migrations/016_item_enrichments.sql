-- Polymorphic enrichment store: a single `item_enrichments` table holds the
-- vision/LLM analysis (description, hook, categories, tags, transcript) for both
-- paid_ads and ugc_items, replacing the per-table analysis columns and the two
-- separate transcript tables. item_id points at paid_ads.paid_ad_row_id OR
-- ugc_items.id (one of two tables, so no FK — same shape as item_embeddings).
--
-- This collapses the enrichment surface to one place and lets the search/embed
-- layer read enrichment without caring whether an item is paid or UGC.
--
-- Run this in the Supabase SQL editor after 015. The backfill (step 3) must run
-- BEFORE the column/table drops (steps 4-7) so no enrichment data is lost.

-- 1. New polymorphic enrichment table.
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

create index if not exists item_enrichments_run_idx on item_enrichments(run_id);
create index if not exists item_enrichments_item_idx on item_enrichments(item_type, item_id);

-- 2. Backfill from paid_ads (+ its transcript) so nothing is lost.
insert into item_enrichments (
  run_id, item_type, item_id,
  ai_description, hook, main_category, content_category, content_format,
  content_tone, primary_emotion, target_demographic, video_topic, visual_style,
  production_quality, setting, product_category, has_product, has_text_overlay,
  is_trending_format, persona, niches, emotional_drivers, brand_mentioned,
  time_product_was_mentioned, analysis_model, analyzed_at,
  transcript_text, transcript_segments
)
select
  p.run_id, 'paid_ad', p.paid_ad_row_id,
  p.ai_description, p.hook, p.main_category, p.content_category, p.content_format,
  p.content_tone, p.primary_emotion, p.target_demographic, p.video_topic, p.visual_style,
  p.production_quality, p.setting, p.product_category, p.has_product, p.has_text_overlay,
  p.is_trending_format, p.persona, p.niches, p.emotional_drivers, p.brand_mentioned,
  p.time_product_was_mentioned, p.analysis_model, p.analyzed_at,
  t.transcript_text, t.transcript_segments
from paid_ads p
left join lateral (
  select transcript_text, transcript_segments
  from paid_ad_transcripts
  where paid_ad_row_id = p.paid_ad_row_id
  limit 1
) t on true
where p.analyzed_at is not null
on conflict (item_type, item_id) do nothing;

-- 3. Backfill from ugc_items (+ its transcript).
insert into item_enrichments (
  run_id, item_type, item_id,
  ai_description, hook, main_category, content_category, content_format,
  content_tone, primary_emotion, target_demographic, video_topic, visual_style,
  production_quality, setting, product_category, has_product, has_text_overlay,
  is_trending_format, persona, niches, emotional_drivers, brand_mentioned,
  time_product_was_mentioned, analysis_model, analyzed_at,
  transcript_text, transcript_segments
)
select
  u.run_id, 'ugc_item', u.id,
  u.ai_description, u.hook, u.main_category, u.content_category, u.content_format,
  u.content_tone, u.primary_emotion, u.target_demographic, u.video_topic, u.visual_style,
  u.production_quality, u.setting, u.product_category, u.has_product, u.has_text_overlay,
  u.is_trending_format, u.persona, u.niches, u.emotional_drivers, u.brand_mentioned,
  u.time_product_was_mentioned, u.analysis_model, u.analyzed_at,
  t.transcript_text, t.transcript_segments
from ugc_items u
left join lateral (
  select transcript_text, transcript_segments
  from ugc_transcripts
  where ugc_item_id = u.id
  limit 1
) t on true
where u.analyzed_at is not null
on conflict (item_type, item_id) do nothing;

-- 4. Drop the now-superseded transcript tables (their indexes drop with them).
drop table if exists paid_ad_transcripts;
drop table if exists ugc_transcripts;

-- 5. Drop the migrated enrichment columns + never-populated/dead columns from paid_ads.
--    KEEP storage_video_url, storage_thumb_url.
alter table paid_ads drop column if exists ai_description;
alter table paid_ads drop column if exists hook;
alter table paid_ads drop column if exists main_category;
alter table paid_ads drop column if exists content_category;
alter table paid_ads drop column if exists content_format;
alter table paid_ads drop column if exists content_tone;
alter table paid_ads drop column if exists primary_emotion;
alter table paid_ads drop column if exists target_demographic;
alter table paid_ads drop column if exists video_topic;
alter table paid_ads drop column if exists visual_style;
alter table paid_ads drop column if exists production_quality;
alter table paid_ads drop column if exists setting;
alter table paid_ads drop column if exists product_category;
alter table paid_ads drop column if exists has_product;
alter table paid_ads drop column if exists has_text_overlay;
alter table paid_ads drop column if exists is_trending_format;
alter table paid_ads drop column if exists brand_mentioned;
alter table paid_ads drop column if exists persona;
alter table paid_ads drop column if exists emotional_drivers;
alter table paid_ads drop column if exists niches;
alter table paid_ads drop column if exists time_product_was_mentioned;
alter table paid_ads drop column if exists analysis_model;
alter table paid_ads drop column if exists analyzed_at;
alter table paid_ads drop column if exists race;
alter table paid_ads drop column if exists hair_color;
alter table paid_ads drop column if exists gender;
alter table paid_ads drop column if exists age;
alter table paid_ads drop column if exists has_face;
alter table paid_ads drop column if exists face_count;
alter table paid_ads drop column if exists color_palette;
alter table paid_ads drop column if exists creative_targeting;
alter table paid_ads drop column if exists market_target;
alter table paid_ads drop column if exists is_ai_generated;
alter table paid_ads drop column if exists full_transcription;
alter table paid_ads drop column if exists timestamped_transcription;
alter table paid_ads drop column if exists content_filter;

-- 6. Drop the migrated enrichment columns + TopYappers-only columns from ugc_items.
--    KEEP storage_video_url, storage_thumb_url.
alter table ugc_items drop column if exists ai_description;
alter table ugc_items drop column if exists hook;
alter table ugc_items drop column if exists main_category;
alter table ugc_items drop column if exists content_category;
alter table ugc_items drop column if exists content_format;
alter table ugc_items drop column if exists content_tone;
alter table ugc_items drop column if exists primary_emotion;
alter table ugc_items drop column if exists target_demographic;
alter table ugc_items drop column if exists video_topic;
alter table ugc_items drop column if exists visual_style;
alter table ugc_items drop column if exists production_quality;
alter table ugc_items drop column if exists setting;
alter table ugc_items drop column if exists product_category;
alter table ugc_items drop column if exists has_product;
alter table ugc_items drop column if exists has_text_overlay;
alter table ugc_items drop column if exists is_trending_format;
alter table ugc_items drop column if exists brand_mentioned;
alter table ugc_items drop column if exists persona;
alter table ugc_items drop column if exists emotional_drivers;
alter table ugc_items drop column if exists niches;
alter table ugc_items drop column if exists time_product_was_mentioned;
alter table ugc_items drop column if exists analysis_model;
alter table ugc_items drop column if exists analyzed_at;
alter table ugc_items drop column if exists topyappers_id;
alter table ugc_items drop column if exists iv_id;
alter table ugc_items drop column if exists account_type;
alter table ugc_items drop column if exists age;
alter table ugc_items drop column if exists bio;
alter table ugc_items drop column if exists categories;
alter table ugc_items drop column if exists color_palette;
alter table ugc_items drop column if exists comments_to_views_ratio;
alter table ugc_items drop column if exists country;
alter table ugc_items drop column if exists creator_avg_views;
alter table ugc_items drop column if exists creator_engagement_rate;
alter table ugc_items drop column if exists creator_language;
alter table ugc_items drop column if exists cta_type;
alter table ugc_items drop column if exists date_added;
alter table ugc_items drop column if exists date_created_timestamp;
alter table ugc_items drop column if exists face_count;
alter table ugc_items drop column if exists follower_tier;
alter table ugc_items drop column if exists gender;
alter table ugc_items drop column if exists hair_color;
alter table ugc_items drop column if exists has_face;
alter table ugc_items drop column if exists is_ai_generated;
alter table ugc_items drop column if exists is_branded;
alter table ugc_items drop column if exists is_promotional;
alter table ugc_items drop column if exists likes_to_views_ratio;
alter table ugc_items drop column if exists race;
alter table ugc_items drop column if exists shares_to_views_ratio;
alter table ugc_items drop column if exists subtitles;
alter table ugc_items drop column if exists user_followers;
alter table ugc_items drop column if exists video_ranges;
alter table ugc_items drop column if exists views_to_avg_ratio;

-- 7. Drop indexes that referenced now-dropped columns.
drop index if exists paid_ads_product_category_idx;
drop index if exists paid_ads_content_category_idx;
drop index if exists paid_ads_video_topic_idx;
drop index if exists paid_ads_analyzed_at_idx;
drop index if exists ugc_items_video_topic_idx;
drop index if exists ugc_items_content_category_idx;
