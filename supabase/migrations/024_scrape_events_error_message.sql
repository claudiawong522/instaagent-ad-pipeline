-- Surface "out of credits" to the UI. When a scrape's Apify or OpenRouter spend runs out of
-- funds/quota mid-run, the failure is otherwise indistinguishable from a generic error (and an
-- enrichment credit failure is swallowed per-item, leaving the event 'done'). We detect the
-- billing rejection from the run's failed source_queries and store a human message here so the
-- campaigns/discover UI can prompt a top-up and a re-run instead of a blind retry. Null = no
-- billing problem; presence = out-of-credits (independent of status).
alter table scrape_events
  add column if not exists error_message text;
