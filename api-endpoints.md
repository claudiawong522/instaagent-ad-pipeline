# API Endpoints

This document lists the endpoints used by the ingestion and transcript-backfill implementation, their input fields, output fields, and Supabase mappings.

The current design keeps paid ads and UGC separate:

- Apify Meta Ad Library paid ads write to `paid_ads`.
- TopYappers UGC writes to `ugc_items`.
- Apify UGC transcript fallback writes to `ugc_transcripts`.
- Raw source JSON from external providers still writes to `raw_payloads`.

## Provider Keyword Strategy

Store exact product and campaign language in `products.notes`, `pipeline_runs.config`, and `keywords`. Provider API inputs should usually be broader category, benefit, or format terms so discovery does not collapse to zero or only owned-brand results.

For a seed such as `QV cleanser`, use examples like:

| Provider | API field | Recommended input | Why |
| --- | --- | --- | --- |
| Apify Meta Ad Library | `search_terms` inside generated Meta Ad Library URL | `gentle cleanser` or `face cleanser` | Finds competitive paid video ads in the cleanser category without over-constraining to exact QV mentions. |
| TopYappers viral-content | `videoTopicContains` | `cleanser`, then top up with `skincare` if needed | The URL-backed viral endpoint is topic-oriented; broad terms return more UGC candidates with usable video URLs. |

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
| transcript fields | `paid_ads.full_transcription`, `paid_ads.timestamped_transcription` | Left null by ingestion; the OpenRouter enrichment stage writes transcripts to `paid_ad_transcripts` instead. |
| unmapped provider fields | `paid_ads.source_metrics` | JSONB overflow for provider-specific fields that are not promoted to columns. |
| full item JSON | `raw_payloads.payload_json` | Raw source of truth. |

## TopYappers: Viral Content

- Provider: TopYappers
- Method: `POST`
- Endpoint: `https://api.topyappers.com/api/v1/viral-content`
- Code path: `ingest-topyappers-viral`
- Purpose: primary URL-backed UGC ingestion endpoint. Discover viral UGC candidates with free-text topic/category filters, virality metrics, and provider video URLs.

### Input Columns / Body Fields

| Field | Type | Required | Used by Code | Notes |
| --- | --- | --- | --- | --- |
| `videoTopicContains` | string | yes | yes | Primary free-text keyword field. |
| `contentCategoryContains` | string | no | yes | Optional free-text content category match. |
| `productCategoryContains` | string | no | yes | Optional free-text product category match. |
| `brandMentionedContains` | string | no | yes | Optional brand mention search. |
| `categories` | string[] | no | yes | Use only as helper filters. |
| `countries` | string[] | no | yes | Country names. |
| `viewsMin`, `viewsMax` | integer | no | yes | View count filter. |
| `viralityScoreMin`, `viralityScoreMax` | float | no | yes | Virality score filter. |
| `followersMin`, `followersMax` | integer | no | yes | Creator size filters if available. |
| `dateCreatedFrom`, `dateCreatedTo` | string | no | yes | `YYYY-MM-DD`. |
| `musicTitle` | string | no | yes | Sound/music filter. |
| `page` | integer | yes | yes | Starts at 1. |
| `pageSize` | integer | yes | yes | Max 100 per docs. |

### Output Columns / Response Fields

`ugc_items` stores stable TopYappers viral-content fields as first-class columns, plus DB bookkeeping. The raw TopYappers `id` field is stored as `ugc_items.topyappers_id` because `ugc_items.id` is the database primary key.

TopYappers viral-content fields stored directly:

```text
topyappers_id, account_type, age, avatar, bio, brand_mentioned,
categories, color_palette, comments, comments_to_views_ratio,
content_category, content_format, content_tone, country, cover,
creator_avg_views, creator_engagement_rate, creator_language, cta_type,
date_added, date_created, description, face_count, follower_tier,
followers, gender, hair_color, handle, has_face, has_product,
has_text_overlay, hashtags, hook, is_ai_generated, is_branded,
is_promotional, is_trending_format, likes, likes_to_views_ratio,
main_category, music, nickname, primary_emotion, product_category,
production_quality, race, setting, shares, shares_to_views_ratio,
source, subtitles, target_demographic, user_id, video_id, video_url,
video_ranges, video_topic, views, views_to_avg_ratio, virality_score,
virality_tier, visual_style
```

DB-only fields:

```text
id, run_id, raw_payload_id, external_id, saved_to_supabase_at
```

Provider-specific fields that are not promoted to first-class columns are stored in `ugc_items.source_metrics` as JSONB. Full source JSON is also preserved in `raw_payloads.payload_json`.

