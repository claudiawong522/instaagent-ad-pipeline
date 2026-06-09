alter table ugc_items
  add column if not exists saved_to_supabase_at timestamptz not null default now();

create index if not exists ugc_items_saved_to_supabase_at_idx
  on ugc_items(saved_to_supabase_at desc);
