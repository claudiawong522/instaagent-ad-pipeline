alter table keywords
  add column if not exists target_paid_count integer not null default 0,
  add column if not exists target_ugc_count integer not null default 0;
