-- Phase 6: multi-value production-format tag. A video can have several overlapping
-- formats (e.g. both `meme` and `ugc`), so this is a jsonb array like age_brackets.
--
-- Derived by the TEXT-ONLY audience pass (audience_enrichment.py / `enrich-audience`)
-- over the already-stored ai_description + transcript_text — no video re-download. The
-- value feeds the search embedding (build_search_text) and the categorical search filter.
--
-- Supersedes the legacy single-value `content_format` column (left in place as harmless
-- legacy; it stops being written once ad_enrichment drops it, and can be dropped later).
alter table item_enrichments add column if not exists content_formats jsonb;
