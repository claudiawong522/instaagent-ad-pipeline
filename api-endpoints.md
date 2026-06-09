# API Endpoints

This document lists the endpoints used by the Step 1/2 implementation, their input fields, output fields, and Supabase mappings.

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
| `limit` | integer | yes | yes | Page size. Foreplay docs list max 250 for similar ad endpoints. |
| `offset` | integer | yes | yes | Offset pagination. |
| `order` | string | yes | yes | Defaults to `longest_running`. |
| `live` | boolean | no | yes | Optional active-status filter. |
| `display_format` | string | no | yes | Optional format filter such as `video`. |
| `publisher_platform` | string | no | yes | Optional platform filter such as `instagram`, `facebook`, or `tiktok`. |
| `languages` | string/string[] | no | yes | Optional language filter. |
| `market_target` | string | no | yes | Optional B2B/B2C filter. |
| `running_duration_min_days` | integer | no | yes | Optional longevity minimum. |
| `running_duration_max_days` | integer | no | yes | Optional longevity maximum. |

### Output Columns / Response Fields

| Response Field | Supabase Destination | Notes |
| --- | --- | --- |
| `id`, `ad_id` | `creative_items.external_id` | Prefer `id`, fallback to `ad_id`. |
| `link_url`, `url`, `share_url` | `creative_items.url` | Destination or public ad URL where available. |
| `video`, `image` | `creative_items.media_url` | Main media URL. |
| `thumbnail` | `creative_items.thumbnail_url` | Thumbnail image. |
| `brand.name`, `brand_name`, `page_name`, `name` | `creative_items.creator_or_brand` | Best available brand/page label. |
| `headline`, `description`, `body` | `creative_items.caption` | Best available ad text. |
| `publisher_platform` | `creative_items.platform` | Stored as text/JSON-compatible value. |
| `display_format` | `creative_items.display_format` | Video/image/carousel/etc. |
| `started_running` | `creative_items.started_running_at` | Parsed as timestamp by Supabase if valid. |
| `running_duration`, `running_duration_days` | `creative_items.running_duration_days` and `source_metrics` | Used later for paid ranking. |
| `full_transcription`, `timestamped_transcription`, `cards` | `creative_items.source_metrics` | Preserved now; transcript stage comes later. |
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

| Response Field | Supabase Destination | Notes |
| --- | --- | --- |
| `id`, `videoId`, `iv_id` | `creative_items.external_id` | Prefer stable source id. |
| `videoUrl`, `url`, `webVideoUrl` | `creative_items.url` / `media_url` | URL fields vary by endpoint. |
| `thumbnailUrl` | `creative_items.thumbnail_url` | Thumbnail URL. |
| `creatorUsername`, `user_handle`, `username` | `creative_items.creator_or_brand` | Creator identity. |
| `caption`, `description`, `hook` | `creative_items.caption` | Best text field available. |
| `createdAt`, `date_created_timestamp` | `creative_items.posted_at` | Post date. |
| `views`, `likes`, `comments`, `shares`, `followers`, `viralityScore`, `hook`, `category`, `country`, `musicTitle` | `creative_items.source_metrics` | UGC ranking later uses `viralityScore`. |
| full item JSON | `raw_payloads.payload_json` | Raw source of truth. |

## TopYappers: Videos

- Provider: TopYappers
- Method: `GET`
- Endpoint: `https://api.topyappers.com/api/v1/videos`
- Code path: `ingest-topyappers-videos`
- Purpose: hydrate UGC records and retrieve subtitles/raw video metrics.

### Input Columns / Query Fields

| Field | Type | Required | Used by Code | Notes |
| --- | --- | --- | --- | --- |
| `page` | integer | yes | yes | Starts at 1. |
| `limit` | integer | yes | yes | Code defaults to 100. |
| `user_followers_min`, `user_followers_max` | integer | no | yes | Optional creator size filters. |
| `views_min`, `views_max` | integer | no | yes | Optional views filter. |
| `date_created_from`, `date_created_to` | string | no | yes | Date range if supported by API. |
| extra JSON params | object | no | yes | Passed through via `--extra-param key=value`. |

### Output Columns / Response Fields

| Response Field | Supabase Destination | Notes |
| --- | --- | --- |
| `iv_id`, `video_id`, `id` | `creative_items.external_id` | Prefer `iv_id`, fallback to video id. |
| `user_handle`, `creatorUsername` | `creative_items.creator_or_brand` | Creator identity. |
| `description`, `caption` | `creative_items.caption` | Main text. |
| `video_url`, `videoUrl`, `url` | `creative_items.url` / `media_url` | Media/public video URL. |
| `date_created_timestamp`, `createdAt` | `creative_items.posted_at` | Post timestamp. |
| `views`, `likes`, `comments`, `shares`, `user_followers`, `hashtags`, `subtitles` | `creative_items.source_metrics` | `subtitles` are preserved for later transcript processing. |
| full item JSON | `raw_payloads.payload_json` | Raw source of truth. |

## Supabase Tables Written by Step 1/2

| Table | Written By | Purpose |
| --- | --- | --- |
| `products` | `init-run` | Product brief. |
| `pipeline_runs` | `init-run` | One execution/config for a product. |
| `keywords` | `init-run` | Seed and expanded keyword terms. |
| `source_queries` | all ingestion commands | Request/response/error logging per API page. |
| `raw_payloads` | ingestion commands | Preserved raw source item JSON. |
| `creative_items` | ingestion commands | Normalized candidate rows. |
| `api_usage` | future monitoring | Provider credit/rate-limit tracking. |
| `transcripts` | created by schema only | Later transcript processing stage. |

