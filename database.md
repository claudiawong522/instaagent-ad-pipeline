# Database

This document reflects the current checked-in working tree at the time it was written, especially `supabase/schema.sql` and `supabase/migrations/001_split_paid_ads_and_ugc.sql`. The repo had uncommitted database and pipeline edits, so confirm against Supabase before treating this as a deployed-production snapshot.

## Tables

### `products`

Stores the product or brand context for a pipeline run.

| Column | Type | Constraints / default | Notes |
| --- | --- | --- | --- |
| `id` | `uuid` | Primary key, default `gen_random_uuid()` | Product identifier. |
| `name` | `text` | Not null | Product name. |
| `category` | `text` | Nullable | Product category. |
| `target_market` | `text` | Nullable | Intended geography, audience, or market. |
| `notes` | `text` | Nullable | Free-form setup notes. |
| `created_at` | `timestamptz` | Not null, default `now()` | Creation timestamp. |

### `pipeline_runs`

Tracks one configured collection run for one product.

| Column | Type | Constraints / default | Notes |
| --- | --- | --- | --- |
| `id` | `uuid` | Primary key, default `gen_random_uuid()` | Run identifier. |
| `product_id` | `uuid` | Not null, references `products(id)` on delete cascade | Product being analyzed. |
| `status` | `text` | Not null, default `'created'` | Run state. |
| `config` | `jsonb` | Not null, default `'{}'::jsonb` | Arbitrary run configuration. |
| `target_paid_count` | `integer` | Not null, default `1000` | Target number of paid ads. |
| `target_ugc_count` | `integer` | Not null, default `2500` | Target number of UGC items. |
| `top_k` | `integer` | Not null, default `3` | Downstream selection count. |
| `created_at` | `timestamptz` | Not null, default `now()` | Creation timestamp. |
| `updated_at` | `timestamptz` | Not null, default `now()` | Last update timestamp. |

### `keywords`

Stores seed and derived keywords attached to a run.

| Column | Type | Constraints / default | Notes |
| --- | --- | --- | --- |
| `id` | `uuid` | Primary key, default `gen_random_uuid()` | Keyword row identifier. |
| `run_id` | `uuid` | Not null, references `pipeline_runs(id)` on delete cascade | Owning run. |
| `keyword_text` | `text` | Not null | Keyword value used for source queries. |
| `keyword_type` | `text` | Not null, default `'seed'` | Keyword category. |
| `source` | `text` | Not null, default `'manual'` | Where the keyword came from. |
| `active` | `boolean` | Not null, default `true` | Whether the keyword should be used. |
| `created_at` | `timestamptz` | Not null, default `now()` | Creation timestamp. |

### `source_queries`

Logs each external API request attempted by the pipeline.

| Column | Type | Constraints / default | Notes |
| --- | --- | --- | --- |
| `id` | `uuid` | Primary key, default `gen_random_uuid()` | Query log identifier. |
| `run_id` | `uuid` | Nullable, references `pipeline_runs(id)` on delete cascade | Run that triggered the query. |
| `provider` | `text` | Not null | Source provider, for example `foreplay` or `topyappers`. |
| `endpoint` | `text` | Not null | Provider endpoint path. |
| `method` | `text` | Not null | HTTP method. |
| `request_params` | `jsonb` | Not null, default `'{}'::jsonb` | Query params or request body. |
| `page_cursor` | `text` | Nullable | Cursor or pagination token when available. |
| `status` | `text` | Not null, default `'started'` | Query state such as `started`, `completed`, or `failed`. |
| `http_status` | `integer` | Nullable | HTTP status for failed or tracked responses. |
| `response_count` | `integer` | Nullable | Number of items extracted from the response. |
| `error_message` | `text` | Nullable | Error text for failed requests. |
| `started_at` | `timestamptz` | Not null, default `now()` | Request start timestamp. |
| `completed_at` | `timestamptz` | Nullable | Request completion timestamp. |

### `api_usage`

Records one usage row per live provider API response. Fixture-based `--input-json` runs and dry-runs do not write usage rows.

