# API Endpoints

This document lists the endpoints used by the Step 1/2 implementation, their input fields, output fields, and Supabase mappings.

The current design keeps paid ads and UGC separate:

- Foreplay paid ads write to `paid_ads`.
- TopYappers UGC writes to `ugc_items`.
- Raw source JSON from both providers still writes to `raw_payloads`.

## Foreplay: Search Paid Ads

- Provider: Foreplay
- Method: `GET`
- Endpoint: `https://public.api.foreplay.co/api/discovery/ads`
- Code path: `ingest-foreplay`
- Purpose: search paid ads by keyword and retrieve candidate ads with longevity and transcript metadata.

### Input Columns / Query Fields

| Field | Type | Required | Used by Code | Notes |
| --- | --- | --- | --- | --- |
| `query` | string | yes | yes | Product/category keyword such as `gentle cleanser`. |
| `limit` | integer | yes | yes | Page size. |
| `offset` | integer | yes | yes | Offset pagination. |
| `order` | string | yes | yes | Defaults to `longest_running`. |
| `live` | boolean | no | yes | Optional active-status filter via `--extra-param live=true`. |
| `display_format` | string | no | yes | Optional format filter via `--extra-param display_format=video`. |
| `publisher_platform` | string | no | yes | Optional platform filter. |
| `languages` | string/string[] | no | yes | Optional language filter. |
| `market_target` | string | no | yes | Optional B2B/B2C filter. |
| `running_duration_min_days` | integer | no | yes | Optional longevity minimum. |
| `running_duration_max_days` | integer | no | yes | Optional longevity maximum. |

### Output Columns / Response Fields

| Response Field | Supabase Destination | Notes |
| --- | --- | --- |
| `id` | `paid_ads.id` | Foreplay item id. Database primary key is `paid_ads.paid_ad_row_id`. |
| `live` | `paid_ads.live` | Exact Foreplay field. |
| `name` | `paid_ads.name` | Exact Foreplay field. |
| `type` | `paid_ads.type` | Exact Foreplay field. |
| `ad_id` | `paid_ads.ad_id` | Exact Foreplay field. |
| `cards` | `paid_ads.cards` | Exact Foreplay field. |
| `image` | `paid_ads.image` | Exact Foreplay field. |
| `video` | `paid_ads.video` | Exact Foreplay field. |
| `avatar` | `paid_ads.avatar` | Exact Foreplay field. |
| `niches` | `paid_ads.niches` | Exact Foreplay field. |
| `persona` | `paid_ads.persona` | Exact Foreplay field. |
| `brand_id` | `paid_ads.brand_id` | Exact Foreplay field. |
| `cta_type` | `paid_ads.cta_type` | Exact Foreplay field. |
| `headline` | `paid_ads.headline` | Exact Foreplay field. |
| `link_url` | `paid_ads.link_url` | Exact Foreplay field. |
| `cta_title` | `paid_ads.cta_title` | Exact Foreplay field. |
| `languages` | `paid_ads.languages` | Exact Foreplay field. |
| `thumbnail` | `paid_ads.thumbnail` | Exact Foreplay field. |
| `categories` | `paid_ads.categories` | Exact Foreplay field. |
| `description` | `paid_ads.description` | Exact Foreplay field. |
| `market_target` | `paid_ads.market_target` | Exact Foreplay field. |
| `content_filter` | `paid_ads.content_filter` | Exact Foreplay field. |
| `display_format` | `paid_ads.display_format` | Exact Foreplay field. |
| `video_duration` | `paid_ads.video_duration` | Exact Foreplay field. |
| `started_running` | `paid_ads.started_running` | Exact Foreplay field. |
| `product_category` | `paid_ads.product_category` | Exact Foreplay field. |
| `running_duration` | `paid_ads.running_duration` | Exact Foreplay field. |
| `emotional_drivers` | `paid_ads.emotional_drivers` | Exact Foreplay field. |
| `creative_targeting` | `paid_ads.creative_targeting` | Exact Foreplay field. |
| `full_transcription` | `paid_ads.full_transcription` | Exact Foreplay field. |
| `publisher_platform` | `paid_ads.publisher_platform` | Exact Foreplay field. |
| `timestamped_transcription` | `paid_ads.timestamped_transcription` | Exact Foreplay field. |
| `time_product_was_mentioned` | `paid_ads.time_product_was_mentioned` | Exact Foreplay field. |
| unmapped provider fields | `paid_ads.source_metrics` | JSONB overflow for provider-specific fields that are not promoted to columns. |
| full item JSON | `raw_payloads.payload_json` | Raw source of truth. |

