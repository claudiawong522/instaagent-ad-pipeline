# API Endpoints

This document lists the endpoints used by the ingestion and enrichment implementation, their input fields, output fields, and Supabase mappings.

The current design keeps paid ads and UGC separate at ingestion, but unifies their transcript + analysis enrichment:

- Apify Meta Ad Library paid ads write to `paid_ads`.
- Apify TikTok UGC (`ingest-tiktok`) and Apify Instagram reel UGC (`ingest-instagram`) write to `ugc_items`.
- Instagram follower backfill (`backfill-ig-followers`) fills follower counts on `ugc_items` (source='instagram').
- OpenRouter (Gemini) vision enrichment for both paid ads and UGC writes transcripts + analysis fields to `item_enrichments` and uploads videos to the Supabase Storage bucket `ad-videos`.
- Voyage embeddings write to `item_embeddings`.
- ICP clustering writes to `item_clusters` and `clusters`.
- Raw source JSON from ingestion and enrichment providers writes to `raw_payloads` where noted below.

## Provider Keyword Strategy

Store exact product and campaign language in `products.notes`, `pipeline_runs.config`, and `keywords`. Provider API inputs should usually be broader category, benefit, or format terms so discovery does not collapse to zero or only owned-brand results.

For a seed such as `QV cleanser`, use examples like:

| Provider | API field | Recommended input | Why |
| --- | --- | --- | --- |
| Apify Meta Ad Library | `search_terms` inside generated Meta Ad Library URL | `gentle cleanser` or `face cleanser` | Finds competitive paid video ads in the cleanser category without over-constraining to exact QV mentions. |
| Apify TikTok scraper | `searchQueries` | `cleanser`, then top up with `skincare` if needed | Keyword search is topic-oriented; broad terms return more UGC candidates with usable video URLs and native follower counts. |
| Apify Instagram reel search | `search` | `cleanser`, then top up with `skincare` if needed | Keyword reel search is topic-oriented; broad terms return more reels. Follower counts are often missing and are filled by `backfill-ig-followers`. |

## Claude: Generate Keyword Allocations

- Provider column: configured Claude model, for example `claude-haiku-4-5`
- Method: `POST`
- Endpoint: `https://api.anthropic.com/v1/messages`
- Code path: `init-run` when no manual `--keyword` values are supplied
- Purpose: generate 3-6 discovery keywords from product context and allocate paid ad / UGC targets across them.

Output is stored in `keywords.keyword_text`, `keywords.target_paid_count`, and `keywords.target_ugc_count`. The per-keyword paid ad targets must add up to `pipeline_runs.target_paid_count`; the per-keyword UGC targets must add up to `pipeline_runs.target_ugc_count`. The Claude call is logged in `source_queries` and `api_usage`.

## Apify: Search Meta Ad Library Paid Ads

- Provider: `apify:apify/facebook-ads-scraper`
- Method: `POST`
- Endpoint: `https://api.apify.com/v2/acts/apify~facebook-ads-scraper/run-sync-get-dataset-items`
- Code path: `ingest-apify-ads`
- Purpose: search Meta Ad Library by keyword and retrieve paid ad candidates with creatives, copy, platform, start/end dates, and raw transparency metadata.

### Input Columns / Query Fields

| Field | Type | Required | Used by Code | Notes |
| --- | --- | --- | --- | --- |
| `startUrls` | array | yes | yes | Contains one generated Meta Ad Library URL per keyword. |
| `resultsLimit` | integer | yes | yes | Set from the keyword's paid-ad target count. |
| `activeStatus` | string | yes | yes | Defaults to `active`. |
| `onlyTotal` | boolean | yes | yes | Defaults to `false`; the pipeline needs ad rows, not counts only. |
| `includeAboutPage` | boolean | yes | yes | Defaults to `false`. |
| `isDetailsPerAd` | boolean | yes | yes | Defaults to `false`. |
| `--extra-param` overrides | JSON values | no | yes | Optional actor input overrides for debugging or provider-specific tuning. |

The generated Meta Ad Library URL uses:

```text
active_status=active
ad_type=all
country=ALL
is_targeted_country=false
media_type=video
publisher_platforms[0]=instagram
publisher_platforms[1]=facebook
search_type=keyword_unordered
search_terms=<keyword>
```

### Output Columns / Response Fields