| Column | Type | Constraints / default | Notes |
| --- | --- | --- | --- |
| `id` | `uuid` | Primary key, default `gen_random_uuid()` | Usage row identifier. |
| `run_id` | `uuid` | Nullable, references `pipeline_runs(id)` on delete set null | Related run, if known. |
| `provider` | `text` | Not null | API provider. |
| `endpoint` | `text` | Not null | Provider endpoint. |
| `credits_used` | `numeric` | Nullable | API credits consumed when exposed in provider headers. |
| `rate_limit` | `jsonb` | Not null, default `'{}'::jsonb` | HTTP status, response count, and selected rate-limit/usage/quota headers. |
| `request_timestamp` | `timestamptz` | Not null, default `now()` | Usage timestamp. |

### `raw_payloads`

Stores raw provider payloads before normalization.

| Column | Type | Constraints / default | Notes |
| --- | --- | --- | --- |
| `id` | `uuid` | Primary key, default `gen_random_uuid()` | Raw payload identifier. |
| `run_id` | `uuid` | Nullable, references `pipeline_runs(id)` on delete cascade | Owning run. |
| `source_query_id` | `uuid` | Nullable, references `source_queries(id)` on delete set null | Query that produced this payload. |
| `provider` | `text` | Not null | Source provider. |
| `endpoint` | `text` | Not null | Provider endpoint. |
| `external_id` | `text` | Nullable | Provider-side item id when available. |
| `payload_json` | `jsonb` | Not null | Full raw item JSON. |
| `payload_storage_path` | `text` | Nullable | Optional object-storage location for larger payloads. |
| `fetched_at` | `timestamptz` | Not null, default `now()` | Fetch timestamp. |

### `paid_ads`

Stores Foreplay paid ad records with stable response fields as first-class columns. Provider-specific overflow fields that are not promoted to columns live in `source_metrics`.

| Column | Type | Constraints / default | Notes |
| --- | --- | --- | --- |
| `paid_ad_row_id` | `uuid` | Primary key, default `gen_random_uuid()` | Supabase row identifier. |
| `run_id` | `uuid` | Not null, references `pipeline_runs(id)` on delete cascade | Owning run. |
| `raw_payload_id` | `uuid` | Nullable, references `raw_payloads(id)` on delete set null | Raw item used for normalization. |
| `id` | `text` | Not null | Foreplay `id` response field. |
| `live` | `boolean` | Nullable | Foreplay `live` response field. |
| `name` | `text` | Nullable | Foreplay `name` response field. |
| `type` | `text` | Nullable | Foreplay `type` response field. |
| `ad_id` | `text` | Nullable | Foreplay `ad_id` response field. |
| `cards` | `jsonb` | Nullable | Foreplay `cards` response field. |
| `image` | `text` | Nullable | Foreplay `image` response field. |
| `video` | `text` | Nullable | Foreplay `video` response field. |
| `avatar` | `text` | Nullable | Foreplay `avatar` response field. |
| `niches` | `jsonb` | Nullable | Foreplay `niches` response field. |
| `persona` | `jsonb` | Nullable | Foreplay `persona` response field. |
| `brand_id` | `text` | Nullable | Foreplay `brand_id` response field. |
| `cta_type` | `text` | Nullable | Foreplay `cta_type` response field. |
| `headline` | `text` | Nullable | Foreplay `headline` response field. |
| `link_url` | `text` | Nullable | Foreplay `link_url` response field. |
| `cta_title` | `text` | Nullable | Foreplay `cta_title` response field. |
| `languages` | `jsonb` | Nullable | Foreplay `languages` response field. |
| `thumbnail` | `text` | Nullable | Foreplay `thumbnail` response field. |
| `categories` | `jsonb` | Nullable | Foreplay `categories` response field. |
| `description` | `text` | Nullable | Foreplay `description` response field. |
| `market_target` | `text` | Nullable | Foreplay `market_target` response field. |
| `content_filter` | `jsonb` | Nullable | Foreplay `content_filter` response field. |
| `display_format` | `text` | Nullable | Foreplay `display_format` response field. |
| `video_duration` | `numeric` | Nullable | Foreplay `video_duration` response field. |
| `started_running` | `numeric` | Nullable | Foreplay `started_running` response field, usually epoch milliseconds. |
| `product_category` | `text` | Nullable | Foreplay `product_category` response field. |
| `running_duration` | `numeric` | Nullable | Foreplay `running_duration` response field. |
| `emotional_drivers` | `jsonb` | Nullable | Foreplay `emotional_drivers` response field. |
| `creative_targeting` | `text` | Nullable | Foreplay `creative_targeting` response field. |
| `full_transcription` | `text` | Nullable | Foreplay `full_transcription` response field. |
| `publisher_platform` | `jsonb` | Nullable | Foreplay `publisher_platform` response field. |
| `timestamped_transcription` | `jsonb` | Nullable | Foreplay `timestamped_transcription` response field. |
| `time_product_was_mentioned` | `numeric` | Nullable | Foreplay `time_product_was_mentioned` response field. |
| `source_metrics` | `jsonb` | Not null, default `{}` | Provider-specific fields not mapped to first-class columns. |
| `saved_to_supabase_at` | `timestamptz` | Not null, default `now()` | Timestamp when the row was saved to Supabase. |

