-- Rename the "ugc" naming to "organic" across the schema, completing the code-side rename.
-- The organic table kept its TopYappers-era "UGC" name while the pipeline modules, CLI, and
-- API all moved to "organic" — every reader had to hold the "ugc == organic" mapping in their
-- head. Storage now follows the code: ugc_items -> organic_items, the polymorphic item_type
-- value 'ugc_item' -> 'organic_item', and the per-run / per-keyword target_ugc_count columns
-- -> target_organic_count. The match_item_embeddings RPC is generic over item_type (a
-- parameter, not a literal), so it needs no change. The 'ugc' CONTENT FORMAT tag value in
-- item_enrichments.content_formats is untouched — there "ugc" genuinely means the
-- user-generated-content production style, not this table.
--
-- Constraint/index names are DISCOVERED from the catalog, not hard-coded: a live DB built
-- through the incremental migrations carries different auto-generated names than a fresh
-- schema.sql install. Every step is idempotent, so the script is safe to re-run.

begin;

-- 1) The organic table itself (skipped if a previous run already renamed it).
do $$ begin
  if to_regclass('public.ugc_items') is not null then
    alter table ugc_items rename to organic_items;
  end if;
end $$;

-- 1a) Constraints keep their old names on a table rename; rename whatever ugc_items-prefixed
--     constraints this database actually has (pkey, unique keys, FKs — names vary by history).
do $$
declare r record;
begin
  for r in
    select conname from pg_constraint
    where conrelid = 'public.organic_items'::regclass and conname like 'ugc_items%'
  loop
    execute format(
      'alter table organic_items rename constraint %I to %I',
      r.conname, replace(r.conname, 'ugc_items', 'organic_items')
    );
  end loop;
end $$;

-- 1b) Same for plain indexes (constraint-backed indexes were already renamed with their
--     constraints above, so they no longer match here).
do $$
declare r record;
begin
  for r in
    select indexname from pg_indexes
    where schemaname = 'public' and tablename = 'organic_items' and indexname like 'ugc_items%'
  loop
    execute format(
      'alter index %I rename to %I',
      r.indexname, replace(r.indexname, 'ugc_items', 'organic_items')
    );
  end loop;
end $$;

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

-- 3) The per-run and per-keyword organic target counts (skipped if already renamed).
do $$ begin
  if exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'pipeline_runs' and column_name = 'target_ugc_count'
  ) then
    alter table pipeline_runs rename column target_ugc_count to target_organic_count;
  end if;
  if exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'keywords' and column_name = 'target_ugc_count'
  ) then
    alter table keywords rename column target_ugc_count to target_organic_count;
  end if;
end $$;

commit;
