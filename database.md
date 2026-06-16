# Database

`supabase/schema.sql` is the canonical schema for a clean Supabase project. `supabase/migrations/` contains incremental changes for existing projects. Before building search or clustering on a live database, verify the live schema against the committed schema and migrations. If the live database drifted from manual edits or out-of-order migration runs, rebuild the schema cleanly in the same project after exporting anything you need, then start a fresh run as the canonical corpus. Add a second Supabase project later only for production isolation.

## Data Flow

1. User gives product info, campaign guidelines, target number of paid ads, and target number of UGC videos. This creates `products` and `pipeline_runs`.
2. If no manual keywords are passed, Claude Haiku extracts 3-5 keywords, aiming for 3 highly relevant single-word keywords, and splits paid ad / UGC targets across them. The allocations must add up to the user's requested totals. Keywords are stored in `keywords`; the Claude call is logged in `api_usage`.
3. Ingest commands load active keywords for the run. Apify paid-ad ingestion and TopYappers query each keyword for its allocated count. Each query is logged in `source_queries`; each live API response is logged in `api_usage`; raw JSON goes into `raw_payloads`.
4. If an API returns fewer ads or videos than requested for a keyword, the pipeline saves what came back and moves on.
5. Normalized Apify Meta Ad Library output fills `paid_ads`. Normalized TopYappers output fills `ugc_items`.
6. Current provider transcript text stays on `ugc_items.subtitles` when TopYappers returns it. After paid-ad ingestion, the LLM enrichment stage (`enrich-paid-ads`, auto-triggered by `ingest-apify-ads`) fetches each `paid_ads.video` mp4 into memory and sends it base64-encoded to OpenRouter (default model `google/gemini-3-flash-preview`) in a single call that returns the spoken transcript plus creative analysis metadata. Transcripts go to `paid_ad_transcripts`; analysis fields go to columns on `paid_ads` (`hook`, `persona`, `target_demographic`, `content_format`, and the rest of the analysis columns), with `analysis_model` and `analyzed_at` recording the run.
7. Live TopYappers ingestion and `backfill-ugc-transcripts` both copy non-empty `ugc_items.subtitles` into `ugc_transcripts`.
8. The same transcript stage finds remaining UGC rows without `subtitles`, sends supported public social video URLs to Apify, stores raw Apify output in `raw_payloads`, and writes cleaned transcript text plus parsed timestamp segments to `ugc_transcripts`.
9. `embed-items` writes separate ICP, format, and hook vectors to `item_embeddings`. `cluster-items` clusters ICP vectors per source, writes item assignments to `item_clusters`, and writes cluster summaries, centroids, exemplars, and optional OpenRouter labels to `clusters`.

### Diagram

```
User: product + campaign info
        │  init-run
        ▼
products ── pipeline_runs ── keywords  (Claude Haiku splits paid/UGC targets across 3-5 keywords)
        │
        ├─ ingest-apify-ads (per keyword)
        │     Meta Ad Library via Apify ──► paid_ads  (copy, video URL, metrics)
        │     └─ auto: OpenRouter enrichment (1 call/ad: video base64 + ad copy)
        │           ├─► paid_ad_transcripts   (transcript + segments)
        │           └─► paid_ads analysis columns (hook, persona/ICP, format, emotion, …)
        │
        └─ ingest-topyappers-viral (per keyword)
              TopYappers ──► ugc_items  (metrics + provider analysis fields)
              └─ auto: transcript backfill
                    ├─ subtitles present ──► ugc_transcripts (topyappers:subtitles)
                    └─ else video_url ──► Apify transcriber ──► ugc_transcripts (apify:…)

every external call ──► source_queries + api_usage;  every raw response ──► raw_payloads

        └─ embed-items (after analysis)
              paid_ads + ugc_items descriptor columns ──► Voyage AI ──► item_embeddings
              (three vectors per item: icp / format / hook)

        └─ cluster-items
              item_embeddings.icp ──► HDBSCAN ──► item_clusters + clusters
              optional OpenRouter labels ──► clusters.label_json + clusters.label_text
```