Unique constraint: `unique (run_id, id)`.

### `ugc_items`

Stores TopYappers UGC records with columns for stable viral-content fields and optional metadata-only Videos fields. Provider-specific overflow fields that are not promoted to columns live in `source_metrics`.

| Column | Type | Constraints / default | Notes |
| --- | --- | --- | --- |
| `id` | `uuid` | Primary key, default `gen_random_uuid()` | Supabase row identifier. |
| `run_id` | `uuid` | Not null, references `pipeline_runs(id)` on delete cascade | Owning run. |
| `raw_payload_id` | `uuid` | Nullable, references `raw_payloads(id)` on delete set null | Raw item used for normalization. |
| `external_id` | `text` | Not null | Dedupe id, chosen from TopYappers `id`, `iv_id`, `video_id`, or `videoId`. |
| `topyappers_id` | `text` | Nullable | TopYappers `id` field when returned. |
| `iv_id` | `text` | Nullable | TopYappers Videos `iv_id` field when using the metadata endpoint. |
| `account_type` | `text` | Nullable | TopYappers field. |
| `age` | `integer` | Nullable | TopYappers field. |
| `avatar` | `text` | Nullable | TopYappers field. |
| `bio` | `text` | Nullable | TopYappers field. |
| `brand_mentioned` | `jsonb` | Nullable | TopYappers field. |
| `categories` | `jsonb` | Nullable | TopYappers field. |
| `color_palette` | `jsonb` | Nullable | TopYappers field. |
| `comments` | `bigint` | Nullable | TopYappers field. |
| `comments_to_views_ratio` | `numeric` | Nullable | TopYappers field. |
| `content_category` | `text` | Nullable | TopYappers field. |
| `content_format` | `text` | Nullable | TopYappers field. |
| `content_tone` | `text` | Nullable | TopYappers field. |
| `country` | `text` | Nullable | TopYappers field. |
| `cover` | `text` | Nullable | TopYappers field. |
| `creator_avg_views` | `numeric` | Nullable | TopYappers field. |
| `creator_engagement_rate` | `numeric` | Nullable | TopYappers field. |
| `creator_language` | `text` | Nullable | TopYappers field. |
| `cta_type` | `text` | Nullable | TopYappers field. |
| `date_added` | `timestamptz` | Nullable | TopYappers field. |
| `date_created` | `timestamptz` | Nullable | TopYappers field. |
| `date_created_timestamp` | `numeric` | Nullable | TopYappers Videos field when using the metadata endpoint. |
| `description` | `text` | Nullable | TopYappers field. |
| `face_count` | `integer` | Nullable | TopYappers field. |
| `follower_tier` | `text` | Nullable | TopYappers field. |
| `followers` | `bigint` | Nullable | Viral-content follower count field. |
| `gender` | `text` | Nullable | TopYappers field. |
| `hair_color` | `text` | Nullable | TopYappers field. |
| `handle` | `text` | Nullable | Viral-content creator handle, mapped from `handle` or `creatorUsername`. |
| `has_face` | `boolean` | Nullable | TopYappers field. |
| `has_product` | `boolean` | Nullable | TopYappers field. |
| `has_text_overlay` | `boolean` | Nullable | TopYappers field. |
| `hashtags` | `jsonb` | Nullable | TopYappers field. |
| `hook` | `text` | Nullable | TopYappers field. |
| `is_ai_generated` | `boolean` | Nullable | TopYappers field. |
| `is_branded` | `boolean` | Nullable | TopYappers field. |
| `is_promotional` | `boolean` | Nullable | TopYappers field. |
| `is_trending_format` | `boolean` | Nullable | TopYappers field. |
| `likes` | `bigint` | Nullable | TopYappers field. |
| `likes_to_views_ratio` | `numeric` | Nullable | TopYappers field. |
| `main_category` | `text` | Nullable | TopYappers field. |
| `music` | `jsonb` | Nullable | TopYappers field. |
| `nickname` | `text` | Nullable | TopYappers field. |
| `primary_emotion` | `text` | Nullable | TopYappers field. |
| `product_category` | `text` | Nullable | TopYappers field. |
| `production_quality` | `text` | Nullable | TopYappers field. |
| `race` | `text` | Nullable | TopYappers field. |
| `setting` | `text` | Nullable | TopYappers field. |
| `shares` | `bigint` | Nullable | TopYappers field. |
| `shares_to_views_ratio` | `numeric` | Nullable | TopYappers field. |
| `source` | `text` | Nullable | TopYappers source platform field. |
| `subtitles` | `text` | Nullable | TopYappers Videos subtitle field when using the metadata endpoint. |
| `target_demographic` | `text` | Nullable | TopYappers field. |
| `user_followers` | `bigint` | Nullable | TopYappers Videos creator follower count when using the metadata endpoint. |
| `user_handle` | `text` | Nullable | TopYappers creator handle, mapped from `user_handle`, `handle`, or viral-content `creatorUsername`. |
| `user_id` | `text` | Nullable | TopYappers Videos user id when using the metadata endpoint. |
| `video_id` | `text` | Nullable | TopYappers Videos video id when using the metadata endpoint. |
| `video_url` | `text` | Nullable | URL-backed UGC video URL, mapped from provider URL fields or derived from `source`, handle, and `video_id`. |
| `video_ranges` | `jsonb` | Nullable | TopYappers field. |
| `video_topic` | `text` | Nullable | TopYappers field. |
| `views` | `bigint` | Nullable | TopYappers field. |
| `views_to_avg_ratio` | `numeric` | Nullable | TopYappers field. |
| `virality_score` | `numeric` | Nullable | TopYappers field. |
| `virality_tier` | `text` | Nullable | TopYappers field. |
| `visual_style` | `text` | Nullable | TopYappers field. |
| `source_metrics` | `jsonb` | Not null, default `{}` | Provider-specific fields not mapped to first-class columns, plus `endpoint_kind`. |
| `saved_to_supabase_at` | `timestamptz` | Not null, default `now()` | Timestamp when the row was saved to Supabase. |

