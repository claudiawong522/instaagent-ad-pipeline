-- Remove obsolete shared-table schema tables from existing Supabase projects.
-- The current schema stores normalized rows in paid_ads and ugc_items, with
-- separate transcript tables for each.

drop table if exists transcripts;
drop table if exists creative_items;
