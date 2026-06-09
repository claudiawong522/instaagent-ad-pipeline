-- Backfill the TopYappers video URL column for Supabase projects that ran
-- an earlier exact-shape UGC migration before this field was included.

alter table ugc_items
  add column if not exists video_url text;
