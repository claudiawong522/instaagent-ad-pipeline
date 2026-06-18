-- Search layer: a combined 'search' embedding space (ai_description + tag block),
-- the vision-generated ai_description field that feeds it, persisted video/thumbnail
-- storage URLs for in-app playback, a pgvector KNN function for query-time search,
-- and the analysis columns ugc_items lacks so paid + UGC reach parity.
--
-- Run this in the Supabase SQL editor after 014. Requires the `vector` extension
-- (already enabled by 013).

-- 1. Allow the new 'search' embedding space on item_embeddings.
alter table item_embeddings drop constraint if exists item_embeddings_space_check;
alter table item_embeddings add constraint item_embeddings_space_check
  check (space in ('icp', 'format', 'hook', 'search'));

-- 2. Cosine KNN index for the search space (HNSW needs no training step).
create index if not exists item_embeddings_search_hnsw
  on item_embeddings using hnsw (embedding vector_cosine_ops)
  where space = 'search';

-- 3. Vision-generated description + persisted media URLs on both content tables.
alter table paid_ads add column if not exists ai_description text;
alter table paid_ads add column if not exists storage_video_url text;
alter table paid_ads add column if not exists storage_thumb_url text;

alter table ugc_items add column if not exists ai_description text;
alter table ugc_items add column if not exists storage_video_url text;
alter table ugc_items add column if not exists storage_thumb_url text;

-- 4. Analysis columns ugc_items lacks, for paid/UGC parity. The UGC vision
--    enrichment fills these the same way ad_enrichment fills them on paid_ads.
alter table ugc_items add column if not exists persona jsonb;
alter table ugc_items add column if not exists niches jsonb;
alter table ugc_items add column if not exists emotional_drivers jsonb;
alter table ugc_items add column if not exists time_product_was_mentioned numeric;
alter table ugc_items add column if not exists analyzed_at timestamptz;
alter table ugc_items add column if not exists analysis_model text;

-- 5. Query-time KNN over the search space. `<=>` is cosine distance; similarity is
--    1 - distance so larger = more similar. p_query is passed as a pgvector text
--    literal (e.g. '[0.1,0.2,...]') which Postgres casts to vector(1024).
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

-- 6. Storage bucket for persisted videos + thumbnails (public read for inline playback).
insert into storage.buckets (id, name, public)
values ('ad-videos', 'ad-videos', true)
on conflict (id) do nothing;
