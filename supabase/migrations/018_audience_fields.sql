-- Phase 4 of the search-quality work: abstract audience/tone fields used by the icp
-- embedding space (target_generation) and by the categorical search filters
-- (price_positioning, age_brackets, languages).
--
-- These are derived by a TEXT-ONLY LLM pass over the already-stored ai_description +
-- transcript_text (see audience_enrichment.py / `enrich-audience` CLI) — no video
-- re-download. age_brackets and languages are arrays (a video can target/depict several
-- age groups and contain several languages); price_positioning and target_generation are
-- single enum-valued strings.
alter table item_enrichments add column if not exists target_generation text;
alter table item_enrichments add column if not exists price_positioning text;
alter table item_enrichments add column if not exists age_brackets jsonb;
alter table item_enrichments add column if not exists languages jsonb;
