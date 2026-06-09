-- Add JSONB overflow fields for provider-specific values that do not need
-- first-class columns.

alter table if exists paid_ads
  add column if not exists source_metrics jsonb not null default '{}'::jsonb;

alter table if exists ugc_items
  add column if not exists source_metrics jsonb not null default '{}'::jsonb;