End state per run: both content tables carry comparable transcript and ICP/format/hook metadata, `item_embeddings` carries one pgvector row per item per embedding space, and `clusters` / `item_clusters` carry the implemented ICP grouping layer that later top-K selection can consume.

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

Stores generated or manual discovery keywords attached to a run, including per-keyword target allocations.

| Column | Type | Constraints / default | Notes |
| --- | --- | --- | --- |
| `id` | `uuid` | Primary key, default `gen_random_uuid()` | Keyword row identifier. |
| `run_id` | `uuid` | Not null, references `pipeline_runs(id)` on delete cascade | Owning run. |
| `keyword_text` | `text` | Not null | Keyword value used for source queries. |
| `keyword_type` | `text` | Not null, default `'seed'` | Keyword category. |
| `source` | `text` | Not null, default `'manual'` | Where the keyword came from. |
| `target_paid_count` | `integer` | Not null, default `0` | Number of paid ads to request for this keyword. |
| `target_ugc_count` | `integer` | Not null, default `0` | Number of UGC items to request for this keyword. |
| `active` | `boolean` | Not null, default `true` | Whether the keyword should be used. |
| `created_at` | `timestamptz` | Not null, default `now()` | Creation timestamp. |

### `source_queries`

Logs each external API request attempted by the pipeline.

| Column | Type | Constraints / default | Notes |
| --- | --- | --- | --- |
| `id` | `uuid` | Primary key, default `gen_random_uuid()` | Query log identifier. |
| `run_id` | `uuid` | Nullable, references `pipeline_runs(id)` on delete cascade | Run that triggered the query. |
| `provider` | `text` | Not null | Source provider, for example `apify:apify/facebook-ads-scraper` or `topyappers`. |
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

Records usage rows for live Claude keyword-generation calls and live provider API responses. Fixture-based `--input-json` runs and dry-runs do not write provider usage rows.

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

Stores Apify Meta Ad Library paid ad records with stable fields mapped into first-class columns. Provider-specific overflow fields that are not promoted to columns live in `source_metrics`.