## Foreplay: Hydrate One Ad

- Provider: Foreplay
- Method: `GET`
- Endpoint: `https://public.api.foreplay.co/api/ad/{ad_id}`
- Code path: not called automatically yet; documented for Step 2 hydration extension.
- Purpose: fetch full ad metadata if discovery results are incomplete.

### Input Columns / Path Fields

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `ad_id` | string | yes | Foreplay ad id. |

### Output Columns / Response Fields

Same mapping as Foreplay search paid ads.

## Foreplay: Usage

- Provider: Foreplay
- Method: `GET`
- Endpoint: `https://public.api.foreplay.co/api/usage`
- Code path: documented for monitoring; not part of default ingestion loop.
- Purpose: track Foreplay credit usage.

### Input Columns / Query Fields

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| auth header | bearer token | yes | `Authorization: Bearer <FOREPLAY_API_KEY>`. |

### Output Columns / Response Fields

| Response Field | Supabase Destination | Notes |
| --- | --- | --- |
| full usage JSON | `api_usage.rate_limit` or `raw_payloads.payload_json` | Exact fields depend on account response. |

## TopYappers: Viral Content

- Provider: TopYappers
- Method: `POST`
- Endpoint: `https://api.topyappers.com/api/v1/viral-content`
- Code path: `ingest-topyappers-viral`
- Purpose: discover viral UGC candidates with free-text topic/category filters and virality metrics.

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

`ugc_items` mirrors the TopYappers response fields one-to-one, plus DB bookkeeping. The raw TopYappers `id` field is stored as `ugc_items.topyappers_id` because `ugc_items.id` is the database primary key.

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

## TopYappers: Videos

- Provider: TopYappers
- Method: `GET`
- Endpoint: `https://api.topyappers.com/api/v1/videos`
- Code path: `ingest-topyappers-videos`
- Purpose: primary UGC ingestion endpoint. Search video records by keyword and retrieve subtitles, views, follower count, hashtags, and raw video metrics.

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

`ugc_items` also stores the TopYappers Videos fields directly:

```text
iv_id, comments, date_created_timestamp, description, hashtags, likes,
shares, source, subtitles, user_followers, user_handle, user_id,
video_id, video_url, views
```

DB-only fields:

```text
id, run_id, raw_payload_id, external_id, saved_to_supabase_at
```

Provider-specific fields that are not promoted to first-class columns are stored in `ugc_items.source_metrics` as JSONB. Full source JSON is also preserved in `raw_payloads.payload_json`.

## Supabase Tables Written by Step 1/2

| Table | Written By | Purpose |
| --- | --- | --- |
| `products` | `init-run` | Product brief. |
| `pipeline_runs` | `init-run` | One execution/config for a product. |
| `keywords` | `init-run` | Seed and expanded keyword terms. |
| `source_queries` | all ingestion commands | Request/response/error logging per API page. |
| `raw_payloads` | ingestion commands | Preserved raw source item JSON. |
| `paid_ads` | `ingest-foreplay` | Foreplay-shaped paid ad rows. |
| `ugc_items` | `ingest-topyappers-viral`, `ingest-topyappers-videos` | TopYappers-shaped UGC candidate rows. |
| `api_usage` | future monitoring | Provider credit/rate-limit tracking. |
| `paid_ad_transcripts` | created by schema only | Later paid-ad transcript processing stage. |
| `ugc_transcripts` | created by schema only | Later UGC transcript processing stage. |

## UGC Save Timestamp

`ugc_items.saved_to_supabase_at` records when a UGC video row was inserted into Supabase. It defaults to `now()` at database insert time.