Unique constraint: `unique (run_id, external_id)`.

### `paid_ad_transcripts`

Stores transcript rows attached to Foreplay-shaped paid ad rows.

| Column | Type | Constraints / default | Notes |
| --- | --- | --- | --- |
| `id` | `uuid` | Primary key, default `gen_random_uuid()` | Transcript row identifier. |
| `paid_ad_row_id` | `uuid` | Not null, references `paid_ads(paid_ad_row_id)` on delete cascade | Parent paid ad row. |
| `transcript_text` | `text` | Nullable | Transcript text. |
| `transcript_segments` | `jsonb` | Nullable | Segment-level transcript data. |
| `transcript_source` | `text` | Nullable | Source of the transcript. |
| `created_at` | `timestamptz` | Not null, default `now()` | Creation timestamp. |

### `ugc_transcripts`

Stores transcript rows attached to normalized UGC items.

| Column | Type | Constraints / default | Notes |
| --- | --- | --- | --- |
| `id` | `uuid` | Primary key, default `gen_random_uuid()` | Transcript row identifier. |
| `ugc_item_id` | `uuid` | Not null, references `ugc_items(id)` on delete cascade | Parent UGC item. |
| `transcript_text` | `text` | Nullable | Transcript text. |
| `transcript_segments` | `jsonb` | Nullable | Segment-level transcript data. |
| `transcript_source` | `text` | Nullable | Source of the transcript. |
| `created_at` | `timestamptz` | Not null, default `now()` | Creation timestamp. |