TopYappers documents `videoUrl` and `thumbnailUrl` on this viral-content endpoint. Use this endpoint when URL-backed UGC records are required. The normalizer maps provider URL fields to `ugc_items.video_url`; when live payloads omit URL fields, it derives public URLs from `source`, `handle`/`user_handle`, and `video_id` for TikTok, Instagram, and YouTube. It also maps `thumbnailUrl` or `cover` to `ugc_items.cover`, `caption` to `ugc_items.description`, `handle` or `creatorUsername` to `ugc_items.handle` and `ugc_items.user_handle`, `createdAt` to `ugc_items.date_created`, `category` to `ugc_items.content_category` and `ugc_items.main_category`, and `musicTitle` to `ugc_items.music`.

## TopYappers: Videos

- Provider: TopYappers
- Method: `GET`
- Endpoint: `https://api.topyappers.com/api/v1/videos`
- Code path: `ingest-topyappers-videos`
- Purpose: metadata-only UGC fallback. Search video records by keyword and retrieve subtitles, views, follower count, hashtags, and raw video metrics. This endpoint does not return video URLs.

### Input Columns / Query Fields

| Field | Type | Required | Used by Code | Notes |
| --- | --- | --- | --- | --- |
| `textSearch` | string | yes | yes | Product/category keyword such as `gentle cleanser`, from `--keyword`. |
| `page` | integer | yes | yes | Starts at 1. |
| `perPage` | integer | yes | yes | Page size, from `--page-size`; docs allow up to 100. |
| `sortBy` | string | yes | yes | Defaults to `views`; can be overridden with `--extra-param sortBy=date_created`. |
| `sortOrder` | string | yes | yes | Defaults to `desc`; can be overridden with `--extra-param sortOrder=asc`. |
| `userFollowersMin`, `userFollowersMax` | integer | no | yes | Optional creator size filters. |
| `viewsMin`, `viewsMax` | integer | no | yes | Optional view count filters. |
| `likesMin`, `likesMax` | integer | no | yes | Optional like count filters. |
| `commentsMin`, `commentsMax` | integer | no | yes | Optional comment count filters. |
| `sharesMin`, `sharesMax` | integer | no | yes | Optional share count filters. |
| `hashtags` | string | no | yes | Optional comma-separated hashtag filter. |
| extra JSON params | object | no | yes | Passed through via `--extra-param key=value`. |

### Output Columns / Response Fields

`ugc_items` also stores the TopYappers Videos fields directly. Per the TopYappers docs, `/api/v1/videos` does not return a URL field; `video_url` remains null for this endpoint unless the provider adds one later.

```text
iv_id, comments, date_created_timestamp, description, hashtags, likes,
shares, source, subtitles, user_followers, user_handle, user_id,
video_id, views
```

DB-only fields:

```text
id, run_id, raw_payload_id, external_id, saved_to_supabase_at
```

Provider-specific fields that are not promoted to first-class columns are stored in `ugc_items.source_metrics` as JSONB. Full source JSON is also preserved in `raw_payloads.payload_json`.

## Apify: Known-URL UGC Transcript Backfill

- Provider: Apify
- Actor: `tictechid/anoxvanzi-transcriber`
- Method: `POST`
- Endpoint: `https://api.apify.com/v2/acts/tictechid~anoxvanzi-transcriber/run-sync-get-dataset-items`
- Code path: `backfill-ugc-transcripts`
- Purpose: backfill transcripts for URL-backed `ugc_items` rows when TopYappers `subtitles` is missing.

After live TopYappers ingestion, the CLI first copies non-empty `ugc_items.subtitles` values into `ugc_transcripts` with `transcript_source = 'topyappers:subtitles'`. It then selects `ugc_items` for the same run where `video_url` is present, `subtitles` is null or empty, and no transcript row exists, and sends supported public social video URLs to Apify. The standalone `backfill-ugc-transcripts` command runs the same two-stage transcript flow. Supported URL hosts are Instagram, TikTok, YouTube, and Facebook.

### Input Columns / Body Fields

| Field | Type | Required | Used by Code | Notes |
| --- | --- | --- | --- | --- |
| `start_urls` | string | yes | yes | Public video URL from `ugc_items.video_url`. The actor readme mentions a single URL or array; the CLI sends one URL per actor run for predictable row-level logging. |
| `token` | query string | yes | yes | Apify token from `APIFY_API_KEY`. |

### Output Columns / Response Fields

| Response Field | Supabase Destination | Notes |
| --- | --- | --- |
| `transcript` | `ugc_transcripts.transcript_text` | Parsed into clean text when timestamp markers are present; raw timestamped text is preserved in `raw_payloads`. |
| timestamp ranges in `transcript` | `ugc_transcripts.transcript_segments` | Parsed into objects with `start`, `end`, and `text` when the actor returns bracketed timestamp ranges. |
| actor name | `ugc_transcripts.transcript_source` | Stored as `apify:tictechid/anoxvanzi-transcriber`. |
| full dataset item JSON | `raw_payloads.payload_json` | Raw source of truth, including `status`, `durationSec`, `detected_language`, `error`, and processing timestamp. |

TopYappers provider subtitles map as follows:

