create unique index if not exists ugc_transcripts_item_source_idx
  on ugc_transcripts (ugc_item_id, transcript_source);
