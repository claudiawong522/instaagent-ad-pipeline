# InstaAgent Ad Selection Pipeline

This is the full future plan for the InstaAgent ad selection pipeline. The current implementation covers Step 1 and Step 2 foundations, plus a first known-URL UGC transcript fallback for Step 3.

## Goal

Given a product and keyword set, collect paid ads and UGC/organic content, analyze the transcripts, cluster repeated ICPs/formats/hooks, and select top examples that InstaAgent can clone and sell to customers.

## MVP Architecture

- Storage: Supabase Postgres as the system of record.
- Paid ads: Apify official `apify/facebook-ads-scraper` actor over Meta Ad Library URLs.
- UGC: TopYappers first, using free-text fields such as `videoTopicContains`.
- Deferred UGC fallback: Apify Instagram Reels Search & Trend Discovery if TopYappers coverage is too narrow.
- Later vector storage: Supabase `pgvector` for ICP, format, and hook embeddings.

## Full Data Flow

1. Product/run setup
   - Create a product record with name, category, target market, and notes.
   - Create a pipeline run with target counts, top K, and source config.
   - Use Claude Haiku to generate 3-6 discovery keywords when manual keywords are not supplied.
   - Store keywords plus per-keyword paid ad and UGC target allocations. Allocations must add up to the run targets.
   - Log every API request in `source_queries`.

2. Source ingestion
   - Apify paid ads: build a Meta Ad Library keyword URL for each allocated keyword and run `apify/facebook-ads-scraper`.
   - TopYappers: query URL-backed UGC by allocated keyword with `POST /api/v1/viral-content`, using free-text fields first and category filters only as helpers.
   - Use TopYappers `GET /api/v1/videos` only as a metadata-only fallback when subtitles or raw video metrics matter more than video URLs.
   - If a provider returns fewer items than the keyword target, save the returned items and move on.
   - Store raw payloads and source-shaped candidates in separate Supabase tables:
     - Apify Meta Ad Library paid ads -> `paid_ads`.
     - TopYappers UGC -> `ugc_items`, with columns matching the TopYappers response fields plus database bookkeeping.

3. Transcript extraction
   - Paid ads: leave transcript fields empty unless a separate paid-ad transcription stage is added.
   - UGC: copy TopYappers `subtitles` into `ugc_transcripts` when present.
   - Known-URL UGC fallback: use Apify `tictechid/anoxvanzi-transcriber` for public Instagram, TikTok, YouTube Shorts, and Facebook URLs when TopYappers subtitles are missing.
   - Fallback later: transcribe downloaded video/audio if source subtitles are missing and URL-based actors fail.

4. LLM analysis
   - Analyze every transcript into structured ICP, format, hook, and cloneability fields.
   - Store prompt version, model version, raw response, parsed JSON, and confidence.

5. Embeddings
   - Generate three independent embedding spaces per item:
     - `icp_embedding`
     - `format_embedding`
     - `hook_embedding`
   - Do not concatenate these into one blended embedding.

6. Clustering
   - Cluster separately by source and embedding space:
     - paid ICP, paid format, paid hook.
     - UGC ICP, UGC format, UGC hook.
   - Store cluster labels, centroids, member distances, and repeatedness counts.

7. Selection
   - Paid ads: select top K per cluster by longevity, using `running_duration_days DESC`.
   - UGC: select top K per cluster by TopYappers `viralityScore DESC`.
   - Normalize per ICP so broad ICPs do not dominate.
   - Dedupe exact URLs/source ids first, then near-duplicate transcripts/hooks.

8. Export
   - Export CSV/JSON grouped by run, source, embedding space, cluster, and ICP.
   - Include URL, thumbnail, transcript, metrics, labels, score, why selected, and cloneability notes.

## Current Implementation Scope

Step 1, Step 2, and the first UGC transcript backfill path in Step 3 are implemented now.

Included:

- Supabase schema for products, runs, keywords, source query logs, raw payloads, Apify-shaped `paid_ads`, TopYappers-shaped `ugc_items`, transcript placeholders, and API usage.
- CLI to create product/runs and Claude-generated or manual keyword allocations.
- CLI to ingest Apify Meta Ad Library paid ad candidates across stored keyword allocations.
- CLI to ingest TopYappers viral-content UGC candidates across stored keyword allocations.
- CLI to ingest/hydrate TopYappers video records across stored keyword allocations.
- CLI to backfill missing UGC transcripts from public social video URLs through Apify into `ugc_transcripts`.
- Endpoint documentation that matches the ingestion code.

Not included yet:

- Paid-ad transcript extraction as a standalone processing stage.
- Downloaded media/audio transcription for UGC rows not covered by provider subtitles or Apify URL actors.
- LLM analysis.
- Embeddings.
- Clustering.
- Ranking/selection outputs.
- Dedupe.
- Exports.
- Review UI.

## Default Product Example

- Product: `QE cleanser`
- Keywords:
  - `cleanser`
  - `gentle cleanser`
  - `gentle cleansing`
  - `skincare cleanser`

## Future Source Notes

TopYappers is the first UGC source because it can return virality, hook, follower, and subtitle/video fields. Its fixed category/tag system should not be the core search mechanism; use `videoTopicContains`, `contentCategoryContains`, `productCategoryContains`, and `brandMentionedContains` for free-text searches.

Apify Instagram Reels Search & Trend Discovery should be tested later if TopYappers does not return enough relevant UGC for niche keywords. The Apify actor supports arbitrary Instagram Reels keyword discovery but does not appear to be transcript-native, so it would require a separate transcription stage.
