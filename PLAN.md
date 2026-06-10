# InstaAgent Ad Selection Pipeline

This is the full future plan for the InstaAgent ad selection pipeline. The current implementation only covers Step 1 and Step 2: product/run setup and source ingestion foundations.

## Goal

Given a product and keyword set, collect paid ads and UGC/organic content, analyze the transcripts, cluster repeated ICPs/formats/hooks, and select top examples that InstaAgent can clone and sell to customers.

## MVP Architecture

- Storage: Supabase Postgres as the system of record.
- Paid ads: Foreplay Public API.
- UGC: TopYappers first, using free-text fields such as `videoTopicContains`.
- Deferred UGC fallback: Apify Instagram Reels Search & Trend Discovery if TopYappers coverage is too narrow.
- Later vector storage: Supabase `pgvector` for ICP, format, and hook embeddings.

## Full Data Flow

1. Product/run setup
   - Create a product record with name, category, target market, and notes.
   - Create a pipeline run with target counts, top K, and source config.
   - Store seed keywords and expanded keyword variants.
   - Log every API request in `source_queries`.

2. Source ingestion
   - Foreplay: query paid ads by keyword and collect up to 1000 candidates, prioritizing `order=longest_running`.
   - TopYappers: query URL-backed UGC with `POST /api/v1/viral-content`, using free-text fields first and category filters only as helpers.
   - Use TopYappers `GET /api/v1/videos` only as a metadata-only fallback when subtitles or raw video metrics matter more than video URLs.
   - Store raw payloads and source-shaped candidates in separate Supabase tables:
     - Foreplay paid ads -> `paid_ads`.
     - TopYappers UGC -> `ugc_items`, with columns matching the TopYappers response fields plus database bookkeeping.

3. Transcript extraction
   - Paid ads: use Foreplay transcript fields when present.
   - UGC: use TopYappers `subtitles` when present.
   - Fallback later: transcribe downloaded video/audio if source subtitles are missing.

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

Only Step 1 and Step 2 are implemented now.

Included:

- Supabase schema for products, runs, keywords, source query logs, raw payloads, Foreplay-shaped `paid_ads`, TopYappers-shaped `ugc_items`, transcript placeholders, and API usage.
- CLI to create product/runs and keywords.
- CLI to ingest Foreplay paid ad candidates.
- CLI to ingest TopYappers viral-content UGC candidates.
- CLI to ingest/hydrate TopYappers video records.
- Endpoint documentation that matches the ingestion code.

Not included yet:

- Transcript extraction as a standalone processing stage.
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
