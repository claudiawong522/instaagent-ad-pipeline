-- Product → viral-format matching. Two additions:
-- 1) Structured, machine-matchable fields on viral_formats, written by classify-formats
--    alongside the free-form niche_constraint prose: a coarse versatility bucket, the niches
--    a format suits, and the concrete product attributes it demands. These drive the
--    structured pre-filter and the versatility badge; product_requirements is what lets the
--    matcher honestly say a product "fits none".
-- 2) A trend-level embedding space so a product query can KNN-recall candidate formats before
--    the LLM judge (keeps the judge's payload flat as the trend library grows). The existing
--    match_item_embeddings RPC is generic over item_type/space, so it is reused as-is — this
--    migration only widens the two check constraints and adds the HNSW index.

alter table viral_formats
  add column if not exists versatility text,
  add column if not exists fit_niches text[],
  add column if not exists product_requirements text[];

alter table viral_formats drop constraint if exists viral_formats_versatility_check;
alter table viral_formats add constraint viral_formats_versatility_check
  check (versatility is null or versatility in ('universal', 'broad', 'niche'));

-- Allow a viral_format's own embedding to live in item_embeddings (item_id = viral_formats.id),
-- in a dedicated 'trend' space kept apart from the paid_ad/ugc_item content spaces.
alter table item_embeddings drop constraint if exists item_embeddings_item_type_check;
alter table item_embeddings add constraint item_embeddings_item_type_check
  check (item_type in ('paid_ad', 'ugc_item', 'viral_format'));

alter table item_embeddings drop constraint if exists item_embeddings_space_check;
alter table item_embeddings add constraint item_embeddings_space_check
  check (space in ('icp', 'format', 'hook', 'search', 'trend'));

create index if not exists item_embeddings_trend_hnsw
  on item_embeddings using hnsw (embedding vector_cosine_ops)
  where space = 'trend';
