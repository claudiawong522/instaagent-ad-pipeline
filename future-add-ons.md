# Future Add-Ons

- **Query expansion for search recall (removed 2026-07-06).** `search.expand_query` expanded short
  queries ("genz" → "gen z, young, casual, trendy") via a cheap OpenRouter call before embedding.
  Removed because it was config-disabled by default: an A/B over the niche query set showed it
  changed zero results (the enriched icp space + reranker already surface the right candidates and
  the 100/space candidate pool covers the corpus) while adding ~2.6s/search. Worth reintroducing
  once the corpus outgrows `rerank_candidate_pool`, where expansion's recall benefit returns —
  see git history of `api/search.py` for the implementation.
- **`GET /products` and `GET /items/{item_type}/{item_id}` endpoints (removed 2026-07-06).** Both
  had zero frontend call sites (the UI reads products via campaign listings and items via search
  results). Trivial to restore from git history if a product picker or item-detail page lands.

These are good ideas intentionally deferred to keep the first version lean.

## Competitor Mode

- Use Meta Ad Library page URLs or page IDs with Apify `apify/facebook-ads-scraper` to pull ads for known competitor brands.
- Useful for customer-specific competitor research.
- Deferred because the first version should prove the keyword-led category workflow first.

## Transcription Optimizations

- If the broader Apify transcript actor has poor Instagram reliability or cost, compare Apify `apple_yang/instagram-transcripts-scraper` as an Instagram-only alternative. It accepts one public Instagram video URL and returns `text` plus timestamped `segments`.
- If Apify confirms array input is stable for `tictechid/anoxvanzi-transcriber`, batch multiple known URLs into one actor run to reduce per-run base charges.

## Account-Size-Normalized Organic Virality

- Normalize organic performance by creator follower count or historical baseline.
- Useful once source data quality around follower counts is confirmed.

## Human Review UI

- Add approval/rejection, notes, cluster renaming, customer fit tags, and final sales-pack curation.

## Creative Cloning Packs

- Generate scripts, shot lists, asset requirements, creator directions, and prompt-ready clone specs from selected winners.

## Keyword Quality Tuning

- Add keyword approval, rejection, regeneration, and per-provider keyword variants.
- Add competitor/domain lookup when exact brand or competitor terms matter.

## Visual Analysis

- Add OCR, frame sampling, scene detection, visual style embeddings, product-shot detection, and before/after detection.

## Compliance/IP Review

- Flag risky medical/beauty claims, direct competitor copying, creator likeness reuse, trademark risk, and platform policy issues.

## Static Image Ads

- The Meta Ad Library scrape URL currently hard-codes `media_type=video` (`apify_ads.py`), so photo-only ads never enter the pipeline.
- To include them: parameterize `media_type` (CLI `--media-type`, default `all`), and extend `enrich-paid-ads` to send the ad image + caption through the same OpenRouter descriptor schema when there is no video (transcript fields null).
- Embeddings need no changes — `embed-items` works off descriptor columns regardless of media type, and same-schema distillation keeps image and video ads clustering by creative pattern instead of input modality.
- Deferred because every scraped ad so far is a video ad and InstaAgent clones video creatives first.

## Trend pipeline: email sources, Instagram videos, per-video tags

The viral-format trend pipeline (`ingest-trends` → `viral_formats` + `ugc_items`, `/trends` dashboard) ingests **web** trend pages and re-scrapes **TikTok + Instagram** example videos. Deferred:

- **Email newsletter source.** Add an IMAP + Gmail app-password fetcher (e.g. Social Growth Engineers' Trend Radar) that emits the same `{source_name, source_url, content_hash, text, candidate_urls}` "issue" shape into the existing `TREND_PARSE_PROMPT` path. Needs a `source_type` column (`email`|`web`) and a per-source idempotency key (email `message_id`). Parked at user request — web-first.
- **YouTube Shorts example videos.** `_rescrape_instagram` (`trend_ingest.py`) now fetches IG reels via `apify/instagram-scraper` `directUrls` → `normalize_instagram_post`, mapping back by reel shortcode; TikTok short links (`vm./vt.tiktok.com`, `/t/`) are redirect-resolved to `/video/<id>` in `_resolve_tiktok_short`. YouTube Shorts are still only counted (surfaced in `ingest_note` as "not scraped yet") — to support them, add a YT actor + `normalize_youtube_item` + a YouTube branch in `organic_enrichment` for the MP4 download.
- **Video-level constraint tagging.** The free-form `niche_constraint` is per-format. If format-level proves too coarse, add per-video niche tags + a video filter on the dashboard (the user's stated fallback).
- **Scheduling.** `ingest-trends` is manual; a cron/routine could auto-pull weekly. JS-rendered pages (none of the current sources) would need an Apify `website-content-crawler` fallback in `trend_sources.fetch_trend_page`.

## Re-seed keywords on campaign edit

- The inline campaign editor (`PATCH /campaigns/{run_id}`) updates the product + campaign config (name/goals/objective) but does **not** regenerate keyword allocations. Keywords are seeded once at create time from the objective.
- So editing the objective/product after creation won't change which keywords the scrapers search.
- To support it: on edit, diff the objective and re-run `generate_keyword_allocations` + `insert_keyword_allocations`, deduping against existing keywords so a re-run doesn't pile up duplicates (and deciding what to do with keywords from already-scraped runs).
- Deferred because it's a meaningfully bigger change (dedup + cost implications) than the in-place detail edit the UI needed.

