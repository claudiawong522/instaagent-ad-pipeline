# Trends Scraping — how it works

**A robot reads "top TikTok trends this week" blog posts for you and checks which videos are actually blowing up.**

Instead of guessing what's viral, it lets marketing blogs do the trend-spotting, structures their output with AI, then fact-checks the view counts.

## The 5 steps

1. **Read the blogs.** It grabs a handful of marketing blogs that list trending TikToks. Some pages hide their videos behind JavaScript, so for those it uses a real browser (Apify) to load them fully.

2. **Take notes — structurally when possible, AI otherwise.** The output is always tidy notes per format: *this format, this description, these example videos.* Pages with reliable structure are split without any AI (`trend_sources.py`): numbered pages (`Trend #1…#N`, newengen) split on the numbering; heading-delimited pages (ramdam, socialbee) split on whichever heading level the video embeds sit under — auto-detected per page, since ramdam's 2025 redesign moved it from h3 to h4. Deterministic parses can't merge adjacent trends or truncate titles, the failure modes the LLM had. The AI reads the page only when neither structure is recognized — and always for SGE, whose headings are app/brand names that must be rewritten into technique names (`SGE_PARSE_PROMPT`).

3. **Fact-check the views.** For each example TikTok, it re-scrapes the real video to get the current view count and the actual clip. The blog says "this is hot" — this step proves it.

4. **Tag the niche.** A second quick AI call notes who each format fits — "works for anyone" vs. "food brands only."

5. **Save + show.** Everything lands in the database and shows up on the `/trends` page, sorted by most views.

## The 3 sources & how often they update

| Source | URL | Cadence |
|--------|-----|---------|
| **ramdam** | ramd.am/blog/trends-tiktok | **Weekly** — evergreen URL, updated in place |
| **socialbee** | socialbee.com/blog/tiktok-trends | **Weekly** — evergreen URL, updated in place |
| **newengen** | newengen.com/insights/`<month>`-tiktok-trends | **Monthly** — a *new* URL each month (deep-dive report) |

These cadences are what the code assumes, not something the pipeline verifies. The pipeline hashes each page and **skips re-parsing anything unchanged since the last run**, so running `ingest-trends` more often than a source actually updates just no-ops on the unchanged ones.

⚠️ **newengen needs manual upkeep:** it publishes a *fresh URL* every month (`june-tiktok-trends` → `july-tiktok-trends` → …), so the hardcoded URL in `TREND_SOURCES` goes stale and must be pointed at the new month's report each time.

## The one idea to remember

The blogs tell you *what's trending*; the re-scrape proves it's *actually live and big*. The AI is just the note-taker in between.

## Where things live (for the curious)

- CLI commands: `ingest-trends` (steps 1–3, 5) and `classify-formats` (step 4) in `src/instaagent_pipeline/cli.py`
- Blog source list: `TREND_SOURCES` in `src/instaagent_pipeline/trend_sources.py` (override with the `TREND_SOURCES` env var)
- Output tables: `viral_formats` (one row per format) and `ugc_items` (the example videos, linked by `format_id`) — see `supabase/migrations/025_viral_formats.sql`
- Served at: `GET /trends/formats` → the frontend `/trends` page
