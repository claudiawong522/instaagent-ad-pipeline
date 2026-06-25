# CLAUDE.md

Guidance for Claude Code working in this repo. `AGENTS.md` holds the full project shape (directory layout, secrets, implementation notes) — read it; this file does not repeat it.

## Behavioral rules

1. **Think before coding.** State assumptions explicitly. If uncertain, ask. If multiple interpretations exist, present them — don't silently pick one. Name confusion instead of bluffing past it.
2. **Simplicity first.** Minimum code that solves the problem. Nothing speculative — no extra features, abstractions, or error handling for impossible cases. This repo's CLI is deliberately lean; keep it that way unless asked for a larger architecture change.
3. **Surgical changes.** Touch only what the task needs. Don't refactor working code or reformat unrelated lines. Only remove imports/vars *your* change orphaned; leave pre-existing dead code unless asked. Match existing style. Every changed line should trace to the request.
4. **Goal-driven execution.** Turn vague asks into testable success criteria plus a brief checkpointed plan, then verify against them before declaring done.
5. **Explain concisely.** When there's technical jargon, explain it. don't use that many words. be to the point. 
6. **Hand off paste-ready artifacts via the clipboard.** When the output is something I have to paste somewhere else — a migration for the Supabase SQL editor, a snippet, a command — pipe it to `pbcopy` and tell me it's copied, instead of just printing it for me to select. I prefer it on the clipboard.


## Project-specific gotchas

- **Paid ads come from Apify Meta Ad Library, not Foreplay.** Foreplay can't show *how long* an ad has been live, and longevity is the key winning-ad signal. Don't reintroduce Foreplay for paid ads.
- **Enrichment runs through OpenRouter (default `google/gemini-3-flash-preview`).** Gemini's free tier is heavily rate-capped — a full pipeline run needs a paid/billing-enabled quota or it will throttle partway through. Budget for this before kicking off a large run.
- **Supabase service role key is server-side only.** It bypasses row-level security — never put it in `frontend/` or any browser/client code. Use it for the ingestion CLI; see `AGENTS.md` and `README.md` "Supabase Key Choice".
- **Schema before writes.** The REST API can write rows but cannot create the schema. Run `supabase/schema.sql` (clean DB) or the pending `supabase/migrations/` in numeric order before search/clustering work. Verify a live DB against the committed migration set first.
- **Preserve raw payloads before normalized upserts.** Paid-ad upserts key on `(run_id, id)`; organic on `(run_id, external_id)`. Provider-specific fields without a first-class column go in `source_metrics`.
- **"New feature doesn't show up" → check delivery before debugging logic.** When a just-built change isn't visible in the running app, the code is usually fine — something stale is serving it. Check, in this order: (1) **Pending migration.** A new endpoint that touches a new table 500s until the migration is applied. There's no psql/DDL access — `cat supabase/migrations/0XX_*.sql | pbcopy` and paste it into the Supabase SQL editor. Confirm by curling the endpoint: `curl localhost:8000/campaigns/<run_id>/scrape-events` — a 500 here while `scrape-stats` returns 200 means the table is missing, not a code bug. (2) **Stale backend.** `uvicorn instaagent_pipeline.api.app:app --port 8000` started **without `--reload`** serves pre-change code; restart with `--reload`. Verify a new route is live with `curl -s localhost:8000/openapi.json | grep <route>`. (3) **Stale frontend.** `next dev --turbo` (port 3000) hot-reloads, but a corrupted `.next` cache serves an old build or 404s compiled CSS (page renders unstyled); `rm -rf frontend/.next` and restart. Always verify the live endpoint returns the new fields *before* digging into component logic.

## Keep docs current

When you make architectural changes, update `database.md`. When you defer a good idea, note it in `future-add-ons.md`.
