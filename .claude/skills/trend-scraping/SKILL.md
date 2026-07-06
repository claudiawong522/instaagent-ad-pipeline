---
name: trend-scraping
description: Reliably scrape JS-rendered trend-roundup pages into viral_formats + correctly-matched example videos, and debug the results that land on the /trends dashboard. Use when working on the viral-format trend pipeline (ingest-trends, trend_sources.py, trend_ingest.py), or when the /trends page shows empty cards, mismatched/irrelevant videos, missing trends, or duplicate cards. Covers waiting for JS embeds to load, telling a real example apart from a recommendation carousel, excluding FAQ name-drops, verifying each trend maps to its own video, surviving flaky renders, and monthly URL/issue_date handling.
---

# Scraping JS trend pages so every trend maps to its right video

The pipeline reads marketing "TikTok trends this month" pages, LLM-parses each into viral
*formats*, and re-scrapes each format's example video for live metrics. Several families of bugs
kept the /trends board wrong; this skill is the hard-won method for avoiding them.

**Golden rule (this repo's CLAUDE.md #7): never speculate — check the real data.** Every claim
below was proven by fetching the live page and querying Supabase, not reasoned from the code.
When something looks wrong, `Config.from_env()` + `SupabaseClient` and a `--dry-run` first.

## The failure families (what "wrong" looked like)

1. **Mismatched / irrelevant videos.** A TikTok embed injects a "you might also like" carousel
   next to the real video. Those links are `tiktok.com/share/video/<other-id>?...&referer_video_id=<the real one>`.
   The harvester can't tell them from the article's chosen example, so one trend ("Wow, Ok")
   collected 22 random high-view videos (a diamond ad, cats, soccer). Proof: 100% of the 22
   stored ids were carousel-recommendation ids from the page.
2. **Empty cards.** Two causes: (a) the LLM mined trend *names* out of the page's **FAQ prose**
   ("strong options include Everything Hallelujah, Show You Off, FB Mom Photos…") and made a
   card per name with no video; (b) the headless render was **partial** — TikTok embeds hadn't
   loaded yet — so a render saw only text and produced name-only formats.
3. **Fewer cards than the page actually has trends (under-count).** July 2026 newengen listed six
   numbered trends (`Trend #1…#6`) but only four cards landed. Two distinct causes: (a)
   **under-segmentation** — the LLM folded two numbered trends into one format, so "I Treated You
   Bad" (#6) got no card and its video was absorbed under "You Look Like the 4th of July" (#5),
   which then hoarded a second, wrong video; (b) **dead featured video** — "You Never Take Me to
   Bangladesh" (#1)'s own TikTok was removed, so its embed rendered "Video currently unavailable",
   no canonical URL was harvested, and the zero-link filter (§4) dropped the whole trend. The tell
   for both: the page *numbers its own trends*, so `max(Trend #N) > formats in DB` proves something
   merged or dropped. See §8.

## The method (each step maps to code that's already in place)

### 1. Wait for the JS embeds to actually load
newengen is `render:"js"` → fetched through Apify's `website-content-crawler` (headless
Firefox). Embeds lazy-load per trend as they scroll into view. Under-scroll or under-wait and
the lower trends silently never render. Settings that matter (`_fetch_rendered_html` in
`trend_sources.py`): `maxScrollHeightPixels` high, `dynamicContentWaitSecs`, and
`waitForSelectorOnLoadTimeoutSecs`. **The render is still non-deterministic** — no setting makes
it always complete. That is why step 6 exists.

### 2. Drop the recommendation carousel at harvest time
`_is_carousel_recommendation(url)`: a `share/video/<X>` link whose `referer_video_id` ≠ `X` is a
recommendation, not the example. Filtered out in `html_to_text`'s `_add`. This is a deterministic
rule from the URL itself — do NOT try to have an LLM or agent "judge" which video belongs; the
answer is printed in the query string.

### 3. Don't let the LLM harvest FAQ/prose name-drops
`TREND_PARSE_PROMPT` tells the model to extract a format only from a section that *describes* it
(heading + explanation), never a name listed in an FAQ answer, a "related trends" sentence, or a
roundup list.

### 4. Only persist formats that actually link a video
In `ingest_trends`, after parsing: `formats = [f for f in formats if f["video_urls"]]`. A
zero-link format is a prose name-drop → skip it (status `no_linked_formats`). A format whose link
merely failed to *scrape* keeps its row + an explanatory `ingest_note` — that's different from
never having a link.

### 5. Skip an incomplete render instead of writing empties
If a `render:"js"` source parses to formats but `videos_found == 0`, treat the render as
incomplete (status `incomplete_render`) and write nothing. Existing data stays; next run retries.

### 6. Survive flaky renders by ACCUMULATING, never destructively pruning
Because each render loads a random subset of trends, a single pass is never guaranteed complete.
The design is **accumulate-and-keep**:
- Re-run ingest; each pass *adds* the trends it saw. `_relink_existing_videos` moves an
  already-scraped video to whatever format the current parse assigns it.
