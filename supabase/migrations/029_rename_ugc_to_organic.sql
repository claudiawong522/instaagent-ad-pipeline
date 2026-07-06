-- Rename the "ugc" naming to "organic" across the schema, completing the code-side rename.
-- The organic table kept its TopYappers-era "UGC" name while the pipeline modules, CLI, and
-- API all moved to "organic" — every reader had to hold the "ugc == organic" mapping in their
-- head. Storage now follows the code: ugc_items -> organic_items, the polymorphic item_type
-- value 'ugc_item' -> 'organic_item', and the per-run / per-keyword target_ugc_count columns
-- -> target_organic_count. The match_item_embeddings RPC is generic over item_type (a
-- parameter, not a literal), so it needs no change. The 'ugc' CONTENT FORMAT tag value in
-- item_enrichments.content_formats is untouched — there "ugc" genuinely means the
-- user-generated-content production style, not this table.

begin;

-- 1) The organic table itself. Indexes/constraints keep their old names on a table rename,
--    so rename the known ones too (if-exists: older DBs may predate some of them).
alter table ugc_items rename to organic_items;

alter table organic_items rename constraint ugc_items_pkey to organic_items_pkey;
alter table organic_items rename constraint ugc_items_run_id_external_id_key to organic_items_run_id_external_id_key;
alter table organic_items rename constraint ugc_items_run_id_fkey to organic_items_run_id_fkey;
alter table organic_items rename constraint ugc_items_raw_payload_id_fkey to organic_items_raw_payload_id_fkey;
alter table organic_items rename constraint ugc_items_format_id_fkey to organic_items_format_id_fkey;

alter index if exists ugc_items_run_id_idx rename to organic_items_run_id_idx;
alter index if exists ugc_items_external_idx rename to organic_items_external_idx;
alter index if exists ugc_items_video_id_idx rename to organic_items_video_id_idx;
alter index if exists ugc_items_virality_idx rename to organic_items_virality_idx;
alter index if exists ugc_items_saved_to_supabase_at_idx rename to organic_items_saved_to_supabase_at_idx;
alter index if exists ugc_items_enrichment_status_idx rename to organic_items_enrichment_status_idx;
alter index if exists ugc_items_format_idx rename to organic_items_format_idx;

-- 2) The polymorphic item_type value on every table that stores it. Drop each check first
--    so the UPDATE can pass, then re-add it with the new vocabulary.
alter table item_enrichments drop constraint if exists item_enrichments_item_type_check;
update item_enrichments set item_type = 'organic_item' where item_type = 'ugc_item';
alter table item_enrichments add constraint item_enrichments_item_type_check
  check (item_type in ('paid_ad', 'organic_item'));

alter table item_embeddings drop constraint if exists item_embeddings_item_type_check;
update item_embeddings set item_type = 'organic_item' where item_type = 'ugc_item';
alter table item_embeddings add constraint item_embeddings_item_type_check
  check (item_type in ('paid_ad', 'organic_item', 'viral_format'));

alter table item_clusters drop constraint if exists item_clusters_item_type_check;
update item_clusters set item_type = 'organic_item' where item_type = 'ugc_item';
alter table item_clusters add constraint item_clusters_item_type_check
  check (item_type in ('paid_ad', 'organic_item'));

alter table clusters drop constraint if exists clusters_item_type_check;
update clusters set item_type = 'organic_item' where item_type = 'ugc_item';
alter table clusters add constraint clusters_item_type_check
  check (item_type in ('paid_ad', 'organic_item'));

-- 3) The per-run and per-keyword organic target counts.
alter table pipeline_runs rename column target_ugc_count to target_organic_count;
alter table keywords rename column target_ugc_count to target_organic_count;

commit;