| Response Field | Supabase Destination | Notes |
| --- | --- | --- |
| `adArchiveID` / `adArchiveId` | `paid_ads.id`, `paid_ads.ad_id` | Meta ad archive identifier. Database primary key is `paid_ads.paid_ad_row_id`. |
| `isActive` | `paid_ads.live` | Active status when supplied. Otherwise inferred from end date. |
| `snapshot.pageName` / `pageName` | `paid_ads.name` | Advertiser/page display name. |
| `snapshot.displayFormat` | `paid_ads.type`, `paid_ads.display_format` | Creative format when supplied. |
| `snapshot.cards` | `paid_ads.cards` | Raw card/carousel items. |
| card/snapshot image URL | `paid_ads.image` | First available creative image URL. |
| card/snapshot video URL | `paid_ads.video` | First available creative video URL. |
| `snapshot.pageProfilePictureUrl` | `paid_ads.avatar` | Page avatar. |
| `pageID` / `pageId` | `paid_ads.brand_id` | Meta page identifier. |
| `snapshot.ctaType` / card `ctaType` | `paid_ads.cta_type` | CTA type. |
| `snapshot.title` / card `title` | `paid_ads.headline` | Ad headline/title. |
| `snapshot.linkUrl` / card `linkUrl` | `paid_ads.link_url` | Destination URL. |
| `snapshot.ctaText` / card `ctaText` | `paid_ads.cta_title` | Human CTA text. |
| card/snapshot preview URL | `paid_ads.thumbnail` | First available preview/thumbnail URL. |
| `categories` / `snapshot.pageCategories` | `paid_ads.categories` | Provider categories. |
| `snapshot.body.text` / card `body` | `paid_ads.description` | Ad copy text. |
| `startDateFormatted` / `startDate` | `paid_ads.started_running` | Stored as epoch milliseconds. |
| `endDateFormatted` / `endDate` | `paid_ads.running_duration` | Duration in days, computed locally from start/end or start/current time for active ads. |
| `publisherPlatform` | `paid_ads.publisher_platform` | Meta publisher platforms. |
| transcript + analysis | `item_enrichments` | Not produced by ingestion; the OpenRouter enrichment stage (`enrich-paid-ads`) writes the transcript and analysis fields to `item_enrichments` (`item_type = 'paid_ad'`, `item_id = paid_ads.paid_ad_row_id`). |
| storage video / thumbnail | `paid_ads.storage_video_url`, `paid_ads.storage_thumb_url` | Filled by enrichment after the video is uploaded to the `ad-videos` Supabase Storage bucket. |
| unmapped provider fields | `paid_ads.source_metrics` | JSONB overflow for provider-specific fields that are not promoted to columns. |
| full item JSON | `raw_payloads.payload_json` | Raw source of truth. |

## Apify: Search TikTok UGC

- Provider: `apify:clockworks/tiktok-scraper`
- Method: `POST`
- Endpoint: `https://api.apify.com/v2/acts/clockworks~tiktok-scraper/run-sync-get-dataset-items`
- Code path: `ingest-tiktok`
- Purpose: keyword-search TikTok for UGC candidates with engagement metrics, creator metadata, and provider video URLs. Follower counts are returned natively.

### Input Columns / Body Fields

| Field | Type | Required | Used by Code | Notes |
| --- | --- | --- | --- | --- |
| `searchQueries` | string[] | yes | yes | One or more keyword terms, from `--keyword`. |
| `resultsPerPage` | integer | yes | yes | Set from the keyword's UGC target count. |
| `token` | query string | yes | yes | Apify token from `APIFY_API_KEY`. |
| `--extra-param` overrides | JSON values | no | yes | Optional actor input overrides for debugging or provider-specific tuning. |

### Output Columns / Response Fields

`ugc_items` (source='tiktok') stores the normalized engagement and creator metadata as first-class columns, plus DB bookkeeping. The raw provider video identifier is stored as `ugc_items.video_id`; `ugc_items.id` is the database primary key.

The TikTok normalizer provides engagement + creator metadata only (handle, follower count, views, likes, comments, shares, video URL, cover, description, date created, source='tiktok'). It does not supply a virality score, so `virality_score` and `virality_tier` are RECOMPUTED from engagement. Analysis fields (`hook`, `content_category`, etc.) are left null at ingestion and filled later by OpenRouter vision enrichment, which writes them to `item_enrichments`.

DB-only fields:

```text
id, run_id, raw_payload_id, external_id, saved_to_supabase_at
```

Provider-specific fields that are not promoted to first-class columns are stored in `ugc_items.source_metrics` as JSONB. Full source JSON is also preserved in `raw_payloads.payload_json`.