| Response Field | Supabase Destination | Notes |
| --- | --- | --- |
| `ugc_items.subtitles` | `ugc_transcripts.transcript_text` | Copied when non-empty. |
| provider name | `ugc_transcripts.transcript_source` | Stored as `topyappers:subtitles`. |

One transcript row is upserted per `(ugc_item_id, transcript_source)`.

## OpenRouter: Paid Ad Video Enrichment

- Provider: `openrouter:<model>` (default model `google/gemini-3-flash-preview`, override with `OPENROUTER_MODEL`)
- Method: `POST`
- Endpoint: `https://openrouter.ai/api/v1/chat/completions`
- Auth: `Authorization: Bearer` header from `OPENROUTER_API_KEY`
- Code path: `enrich-paid-ads`, auto-triggered after live `ingest-apify-ads` (`--skip-enrichment` to disable, `--enrichment-limit` / `--enrichment-timeout` to tune)
- Purpose: one call per paid ad that both transcribes the ad video and extracts ugc_items-parity creative metadata.

Candidates are `paid_ads` rows for the run with a non-null `video` URL and `analyzed_at` null. OpenRouter does not forward arbitrary video URLs to Gemini, so the code fetches the signed CDN mp4 into memory (100 MB cap, never written to disk) and sends it as a base64 `data:` URL in a `video_url` content part. Because CDN URLs are signed and expire within days, run enrichment soon after ingestion; per-row failures are logged in `source_queries` and do not stop the batch.

### Input Columns / Body Fields

| Field | Type | Required | Used by Code | Notes |
| --- | --- | --- | --- | --- |
| `model` | string | yes | yes | `OPENROUTER_MODEL`, default `google/gemini-3-flash-preview`. |
| `messages[0].content[0].video_url.url` | string | yes | yes | `data:video/mp4;base64,<bytes>` fetched from `paid_ads.video`. |
| `messages[0].content[1].text` | string | yes | yes | Extraction prompt plus ad copy context (headline, description, CTA, page name, link URL, display format). |
| `response_format.json_schema` | object | yes | yes | Strict structured-output schema guaranteeing parseable JSON. |

### Output Columns / Response Fields

| Response Field | Supabase Destination | Notes |
| --- | --- | --- |
| `transcript_text` | `paid_ad_transcripts.transcript_text` | Verbatim spoken transcript; null when the ad has no speech (no transcript row is written). |
| `transcript_segments` | `paid_ad_transcripts.transcript_segments` | `{start, end, text}` objects in seconds. |
| model identity | `paid_ad_transcripts.transcript_source` | Stored as `openrouter:<model>`. |
| analysis fields | `paid_ads` analysis columns | `hook`, `persona`, `target_demographic`, `content_format`, `content_tone`, `primary_emotion`, `visual_style`, `production_quality`, `setting`, `color_palette`, `has_face`, `face_count`, `gender`, `age`, `race`, `hair_color`, `has_product`, `has_text_overlay`, `is_ai_generated`, `is_trending_format`, `brand_mentioned`, `emotional_drivers`, `market_target`, `product_category`, `creative_targeting`, `niches`, `main_category`, `content_category`, `video_topic`, `time_product_was_mentioned`. |
| bookkeeping | `paid_ads.analysis_model`, `paid_ads.analyzed_at` | Which model ran and when. |
| `usage` | `api_usage.rate_limit.usage` | Token counts per call. |
| full response JSON | `raw_payloads.payload_json` | Raw source of truth. |

One transcript row is upserted per `(paid_ad_row_id, transcript_source)`.

## Supabase Tables Written by Current Commands

| Table | Written By | Purpose |
| --- | --- | --- |
| `products` | `init-run` | Product brief. |
| `pipeline_runs` | `init-run` | One execution/config for a product. |
| `keywords` | `init-run` | Claude-generated or manual keyword terms plus per-keyword paid ad and UGC target allocations. |
| `source_queries` | all external API commands | Request/response/error logging per API page or transcript actor run. |
| `raw_payloads` | external API commands | Preserved raw source item JSON. |
| `paid_ads` | `ingest-apify-ads`, `enrich-paid-ads` | Apify Meta Ad Library paid ad rows; enrichment fills the analysis columns. |
| `ugc_items` | `ingest-topyappers-viral`, `ingest-topyappers-videos` | TopYappers-shaped UGC candidate rows. Use `ingest-topyappers-viral` when `video_url` is required. |
| `api_usage` | live LLM, ingestion, and transcript commands | Claude keyword-generation usage plus provider HTTP status, response count, selected rate-limit/usage headers, and credits used when exposed. |
| `paid_ad_transcripts` | `enrich-paid-ads` (auto after `ingest-apify-ads`) | Paid ad transcript rows from the OpenRouter enrichment call. |
| `ugc_transcripts` | `backfill-ugc-transcripts` | UGC transcript rows from Apify fallback results. |

## UGC Save Timestamp

`ugc_items.saved_to_supabase_at` records when a UGC video row was inserted into Supabase. It defaults to `now()` at database insert time.
