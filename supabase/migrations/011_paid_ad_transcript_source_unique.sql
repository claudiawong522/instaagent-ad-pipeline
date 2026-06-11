-- Enables upsert-by-source for paid ad transcript rows, mirroring
-- 010_ugc_transcript_source_unique.sql for ugc_transcripts.
create unique index if not exists paid_ad_transcripts_row_source_idx
  on paid_ad_transcripts (paid_ad_row_id, transcript_source);