| Column | Type | Constraints / default | Notes |
| --- | --- | --- | --- |
| `paid_ad_row_id` | `uuid` | Primary key, default `gen_random_uuid()` | Supabase row identifier. |
| `run_id` | `uuid` | Not null, references `pipeline_runs(id)` on delete cascade | Owning run. |
| `raw_payload_id` | `uuid` | Nullable, references `raw_payloads(id)` on delete set null | Raw item used for normalization. |
| `id` | `text` | Not null | Apify `adArchiveID` / `adArchiveId`. |
| `live` | `boolean` | Nullable | Apify `isActive`, or inferred from end date. |
| `name` | `text` | Nullable | Page name from Apify `snapshot.pageName` / `pageName`. |
| `type` | `text` | Nullable | Apify `snapshot.displayFormat` when available. |
| `ad_id` | `text` | Nullable | Apify `adArchiveID` / `adArchiveId`. |
| `cards` | `jsonb` | Nullable | Apify `snapshot.cards`. |
| `image` | `text` | Nullable | First image URL from Apify snapshot/card media. |
| `video` | `text` | Nullable | First video URL from Apify snapshot/card media. |
| `avatar` | `text` | Nullable | Apify `snapshot.pageProfilePictureUrl`. |
| `niches` | `jsonb` | Nullable | LLM enrichment: list of niche descriptors. |
| `persona` | `jsonb` | Nullable | LLM enrichment: the ICP the ad targets. |
| `brand_id` | `text` | Nullable | Apify `pageID` / `pageId`. |
| `cta_type` | `text` | Nullable | Apify `snapshot.ctaType` or card `ctaType`. |
| `headline` | `text` | Nullable | Apify `snapshot.title` or card `title`. |
| `link_url` | `text` | Nullable | Apify `snapshot.linkUrl` or card `linkUrl`. |
| `cta_title` | `text` | Nullable | Apify `snapshot.ctaText` or card `ctaText`. |
| `languages` | `jsonb` | Nullable | Apify language metadata if present. |
| `thumbnail` | `text` | Nullable | First preview/thumbnail URL from Apify media. |
| `categories` | `jsonb` | Nullable | Apify `categories` or `snapshot.pageCategories`. |
| `description` | `text` | Nullable | Apify `snapshot.body.text` or card `body`. |
| `market_target` | `text` | Nullable | LLM enrichment: market/region/segment. |
| `content_filter` | `jsonb` | Nullable | Reserved compatibility column. |
| `display_format` | `text` | Nullable | Apify `snapshot.displayFormat`. |
| `video_duration` | `numeric` | Nullable | Apify video duration if present. |
| `started_running` | `numeric` | Nullable | Apify `startDateFormatted` / `startDate`, stored as epoch milliseconds. |
| `product_category` | `text` | Nullable | LLM enrichment: product category. |
| `running_duration` | `numeric` | Nullable | Days computed from Apify start/end dates, or start/current time for active ads. |
| `emotional_drivers` | `jsonb` | Nullable | LLM enrichment: list of persuasion levers. |
| `creative_targeting` | `text` | Nullable | LLM enrichment: who the creative addresses and how. |
| `full_transcription` | `text` | Nullable | Stays null; transcripts live in `paid_ad_transcripts`. |
| `publisher_platform` | `jsonb` | Nullable | Apify `publisherPlatform`. |
| `timestamped_transcription` | `jsonb` | Nullable | Stays null; transcripts live in `paid_ad_transcripts`. |
| `time_product_was_mentioned` | `numeric` | Nullable | LLM enrichment: seconds until the product first appears or is mentioned. |
| `hook` | `text` | Nullable | LLM enrichment: opening line or visual device. |
| `main_category` | `text` | Nullable | LLM enrichment. |
| `content_category` | `text` | Nullable | LLM enrichment. |
| `content_format` | `text` | Nullable | LLM enrichment, e.g. `ugc_testimonial`, `demo`. |
| `content_tone` | `text` | Nullable | LLM enrichment. |
| `primary_emotion` | `text` | Nullable | LLM enrichment. |
| `target_demographic` | `text` | Nullable | LLM enrichment audience descriptor. |
| `video_topic` | `text` | Nullable | LLM enrichment. |
| `visual_style` | `text` | Nullable | LLM enrichment. |
| `production_quality` | `text` | Nullable | LLM enrichment: low/medium/high/professional. |
| `setting` | `text` | Nullable | LLM enrichment. |
| `color_palette` | `jsonb` | Nullable | LLM enrichment: list of dominant colors. |
| `has_face` | `boolean` | Nullable | LLM enrichment. |
| `face_count` | `integer` | Nullable | LLM enrichment. |
| `gender` | `text` | Nullable | LLM enrichment: on-screen presenters. |
| `age` | `integer` | Nullable | LLM enrichment: approximate age of the primary person. |
| `race` | `text` | Nullable | LLM enrichment. |
| `hair_color` | `text` | Nullable | LLM enrichment. |
| `has_product` | `boolean` | Nullable | LLM enrichment. |
| `has_text_overlay` | `boolean` | Nullable | LLM enrichment. |
| `is_ai_generated` | `boolean` | Nullable | LLM enrichment. |
| `is_trending_format` | `boolean` | Nullable | LLM enrichment. |
| `brand_mentioned` | `jsonb` | Nullable | LLM enrichment: list of brand names spoken or shown. |
| `analysis_model` | `text` | Nullable | OpenRouter model that produced the analysis, e.g. `google/gemini-3-flash-preview`. |
| `analyzed_at` | `timestamptz` | Nullable | When enrichment ran; null means not yet enriched. |
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

Stores transcript rows attached to paid ad rows. Written by the LLM enrichment stage with `transcript_source = 'openrouter:<model>'`; one row is upserted per `(paid_ad_row_id, transcript_source)` (unique index `paid_ad_transcripts_row_source_idx`).

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