## Indexes

| Index | Table | Columns / expression | Purpose |
| --- | --- | --- | --- |
| `keywords_run_id_idx` | `keywords` | `run_id` | Find keywords for a run. |
| `source_queries_run_id_idx` | `source_queries` | `run_id` | Find query logs for a run. |
| `raw_payloads_run_id_idx` | `raw_payloads` | `run_id` | Find raw payloads for a run. |
| `paid_ads_run_id_idx` | `paid_ads` | `run_id` | Find paid ads for a run. |
| `paid_ads_id_idx` | `paid_ads` | `id` | Lookup by Foreplay item id. |
| `paid_ads_ad_id_idx` | `paid_ads` | `ad_id` | Lookup by Foreplay ad id. |
| `paid_ads_brand_id_idx` | `paid_ads` | `brand_id` | Find ads for a Foreplay brand. |
| `paid_ads_product_category_idx` | `paid_ads` | `product_category` | Filter paid ads by Foreplay product category. |
| `paid_ads_saved_to_supabase_at_idx` | `paid_ads` | `saved_to_supabase_at desc` | Find recently saved paid ads. |
| `ugc_items_run_id_idx` | `ugc_items` | `run_id` | Find UGC items for a run. |
| `ugc_items_external_idx` | `ugc_items` | `external_id` | Lookup by provider id. |
| `ugc_items_virality_idx` | `ugc_items` | `virality_score desc` | Rank UGC items by virality. |

## Simple Data Flow

```text
init-run
  -> products
  -> pipeline_runs
  -> keywords

ingest-foreplay --run-id ... --keyword ...
  -> source_queries row starts
  -> Foreplay GET /api/discovery/ads
  -> api_usage logs HTTP status, response count, and rate/usage headers
  -> source_queries row completes or fails
  -> raw_payloads stores each raw ad item
  -> normalize_foreplay_ad()
  -> paid_ads upsert on run_id + id

ingest-topyappers-viral --run-id ... --keyword ...
  -> source_queries row starts
  -> TopYappers POST /api/v1/viral-content
  -> api_usage logs HTTP status, response count, and rate/usage headers
  -> source_queries row completes or fails
  -> raw_payloads stores each raw UGC item
  -> normalize_topyappers_item(endpoint_kind="viral-content")
  -> ugc_items upsert on run_id + external_id

ingest-topyappers-videos --run-id ... --keyword ...
  -> source_queries row starts
  -> TopYappers GET /api/v1/videos metadata-only fallback
  -> api_usage logs HTTP status, response count, and rate/usage headers
  -> source_queries row completes or fails
  -> raw_payloads stores each raw video item
  -> normalize_topyappers_item(endpoint_kind="videos")
  -> ugc_items upsert on run_id + external_id
```

## Relationship Map

```text
products
  -> pipeline_runs
       -> keywords
       -> source_queries
       -> raw_payloads
       -> paid_ads
            -> paid_ad_transcripts
       -> ugc_items
            -> ugc_transcripts
       -> api_usage
```

Notes:

- `raw_payloads` is the audit and re-normalization source. Keep it when provider payload shapes change.
- `paid_ads` stores Foreplay-shaped paid ad rows; `ugc_items` stores UGC candidate rows.
- `source_queries` records request status, parameters, response counts, and failures.
- `api_usage` records one row per live provider HTTP response, including HTTP status, response count, selected rate-limit/usage headers, and credits used when exposed by provider headers.
- Transcript tables exist, but the current ingestion path writes Foreplay transcript fields directly into matching `paid_ads` columns when they are present.
