-- Per-video enrichment outcome, so the UI can show "X of Y videos searchable"
-- and split the failures into expired-URL vs other. Previously this only lived in
-- the EnrichmentResult returned to the CLI (logged, then lost); nothing on the row
-- recorded whether a scraped video actually became searchable.
--
-- enrichment_status (null until enrichment touches the row):
--   'enriched' — vision succeeded, item_enrichments written → searchable
--   'expired'  — the provider URL no longer serves video (HTTP error / non-video
--                bytes / network failure at download time); Apify links expire
--   'failed'   — downloaded but the vision/analysis step produced nothing usable,
--                or the URL was unsupported
-- enrichment_error holds the human-readable reason for expired/failed.
alter table paid_ads
  add column if not exists enrichment_status text,
  add column if not exists enrichment_error text;

alter table ugc_items
  add column if not exists enrichment_status text,
  add column if not exists enrichment_error text;

create index if not exists paid_ads_enrichment_status_idx on paid_ads(run_id, enrichment_status);
create index if not exists ugc_items_enrichment_status_idx on ugc_items(run_id, enrichment_status);