OpenRouter (Gemini) vision enrichment auto-runs after live `ingest-tiktok`; see the enrichment section below.

## Apify: Search Instagram Reel UGC

- Provider: `apify:data-slayer/instagram-search-reels`
- Method: `POST`
- Endpoint: `https://api.apify.com/v2/acts/data-slayer~instagram-search-reels/run-sync-get-dataset-items`
- Code path: `ingest-instagram`
- Purpose: keyword-search Instagram Reels for UGC candidates with engagement metrics, creator metadata, and provider video URLs.

### Input Columns / Body Fields

| Field | Type | Required | Used by Code | Notes |
| --- | --- | --- | --- | --- |
| `search` | string | yes | yes | Keyword reel-search term, from `--keyword`. |
| `limit` | integer | yes | yes | Set from the keyword's UGC target count. |
| `token` | query string | yes | yes | Apify token from `APIFY_API_KEY`. |
| `--extra-param` overrides | JSON values | no | yes | Optional actor input overrides for debugging or provider-specific tuning. |

### Output Columns / Response Fields

`ugc_items` (source='instagram') stores the normalized engagement and creator metadata as first-class columns, plus DB bookkeeping. `ugc_items.id` is the database primary key.

The Instagram normalizer provides engagement + creator metadata only. Follower counts are often missing from reel-search results and are filled later by `backfill-ig-followers`. It does not supply a virality score, so `virality_score` and `virality_tier` are RECOMPUTED from engagement. Analysis fields are left null at ingestion and filled later by OpenRouter vision enrichment, which writes them to `item_enrichments`.

DB-only fields:

```text
id, run_id, raw_payload_id, external_id, saved_to_supabase_at
```

Provider-specific fields that are not promoted to first-class columns are stored in `ugc_items.source_metrics` as JSONB. Full source JSON is also preserved in `raw_payloads.payload_json`.

OpenRouter (Gemini) vision enrichment auto-runs after live `ingest-instagram`; see the enrichment section below.

## Apify: Instagram Follower Backfill

- Provider: `apify:apify/instagram-profile-scraper`
- Method: `POST`
- Endpoint: `https://api.apify.com/v2/acts/apify~instagram-profile-scraper/run-sync-get-dataset-items`
- Code path: `backfill-ig-followers`
- Purpose: fill the follower counts that Instagram reel-search discovery omits. Scrapes Instagram profiles by handle and writes follower counts back to `ugc_items` (source='instagram').

The command selects `ugc_items` rows for the run where `source = 'instagram'` and the follower count is null or zero, dedupes the candidates per creator handle (one profile scrape per unique creator), and writes the resolved follower count to every matching row.

### Input Columns / Body Fields

| Field | Type | Required | Used by Code | Notes |
| --- | --- | --- | --- | --- |
| `usernames` | string[] | yes | yes | Deduped creator handles drawn from `ugc_items.handle` / `ugc_items.user_handle`. |
| `token` | query string | yes | yes | Apify token from `APIFY_API_KEY`. |

### Output Columns / Response Fields

| Response Field | Supabase Destination | Notes |
| --- | --- | --- |
| `followersCount` | `ugc_items.followers` | Resolved follower count, applied to every `ugc_items` row for that creator handle. |
| full dataset item JSON | `raw_payloads.payload_json` | Raw source of truth. |

## OpenRouter: Video Enrichment (Paid Ads + UGC)

- Provider: `openrouter:<model>` (default model `google/gemini-3-flash-preview`, override with `OPENROUTER_MODEL`)
- Method: `POST`
- Endpoint: `https://openrouter.ai/api/v1/chat/completions`
- Auth: `Authorization: Bearer` header from `OPENROUTER_API_KEY`
- Code paths: `enrich-paid-ads` (paid ads) and `enrich-ugc` (UGC). The paid path auto-triggers after live `ingest-apify-ads`; the UGC path auto-triggers after live `ingest-tiktok` / `ingest-instagram` (`--skip-enrichment` to disable, `--enrichment-limit` / `--enrichment-timeout` to tune)
- Purpose: one Gemini vision call per video that both transcribes the video and extracts the trimmed creative-metadata set. The same single-call flow runs for paid ads and UGC.