Unique index: `ugc_transcripts_item_source_idx` on `(ugc_item_id, transcript_source)`.

### `item_embeddings`

Stores one embedding vector per item per embedding space, written by `embed-items` (Voyage AI; migration `013_item_embeddings.sql`, requires the `vector` extension). Items are embedded from their analyzed descriptor columns; spaces with no usable text are skipped. Upserts are idempotent on `(item_type, item_id, space, embedding_model)`.

| Column | Type | Constraints / default | Notes |
| --- | --- | --- | --- |
| `id` | `uuid` | Primary key, default `gen_random_uuid()` | Embedding row identifier. |
| `run_id` | `uuid` | Not null, references `pipeline_runs(id)` on delete cascade | Parent run. |
| `item_type` | `text` | Not null, check in (`paid_ad`, `ugc_item`) | Which content table the item lives in. |
| `item_id` | `uuid` | Not null | `paid_ads.paid_ad_row_id` or `ugc_items.id` (no FK — points at one of two tables). |
| `space` | `text` | Not null, check in (`icp`, `format`, `hook`) | Embedding space. Never concatenated across spaces. |
| `embedding_model` | `text` | Not null | Voyage model name, e.g. `voyage-4-lite`. |
| `source_text` | `text` | Not null | The exact text that was embedded, for debugging and dedupe. |
| `embedding` | `vector(1024)` | Not null | pgvector embedding. |
| `created_at` | `timestamptz` | Not null, default `now()` | Creation timestamp. |

Unique constraint on `(item_type, item_id, space, embedding_model)`.

### `item_clusters`

Stores one clustering assignment per embedded item and embedding space, written by `cluster-items` (migration `014_item_clusters.sql`). The command currently clusters ICP vectors only, but `space` is kept for parity with `item_embeddings`.

| Column | Type | Constraints / default | Notes |
| --- | --- | --- | --- |
| `id` | `uuid` | Primary key, default `gen_random_uuid()` | Assignment row identifier. |
| `run_id` | `uuid` | Not null, references `pipeline_runs(id)` on delete cascade | Parent run. |
| `item_type` | `text` | Not null, check in (`paid_ad`, `ugc_item`) | Source table represented by `item_id`. |
| `item_id` | `uuid` | Not null | `paid_ads.paid_ad_row_id` or `ugc_items.id`. |
| `space` | `text` | Not null, check in (`icp`, `format`, `hook`) | Embedding space; currently `icp`. |
| `cluster_label` | `integer` | Not null | HDBSCAN label; `-1` means noise. |
| `distance_to_centroid` | `double precision` | Nullable | Cosine distance to the cluster centroid for clustered items. |
| `clustering_params` | `text` | Not null | Parameter string, e.g. `hdbscan:min_cluster_size=5`. |
| `created_at` | `timestamptz` | Not null, default `now()` | Creation timestamp. |

Unique constraint on `(item_type, item_id, space)`.

### `clusters`

Stores one discovered cluster per run, source, and space, written by `cluster-items`. It keeps centroid/exemplar metadata and optional OpenRouter labels for ICP clusters.

| Column | Type | Constraints / default | Notes |
| --- | --- | --- | --- |
| `id` | `uuid` | Primary key, default `gen_random_uuid()` | Cluster row identifier. |
| `run_id` | `uuid` | Not null, references `pipeline_runs(id)` on delete cascade | Parent run. |
| `item_type` | `text` | Not null, check in (`paid_ad`, `ugc_item`) | Source being clustered. |
| `space` | `text` | Not null, check in (`icp`, `format`, `hook`) | Embedding space; currently `icp`. |
| `cluster_label` | `integer` | Not null | HDBSCAN cluster label. |
| `name` | `text` | Nullable | Short label, currently the labeled persona when labeling succeeds. |
| `label_json` | `jsonb` | Nullable | Structured OpenRouter label with persona, pains, scroll topics, and quote. |
| `label_text` | `text` | Nullable | Human-readable label render. |
| `centroid` | `vector(1024)` | Nullable | Cluster centroid. |
| `member_count` | `integer` | Not null | Number of items in the cluster. |
| `exemplar_item_ids` | `jsonb` | Nullable | Closest item IDs used as labeling exemplars. |
| `silhouette` | `double precision` | Nullable | Cell-level silhouette score when defined. |
| `label_model` | `text` | Nullable | OpenRouter model used for labeling. |
| `clustering_params` | `text` | Not null | Parameter string, e.g. `hdbscan:min_cluster_size=5`. |
| `created_at` | `timestamptz` | Not null, default `now()` | Creation timestamp. |

