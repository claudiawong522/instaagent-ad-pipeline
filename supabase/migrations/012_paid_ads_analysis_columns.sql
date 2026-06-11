-- Adds ugc_items-parity analysis columns to paid_ads, populated by the
-- Gemini paid-ad enrichment stage (enrich-paid-ads / auto after ingest-apify-ads).
alter table paid_ads
  add column if not exists hook text,
  add column if not exists main_category text,
  add column if not exists content_category text,
  add column if not exists content_format text,
  add column if not exists content_tone text,
  add column if not exists primary_emotion text,
  add column if not exists target_demographic text,
  add column if not exists video_topic text,
  add column if not exists visual_style text,
  add column if not exists production_quality text,
  add column if not exists setting text,
  add column if not exists color_palette jsonb,
  add column if not exists has_face boolean,
  add column if not exists face_count integer,
  add column if not exists gender text,
  add column if not exists age integer,
  add column if not exists race text,
  add column if not exists hair_color text,
  add column if not exists has_product boolean,
  add column if not exists has_text_overlay boolean,
  add column if not exists is_ai_generated boolean,
  add column if not exists is_trending_format boolean,
  add column if not exists brand_mentioned jsonb,
  add column if not exists analysis_model text,
  add column if not exists analyzed_at timestamptz;

create index if not exists paid_ads_analyzed_at_idx on paid_ads(analyzed_at);
create index if not exists paid_ads_content_category_idx on paid_ads(content_category);
create index if not exists paid_ads_video_topic_idx on paid_ads(video_topic);