- Prune ONLY empty rows: `_prune_empty_formats` deletes formats with 0 linked videos (a rename
  leftover — the video moved to the new-name row). A trend a partial render *missed* still has
  its video, so it is NOT empty and survives.
- **Never prune by content_hash.** The old hash-based prune deleted every row from a different
  page version, so a partial render wiped good trends. That bug is why "accumulate + empty-only
  prune" is the rule.

To fully populate a source in one sitting, loop the ingest a handful of times
(`--force --skip-enrichment`), then enrich once (`enrich-ugc --run-id <id>`).

### 7. Verify the mapping before trusting it
Cross-check each trend heading against the page's embed structure: in the rendered text, the
first `referer_video_id` / canonical `@user/video/<id>` after a heading is that section's real
example. Confirm each format got a *distinct* id (no collisions). This is how a mislabeled
video gets caught — e.g. an LLM run once put jaydenbanks' video under "Wow, Ok" instead of
"Summer Anthem"; a good render corrects it.

### 8. Trust the page's own trend numbering (count · boundaries · names)
newengen's monthly report labels every trend `Trend #1`, `Trend #2`, … `Trend #N` in the rendered
text. That numbering is ground truth the free-form LLM parse currently ignores — which is how six
July trends became four cards (failure family 3):
- **Count check.** `grep -c "Trend #"` the rendered text = the authoritative trend count. If the DB
  has fewer formats for that `issue_date`, one merged (under-segmentation) or dropped (dead video).
  Loop ingest and re-check; if it never reaches N, inspect *which* number is missing.
- **Boundaries + names.** Each `Trend #N:` heading owns exactly ONE featured example (the handle in
  its own section); everything under that trend's "Related videos" is carousel. A format that ends
  up with videos from two different `Trend #N` sections is under-segmented — split it by heading.
  Use the full heading text ("You Look Like the 4th of July (Makes Me Want a Hot Dog Real Bad)"),
  not an LLM-shortened invention ("You Look Like 4th July").
- **Dead-video trends aren't name-drops.** A numbered trend whose featured TikTok was removed shows
  "Video currently unavailable" and yields no URL, so §4 drops it — but it's a *real* current trend,
  not FAQ prose. Worth a card + `ingest_note` rather than silent disappearance.

Not yet enforced in code — `TREND_PARSE_PROMPT` doesn't pin to the numbering, so this is a manual
check today. The durable fix is to have the parse segment strictly on `Trend #N` headings and emit
exactly one format per number.

### 9. Right page, right month
- Use newengen's **monthly `/insights/<month>-tiktok-trends/`** report (one embed per trend, ~9),
  NOT the weekly `/tiktok-trends/` hub (3 trends + FAQ name-drops). `_newengen_insights_url()`
  derives the current month; `default_trend_sources()` builds it fresh per call. Month names are
  hard-coded (locale-proof), not `strftime`.
- Stamp `viral_formats.issue_date` from the report month (`issue_date_from_url`). The API defaults
  to the latest month per source (`_latest_month_per_source`), so last month drops off the board
  once the new report is ingested — without deleting it (`?all_months=true` returns everything).

## Debugging checklist (in order)
1. `SELECT` the source's formats + linked `ugc_items`; count empties and videos-per-format.
2. `--dry-run` the source: see what the LLM currently extracts and how it assigns video URLs.
3. Re-fetch the page (`fetch_trend_page`) and inspect `candidate_urls` — carousel vs canonical,
   and how many distinct `referer_video_id` groups (that's the real trend count).
4. For mismatches, check the stored `external_id`s against the page's carousel ids (overlap = junk).
5. For empties, grep the page text for the name — if it only appears in an FAQ answer, it was a
   name-drop, not a trend.
6. For under-counts, `grep -c "Trend #"` the rendered text = the real trend count; compare to
   formats-per-`issue_date` in the DB. A gap = a merged (under-segmented) or dropped (dead-video)
   trend — inspect *which* `Trend #N` is absent (method §8). July 2026: 6 numbered trends → 4 cards
   because #6 folded into #5 and #1's featured TikTok was unavailable.

## Key files
- `src/instaagent_pipeline/trend_sources.py` — fetch/render, `html_to_text`, carousel filter,
  parse prompt, month URL + `issue_date_from_url`, `default_trend_sources`.
- `src/instaagent_pipeline/trend_ingest.py` — `ingest_trends` orchestration, `_relink_existing_videos`,
  `_prune_empty_formats`, incomplete-render + zero-link guards.
- `src/instaagent_pipeline/api/routes_trends.py` — `/trends/formats`, `_latest_month_per_source`.
- `frontend/app/trends/page.tsx` — the board + sources popover (kept in sync with the backend URLs).
- Tests: `tests/test_trend_carousel.py`, `tests/test_trend_dedupe.py`, `tests/test_trend_match.py`.
