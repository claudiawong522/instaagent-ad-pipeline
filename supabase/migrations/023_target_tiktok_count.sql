-- Split organic scrape targets: target_ugc_count now means reels (Instagram) only,
-- and target_tiktok_count is the separate TikTok target. Backfill existing rows so
-- TikTok keeps the previous shared value (no behavior change for existing campaigns).
alter table pipeline_runs
  add column if not exists target_tiktok_count integer not null default 2500;

alter table keywords
  add column if not exists target_tiktok_count integer not null default 0;

update pipeline_runs set target_tiktok_count = target_ugc_count;
update keywords set target_tiktok_count = target_ugc_count;