Candidates are items for the run with a non-null video URL (`paid_ads.video` for paid, `ugc_items.video_url` for UGC) and no `item_enrichments` row yet. Each enrichment downloads the video into memory (100 MB cap, never written to disk), uploads it to the Supabase Storage bucket `ad-videos` (recording `storage_video_url` / `storage_thumb_url` on the item table — `paid_ads` or `ugc_items`), and sends the base64 video to OpenRouter as a `data:` URL in a `video_url` content part. Because source CDN URLs are signed and expire within days, run enrichment soon after ingestion; per-row failures are logged in `source_queries` and do not stop the batch.

### Input Columns / Body Fields

| Field | Type | Required | Used by Code | Notes |
| --- | --- | --- | --- | --- |
| `model` | string | yes | yes | `OPENROUTER_MODEL`, default `google/gemini-3-flash-preview`. |
| `messages[0].content[0].video_url.url` | string | yes | yes | `data:video/mp4;base64,<bytes>` fetched from `paid_ads.video` (paid) or `ugc_items.video_url` (UGC). |
| `messages[0].content[1].text` | string | yes | yes | Extraction prompt plus available item context (for paid ads: headline, description, CTA, page name, link URL, display format; for UGC: caption/description, handle, hashtags). |
| `response_format.json_schema` | object | yes | yes | Strict structured-output schema guaranteeing parseable JSON. |

### Output Columns / Response Fields

All enrichment output is written to the polymorphic `item_enrichments` table, keyed by `(item_type, item_id)`: `item_type = 'paid_ad'` with `item_id = paid_ads.paid_ad_row_id`, or `item_type = 'ugc_item'` with `item_id = ugc_items.id`.

| Response Field | Supabase Destination | Notes |
| --- | --- | --- |
| `transcript_text` | `item_enrichments.transcript_text` | Verbatim spoken transcript; null when the video has no speech. |
| `transcript_segments` | `item_enrichments.transcript_segments` | `{start, end, text}` objects in seconds. |
| `ai_description` | `item_enrichments.ai_description` | Model-generated description of the video. |
| analysis fields | `item_enrichments` analysis columns | `hook`, `main_category`, `content_category`, `content_format`, `content_tone`, `primary_emotion`, `target_demographic`, `video_topic`, `visual_style`, `production_quality`, `setting`, `product_category`, `has_product`, `has_text_overlay`, `is_trending_format`, `persona`, `niches`, `emotional_drivers`, `brand_mentioned`, `time_product_was_mentioned`. |
| bookkeeping | `item_enrichments.analysis_model`, `item_enrichments.analyzed_at` | Which model ran and when. |
| `usage` | `api_usage.rate_limit.usage` | Token counts per call. |
| full response JSON | `raw_payloads.payload_json` | Raw source of truth. |

One row is upserted per `(item_type, item_id)`. The video upload also sets `storage_video_url` / `storage_thumb_url` on the source item table (`paid_ads` or `ugc_items`).

## Voyage AI: Item Embeddings

- Provider: `voyage:<model>` (default model `voyage-4-lite`, override with `EMBEDDING_MODEL` or `--model`)
- Method: `POST`
- Endpoint: `https://api.voyageai.com/v1/embeddings`
- Auth: `Authorization: Bearer` header from `VOYAGE_API_KEY`
- Code path: `embed-items` (standalone; requires migration `013_item_embeddings.sql`)
- Purpose: turn the enriched icp/search text of each item into vectors for the clustering and dedupe stages.

Candidates are items with an `item_enrichments` row for the run (`--source paid|ugc|all`). For each item, up to two texts are built — `icp` from `persona` + `target_demographic`, and `search` from `ai_description` + a labeled tag block + the full transcript appended — and spaces with no usable text are skipped. Texts are sent in batches of up to 128 with `input_type: "document"`.

### Input Body Fields

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `input` | string[] | yes | The batch of source texts, order-aligned with the response. |
| `model` | string | yes | Voyage model name. |
| `input_type` | string | yes | Always `document`; queries against the corpus would use `query`. |

### Output Fields

| Response Field | Supabase Destination | Notes |
| --- | --- | --- |
| `data[].embedding` | `item_embeddings.embedding` | 1024-dim vector, serialized as the pgvector text literal. Re-ordered by `data[].index`. |
| model identity | `item_embeddings.embedding_model` | Stored as the bare model name. |
| source text | `item_embeddings.source_text` | Exactly what was embedded, for debugging and dedupe. |
| `usage` | `api_usage.rate_limit.usage` | `total_tokens` per call. |

One row is upserted per `(item_type, item_id, space, embedding_model)`, so re-runs are idempotent. Raw responses are not stored in `raw_payloads` (vectors are large and fully captured in `item_embeddings`).

