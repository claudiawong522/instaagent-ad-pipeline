-- Remove the "later" trend source. later.com's trend roundups no longer embed example
-- videos (text recaps + sound links only), so the source was dropped from
-- DEFAULT_TREND_SOURCES; this clears its already-ingested data. Deleting the pipeline
-- run cascades to viral_formats, ugc_items, raw_payloads, scrape_events, and enrichments.
delete from pipeline_runs
  where product_id in (select id from products where name = 'Trend: later');
delete from products where name = 'Trend: later';
delete from viral_formats where source_name = 'later';
