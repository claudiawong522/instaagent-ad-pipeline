-- Why a format ended up with no playable example video (e.g. "Instagram reel could not be
-- scraped", "1 TikTok short link couldn't be resolved", "Source listed no example video
-- links"). Written by ingest-trends; NULL when the format has a video. Surfaced on the
-- dashboard card so an empty format explains itself instead of looking broken.
alter table viral_formats
  add column if not exists ingest_note text;