## OpenRouter: ICP Cluster Labels

- Provider: `openrouter:<model>` (default model `google/gemini-3-flash-preview`, override with `OPENROUTER_MODEL` or `--model`)
- Method: `POST`
- Endpoint: `https://openrouter.ai/api/v1/chat/completions`
- Auth: `Authorization: Bearer` header from `OPENROUTER_API_KEY`
- Code path: `cluster-items` (standalone; requires migration `014_item_clusters.sql`)
- Purpose: cluster ICP embeddings per source and optionally label each discovered cluster from representative source texts.

`cluster-items` first loads `item_embeddings` rows for the run with `space = 'icp'`, separately for `paid_ad` and `ugc_item`. It runs HDBSCAN locally through scikit-learn, upserts every item assignment into `item_clusters`, and upserts each discovered non-noise cluster into `clusters`. If `--no-label` is not passed, it sends up to five closest exemplar ICP texts to OpenRouter and stores the parsed label on `clusters`.

### Input Body Fields

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `model` | string | yes | `OPENROUTER_MODEL` or `--model`, default `google/gemini-3-flash-preview`. |
| `messages[0].content` | string | yes | Prompt containing representative ICP source texts for one cluster. |
| `response_format.json_schema` | object | yes | Strict JSON schema for persona, pains, scroll topics, and quote. |

### Output Fields

| Response Field | Supabase Destination | Notes |
| --- | --- | --- |
| local HDBSCAN labels | `item_clusters.cluster_label` | `-1` means noise. |
| local centroid distance | `item_clusters.distance_to_centroid` | Null for noise rows. |
| local centroid | `clusters.centroid` | `vector(1024)` centroid for the discovered cluster. |
| exemplar IDs | `clusters.exemplar_item_ids` | Closest item IDs used for labeling. |
| `persona` | `clusters.name`, `clusters.label_json.persona`, `clusters.label_text` | Persona is also rendered into the readable label text. |
| `pains`, `scrolls_for`, `quote` | `clusters.label_json`, `clusters.label_text` | Structured and readable label output. |
| model identity | `clusters.label_model` | Stored only when labeling succeeds. |
| `usage` | `api_usage.rate_limit.usage` | Token counts per label call. |

Cluster label API calls are logged in `source_queries` and `api_usage`. Raw label responses are not stored in `raw_payloads`; the parsed cluster label is stored directly in `clusters.label_json` and `clusters.label_text`.

## Supabase Tables Written by Current Commands

| Table | Written By | Purpose |
| --- | --- | --- |
| `products` | `init-run` | Product brief. |
| `pipeline_runs` | `init-run` | One execution/config for a product. |
| `keywords` | `init-run` | Claude-generated or manual keyword terms plus per-keyword paid ad and UGC target allocations. |
| `source_queries` | all external API commands | Request/response/error logging per API page or transcript actor run. |
| `raw_payloads` | external API commands | Preserved raw source item JSON. |
| `paid_ads` | `ingest-apify-ads`, `enrich-paid-ads` | Apify Meta Ad Library paid ad rows; enrichment fills `storage_video_url` / `storage_thumb_url`. |
| `ugc_items` | `ingest-tiktok`, `ingest-instagram`, `backfill-ig-followers`, `enrich-ugc` | Apify TikTok and Instagram reel UGC candidate rows; follower backfill fills Instagram follower counts; enrichment fills `storage_video_url` / `storage_thumb_url`. |
| `api_usage` | live LLM, ingestion, and enrichment commands | Claude keyword-generation usage plus provider HTTP status, response count, selected rate-limit/usage headers, and credits used when exposed. |
| `item_enrichments` | `enrich-paid-ads` (auto after `ingest-apify-ads`), `enrich-ugc` (auto after `ingest-tiktok` / `ingest-instagram`) | Polymorphic transcript + analysis rows from the OpenRouter vision call, one per `(item_type, item_id)` for paid ads and UGC. |
| `item_embeddings` | `embed-items` | One pgvector row per item per embedding space (icp/search) per model. |
| `item_clusters` | `cluster-items` | One cluster assignment per embedded item for the ICP space. |
| `clusters` | `cluster-items` | Cluster summaries, centroids, exemplars, and optional OpenRouter labels. |

## UGC Save Timestamp

`ugc_items.saved_to_supabase_at` records when a UGC video row was inserted into Supabase. It defaults to `now()` at database insert time.