Unique constraint on `(run_id, item_type, space, cluster_label)`.

## Indexes

| Index | Table | Columns / expression | Purpose |
| --- | --- | --- | --- |
| `keywords_run_id_idx` | `keywords` | `run_id` | Find keywords for a run. |
| `source_queries_run_id_idx` | `source_queries` | `run_id` | Find query logs for a run. |
| `raw_payloads_run_id_idx` | `raw_payloads` | `run_id` | Find raw payloads for a run. |
| `paid_ads_run_id_idx` | `paid_ads` | `run_id` | Find paid ads for a run. |
| `paid_ads_id_idx` | `paid_ads` | `id` | Lookup by Apify/Meta ad archive id. |
| `paid_ads_ad_id_idx` | `paid_ads` | `ad_id` | Lookup by Apify/Meta ad archive id. |
| `paid_ads_brand_id_idx` | `paid_ads` | `brand_id` | Find ads for a Meta page id. |
| `paid_ads_product_category_idx` | `paid_ads` | `product_category` | Filter paid ads when product category is populated by a later stage. |
| `paid_ads_saved_to_supabase_at_idx` | `paid_ads` | `saved_to_supabase_at desc` | Find recently saved paid ads. |
| `paid_ads_analyzed_at_idx` | `paid_ads` | `analyzed_at` | Find rows still needing enrichment or rows already analyzed. |
| `paid_ads_content_category_idx` | `paid_ads` | `content_category` | Filter enriched paid ads by content category. |
| `paid_ads_video_topic_idx` | `paid_ads` | `video_topic` | Filter enriched paid ads by video topic. |
| `ugc_items_run_id_idx` | `ugc_items` | `run_id` | Find UGC items for a run. |
| `ugc_items_external_idx` | `ugc_items` | `external_id` | Lookup by provider id. |
| `ugc_items_video_id_idx` | `ugc_items` | `video_id` | Lookup TopYappers video IDs. |
| `ugc_items_video_topic_idx` | `ugc_items` | `video_topic` | Filter UGC by provider video topic. |
| `ugc_items_content_category_idx` | `ugc_items` | `content_category` | Filter UGC by provider content category. |
| `ugc_items_virality_idx` | `ugc_items` | `virality_score desc` | Rank UGC items by virality. |
| `ugc_items_saved_to_supabase_at_idx` | `ugc_items` | `saved_to_supabase_at desc` | Find recently saved UGC items. |
| `ugc_transcripts_item_source_idx` | `ugc_transcripts` | `ugc_item_id, transcript_source` | Upsert one transcript per item/source and support transcript lookup by UGC item. |
| `paid_ad_transcripts_row_source_idx` | `paid_ad_transcripts` | `paid_ad_row_id, transcript_source` | Upsert one transcript per paid ad/source. |
| `item_embeddings_run_idx` | `item_embeddings` | `run_id` | Find embeddings for a run. |
| `item_embeddings_space_idx` | `item_embeddings` | `item_type, space` | Pull one embedding space per source for clustering. |
| `item_clusters_run_idx` | `item_clusters` | `run_id` | Find cluster assignments for a run. |
| `item_clusters_cluster_idx` | `item_clusters` | `item_type, space, cluster_label` | Find members of a source/space cluster. |
| `clusters_run_idx` | `clusters` | `run_id` | Find cluster summaries for a run. |
| `clusters_lookup_idx` | `clusters` | `item_type, space` | Lookup cluster summaries by source and space. |
