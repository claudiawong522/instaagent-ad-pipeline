# Database

`supabase/schema.sql` is the canonical schema for a clean Supabase project. `supabase/migrations/` contains incremental changes for existing projects. Before building search or clustering on a live database, verify the live schema against the committed schema and migrations. If the live database drifted from manual edits or out-of-order migration runs, rebuild the schema cleanly in the same project after exporting anything you need, then start a fresh run as the canonical corpus. Add a second Supabase project later only for production isolation.

## Data Flow

1. User gives product info, campaign guidelines, target number of paid ads, and target number of organic videos. This creates `products` and `pipeline_runs` (`init-run`).
2. If no manual keywords are passed, Claude Haiku extracts 3-5 keywords, aiming for 3 highly relevant single-word keywords, and splits paid ad / organic targets across them. The allocations must add up to the user's requested totals. Keywords are stored in `keywords`; the Claude call is logged in `api_usage`.
3. Ingest commands load active keywords for the run. Apify paid-ad ingestion (`ingest-apify-ads`, Meta Ad Library) and Apify organic ingestion (`ingest-tiktok` via `clockworks/tiktok-scraper`; `ingest-instagram` reels via `data-slayer/instagram-search-reels`) query each keyword for its allocated count. Each query is logged in `source_queries`; each live API response is logged in `api_usage`; raw JSON goes into `raw_payloads`.
4. If an API returns fewer ads or videos than requested for a keyword, the pipeline saves what came back and moves on.
5. Normalized Apify Meta Ad Library output fills `paid_ads`. Normalized Apify TikTok/Instagram output fills `ugc_items`. TikTok follower counts are native; Instagram reel follower counts are backfilled by `backfill-ig-followers` (via `apify/instagram-profile-scraper`). The Apify normalizers recompute `virality_score` / `virality_tier` from engagement metrics.
6. Vision enrichment runs after ingestion: `enrich-paid-ads` is auto-triggered by `ingest-apify-ads`, and organic vision enrichment (`enrich-ugc`) is auto-triggered by `ingest-tiktok` / `ingest-instagram`. For each item, enrichment downloads the video bytes into memory, uploads them to the Supabase Storage bucket `ad-videos`, and records the persisted `storage_video_url` / `storage_thumb_url` on the item table (`paid_ads` / `ugc_items`). It reuses the same in-memory bytes, base64-encoded, for a single OpenRouter vision call (default model `google/gemini-3-flash-preview`) that returns the spoken transcript plus creative analysis. For paid ads, the existing ad copy is also passed to the model.
7. Each enrichment writes one row to `item_enrichments` (polymorphic on `item_type` / `item_id`, one row per item): `transcript_text` + `transcript_segments`, `ai_description`, and the analysis fields (`hook`, `persona`, `target_demographic`, `content_format`, and the rest), with `analysis_model` and `analyzed_at` recording the run. It also stamps the per-video outcome back onto the source row (`paid_ads.enrichment_status` / `ugc_items.enrichment_status`): `enriched` when the item became searchable, `expired` when the provider URL no longer served video bytes (Apify links expire before OpenRouter fetches them), or `failed` otherwise — so the campaigns UI can show "X of Y videos searchable" per platform via the `scrape-stats` endpoint.
8. `embed-items` writes ICP and search vectors to `item_embeddings` (Voyage AI). The `search` space combines `ai_description`, a labeled tag block, and the full transcript; the `icp` space combines `persona` and `target_demographic`.
9. `cluster-items` clusters ICP vectors per source, writes item assignments to `item_clusters`, and writes cluster summaries, centroids, exemplars, and optional OpenRouter labels to `clusters`.

### Diagram

```
User: product + campaign info
        │  init-run
        ▼
products ── pipeline_runs ── keywords  (Claude Haiku splits paid/organic targets across 3-5 keywords)
        │
        ├─ ingest-apify-ads (per keyword)
        │     Meta Ad Library via Apify ──► paid_ads  (copy, video URL, metrics)
        │     └─ auto: enrich-paid-ads
        │
        ├─ ingest-tiktok (per keyword)
        │     clockworks/tiktok-scraper ──► ugc_items  (metrics, native followers)
        │     └─ auto: enrich-ugc
        │
        └─ ingest-instagram (per keyword)
              data-slayer/instagram-search-reels ──► ugc_items  (metrics)
              ├─ backfill-ig-followers (apify/instagram-profile-scraper)
              └─ auto: enrich-ugc

   vision enrichment (paid + organic):
        download video bytes ──► Supabase Storage bucket 'ad-videos'
              └─► storage_video_url / storage_thumb_url on paid_ads / ugc_items
        same bytes base64 (+ ad copy for paid) ──► OpenRouter Gemini (1 call/item)
              └─► item_enrichments  (transcript + segments, ai_description, analysis fields)

every external call ──► source_queries + api_usage;  every raw response ──► raw_payloads

        └─ embed-items (after enrichment)
              item_enrichments ──► Voyage AI ──► item_embeddings
              (two vectors per item: icp / search)

        └─ cluster-items
              item_embeddings.icp ──► HDBSCAN ──► item_clusters + clusters
              optional OpenRouter labels ──► clusters.label_json + clusters.label_text
```

End state per run: both content tables carry persisted Storage video URLs, `item_enrichments` carries one transcript + analysis row per item, `item_embeddings` carries one pgvector row per item per embedding space (`icp` / `search`), and `clusters` / `item_clusters` carry the implemented ICP grouping layer that later top-K selection can consume.

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
| `target_ugc_count` | `integer` | Not null, default `2500` | Target number of organic items. |
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
| `target_ugc_count` | `integer` | Not null, default `0` | Number of organic items to request for this keyword. |
| `active` | `boolean` | Not null, default `true` | Whether the keyword should be used. |
| `created_at` | `timestamptz` | Not null, default `now()` | Creation timestamp. |

### `source_queries`

Logs each external API request attempted by the pipeline.

| Column | Type | Constraints / default | Notes |
| --- | --- | --- | --- |
| `id` | `uuid` | Primary key, default `gen_random_uuid()` | Query log identifier. |
| `run_id` | `uuid` | Nullable, references `pipeline_runs(id)` on delete cascade | Run that triggered the query. |
| `provider` | `text` | Not null | Source provider, for example `apify:apify/facebook-ads-scraper` or `apify:clockworks/tiktok-scraper`. |
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

Stores Apify Meta Ad Library paid ad records with stable fields mapped into first-class columns. Provider-specific overflow fields that are not promoted to columns live in `source_metrics`. Transcript and creative-analysis fields now live in `item_enrichments`, not on this table.

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
| `brand_id` | `text` | Nullable | Apify `pageID` / `pageId`. |
| `cta_type` | `text` | Nullable | Apify `snapshot.ctaType` or card `ctaType`. |
| `headline` | `text` | Nullable | Apify `snapshot.title` or card `title`. |
| `link_url` | `text` | Nullable | Apify `snapshot.linkUrl` or card `linkUrl`. |
| `cta_title` | `text` | Nullable | Apify `snapshot.ctaText` or card `ctaText`. |
| `languages` | `jsonb` | Nullable | Apify language metadata if present. |
| `thumbnail` | `text` | Nullable | First preview/thumbnail URL from Apify media. |
| `categories` | `jsonb` | Nullable | Apify `categories` or `snapshot.pageCategories`. |
| `description` | `text` | Nullable | Apify `snapshot.body.text` or card `body`. |
| `display_format` | `text` | Nullable | Apify `snapshot.displayFormat`. |
| `video_duration` | `numeric` | Nullable | Apify video duration if present. |
| `started_running` | `numeric` | Nullable | Apify `startDateFormatted` / `startDate`, stored as epoch milliseconds. |
| `running_duration` | `numeric` | Nullable | Days computed from Apify start/end dates, or start/current time for active ads. |
| `publisher_platform` | `jsonb` | Nullable | Apify `publisherPlatform`. |
| `storage_video_url` | `text` | Nullable | Persisted Supabase Storage (`ad-videos`) URL of the downloaded video; written by `enrich-paid-ads` (migration `015`). |
| `storage_thumb_url` | `text` | Nullable | Persisted Supabase Storage (`ad-videos`) URL of the thumbnail; written by `enrich-paid-ads` (migration `015`). |
| `enrichment_status` | `text` | Nullable | Per-video enrichment outcome written by `enrich-paid-ads` (migration `021`): `enriched` (searchable), `expired` (URL no longer served video), `failed` (analysis produced nothing / unsupported URL). Null until enrichment touches the row. |
| `enrichment_error` | `text` | Nullable | Human-readable reason for an `expired`/`failed` status (migration `021`). |
| `source_metrics` | `jsonb` | Not null, default `{}` | Provider-specific fields not mapped to first-class columns. |
| `saved_to_supabase_at` | `timestamptz` | Not null, default `now()` | Timestamp when the row was saved to Supabase. |

Unique constraint: `unique (run_id, id)`.

### `ugc_items`

Stores Apify TikTok / Instagram organic records with stable fields mapped into first-class columns. Provider-specific overflow fields that are not promoted to columns live in `source_metrics`. Transcript and creative-analysis fields now live in `item_enrichments`, not on this table.

| Column | Type | Constraints / default | Notes |
| --- | --- | --- | --- |
| `id` | `uuid` | Primary key, default `gen_random_uuid()` | Supabase row identifier. |
| `run_id` | `uuid` | Not null, references `pipeline_runs(id)` on delete cascade | Owning run. |
| `raw_payload_id` | `uuid` | Nullable, references `raw_payloads(id)` on delete set null | Raw item used for normalization. |
| `external_id` | `text` | Not null | Dedupe id, chosen from the Apify item id / video id. |
| `source` | `text` | Nullable | Platform the item came from: `tiktok` or `instagram`. |
| `video_id` | `text` | Nullable | Platform video id from the Apify payload. |
| `video_url` | `text` | Nullable | Organic video URL from the Apify payload. |
| `cover` | `text` | Nullable | Cover/thumbnail image URL. |
| `description` | `text` | Nullable | Caption / description text. |
| `hashtags` | `jsonb` | Nullable | Hashtags from the Apify payload. |
| `followers` | `bigint` | Nullable | Creator follower count; native for TikTok, backfilled for Instagram reels. |
| `handle` | `text` | Nullable | Creator handle. |
| `user_handle` | `text` | Nullable | Creator handle (alternate mapping). |
| `user_id` | `text` | Nullable | Platform user id. |
| `nickname` | `text` | Nullable | Creator display name. |
| `avatar` | `text` | Nullable | Creator avatar URL. |
| `views` | `bigint` | Nullable | View count. |
| `likes` | `bigint` | Nullable | Like count. |
| `comments` | `bigint` | Nullable | Comment count. |
| `shares` | `bigint` | Nullable | Share count. |
| `music` | `jsonb` | Nullable | Music/sound metadata from the Apify payload. |
| `date_created` | `timestamptz` | Nullable | Post creation timestamp. |
| `virality_score` | `numeric` | Nullable | Recomputed from engagement metrics by the Apify normalizer. |
| `virality_tier` | `text` | Nullable | Recomputed from engagement metrics by the Apify normalizer. |
| `storage_video_url` | `text` | Nullable | Persisted Supabase Storage (`ad-videos`) URL of the downloaded video; written by `enrich-ugc` (migration `015`). |
| `storage_thumb_url` | `text` | Nullable | Persisted Supabase Storage (`ad-videos`) URL of the thumbnail; written by `enrich-ugc` (migration `015`). |
| `enrichment_status` | `text` | Nullable | Per-video enrichment outcome written by `enrich-ugc` (migration `021`): `enriched` (searchable), `expired` (URL no longer served video), `failed`. Null until enrichment touches the row. |
| `enrichment_error` | `text` | Nullable | Human-readable reason for an `expired`/`failed` status (migration `021`). |
| `format_id` | `uuid` | Nullable, references `viral_formats(id)` on delete cascade | Trend pipeline (migration `025`): set when this is an example video of a viral format (`source='trend'`). |
| `source_metrics` | `jsonb` | Not null, default `{}` | Provider-specific fields not mapped to first-class columns, plus `endpoint_kind`. |
| `saved_to_supabase_at` | `timestamptz` | Not null, default `now()` | Timestamp when the row was saved to Supabase. |

Unique constraint: `unique (run_id, external_id)`.

### `viral_formats`

Trend pipeline (migration `025`). One row per viral format scraped from a web trend page (`ingest-trends`); example videos hang off it via `ugc_items.format_id` and a format is ranked on the `/trends` dashboard by its videos' aggregate live views. `classify-formats` writes the free-form `niche_constraint` plus (migration `027`) the structured match fields `versatility` / `fit_niches` / `product_requirements`, which power product→trend matching (`POST /trends/match`) and the versatility badge. Each source has a persistent product/`pipeline_run` (`products.name = 'Trend: <source>'`).

**Keeping cards from going empty.** A blog (and the LLM reading it) can list the same trend under several names, and can rename a trend between fetches; JS-rendered pages (newengen) also render a *random subset* of their trends per fetch (embeds lazy-load), so no single pass is guaranteed complete. Because only one `ugc_items` row exists per `(run, video)`, `ingest-trends` guards against duplicate/renamed formats stealing each other's video: (1) it collapses formats that share an example video before upserting (`_dedupe_formats`); (2) it drops parsed formats with **no example-video link** (FAQ/prose name-drops) before writing, and skips a `render:"js"` fetch that came back with zero videos (`incomplete_render`) so a half-loaded page never writes empties; (3) for videos already scraped in a prior pass it *re-links* the existing `ugc_items` row onto the format the current parse assigns it to (`_relink_existing_videos`); (4) after ingest it prunes only this source's **empty** rows — 0 linked videos after re-link (`_prune_empty_formats`) — which drops rename leftovers while a trend a partial render *missed* keeps its video and survives. This is an **accumulate-and-keep** model: re-running ingest adds the trends each render happened to see, and pruning by emptiness (never by `content_hash`) means a partial render can't delete good trends. Net: no empty/duplicate cards, and each video follows its trend across renames and flaky renders.

| Column | Type | Constraints / default | Notes |
| --- | --- | --- | --- |
| `id` | `uuid` | Primary key, default `gen_random_uuid()` | Row identifier. |
| `run_id` | `uuid` | Not null, references `pipeline_runs(id)` on delete cascade | The source's persistent trends run. |
| `source_name` | `text` | Not null | Trend page key, e.g. `ramdam`, `socialbee`. |
| `source_url` | `text` | Nullable | The page the format was parsed from. |
| `content_hash` | `text` | Nullable | SHA-256 of the fetched page text; an unchanged hash skips re-parsing. |
| `issue_date` | `date` | Nullable | The report month for a monthly source (1st of the month, from a URL like `…/july-tiktok-trends/`, via `issue_date_from_url`); `NULL` for weekly/undated sources. `/trends/formats` defaults to the latest month per source (`_latest_month_per_source`), so last month's trends leave the board once the new report is ingested — without deleting them (`?all_months=true` returns all; undated sources always shown). |
| `format_name` | `text` | Not null | Short name of the format. |
| `format_description` | `text` | Nullable | The trend description as written on the page. |
| `niche_constraint` | `text` | Nullable | Free-form marketing constraint (which niches the format suits); written by `classify-formats`. |
| `versatility` | `text` | Nullable, check `universal`/`broad`/`niche` (migration `027`) | Coarse reuse bucket; drives the badge and the product→trend structured filter. Written by `classify-formats`. |
| `fit_niches` | `text[]` | Nullable (migration `027`) | Product niches the format suits (`{}` = any product). Written by `classify-formats`. |
| `product_requirements` | `text[]` | Nullable (migration `027`) | Concrete attributes a product must show to reuse the format (`{}` = any product); the key signal for whether a product "fits none". Written by `classify-formats`. |
| `ingest_note` | `text` | Nullable (migration `026`) | Why the format has no playable example video (e.g. IG/YT link not scraped, short link unresolved, source listed no link); `NULL` when it has one. Written by `ingest-trends`, shown on the empty card. |
| `niche_constraint_model` | `text` | Nullable | OpenRouter model that wrote the constraint. |
| `classified_at` | `timestamptz` | Nullable | When the constraint was written. |
| `created_at` | `timestamptz` | Not null, default `now()` | First-scrape timestamp; powers the `/trends` "Scraped" date filter (`GET /trends/scrape-dates`, `?scraped_on=`). For **dated (monthly)** sources every format of a report is pinned to the report's earliest `created_at` (`ingest-trends`), so a flaky render that finishes the report on a later pass/day doesn't split one report across two scrape dates. **Weekly** (undated) sources keep true first-seen — a new weekly trend belongs to the week it appears. |

Unique constraint: `unique (source_name, format_name)` (idempotent re-ingest).

### `item_enrichments`

Stores one vision-enrichment row per item, written by `enrich-paid-ads` and `enrich-ugc` from a single OpenRouter (Gemini) vision call. Polymorphic on `(item_type, item_id)` like `item_embeddings` — `item_id` points at `paid_ads.paid_ad_row_id` or `ugc_items.id` with no FK. Holds the LLM transcript, the AI description, and all creative-analysis fields.

| Column | Type | Constraints / default | Notes |
| --- | --- | --- | --- |
| `id` | `uuid` | Primary key, default `gen_random_uuid()` | Enrichment row identifier. |
| `run_id` | `uuid` | Not null, references `pipeline_runs(id)` on delete cascade | Parent run. |
| `item_type` | `text` | Not null, check in (`paid_ad`, `ugc_item`) | Which content table the item lives in. |
| `item_id` | `uuid` | Not null | `paid_ads.paid_ad_row_id` or `ugc_items.id` (no FK — points at one of two tables). |
| `transcript_text` | `text` | Nullable | Spoken transcript text. |
| `transcript_segments` | `jsonb` | Nullable | Segment-level transcript data. |
| `ai_description` | `text` | Nullable | LLM description of the video; core search text. |
| `hook` | `text` | Nullable | Opening line or visual device. |
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
| `product_category` | `text` | Nullable | LLM enrichment: product category. |
| `has_product` | `boolean` | Nullable | LLM enrichment. |
| `has_text_overlay` | `boolean` | Nullable | LLM enrichment. |
| `is_trending_format` | `boolean` | Nullable | LLM enrichment. |
| `persona` | `jsonb` | Nullable | LLM enrichment: the ICP the item targets. |
| `niches` | `jsonb` | Nullable | LLM enrichment: list of niche descriptors. |
| `emotional_drivers` | `jsonb` | Nullable | LLM enrichment: list of persuasion levers. |
| `brand_mentioned` | `jsonb` | Nullable | LLM enrichment: list of brand names spoken or shown. |
| `time_product_was_mentioned` | `numeric` | Nullable | LLM enrichment: seconds until the product first appears or is mentioned. |
| `analysis_model` | `text` | Nullable | OpenRouter model that produced the analysis, e.g. `google/gemini-3-flash-preview`. |
| `analyzed_at` | `timestamptz` | Nullable | When enrichment ran; null means not yet enriched. |
| `created_at` | `timestamptz` | Not null, default `now()` | Creation timestamp. |

Unique constraint on `(item_type, item_id)`.

### `item_embeddings`

Stores one embedding vector per item per embedding space, written by `embed-items` (Voyage AI; migration `013_item_embeddings.sql`, requires the `vector` extension). Items are embedded from their `item_enrichments` row; spaces with no usable text are skipped. Upserts are idempotent on `(item_type, item_id, space, embedding_model)`.

`embed-items` builds two spaces:

- `search` — `ai_description` as core text, followed by a labeled tag block (`content_format`, `main_category`, `content_category`, `product_category`, `video_topic`, `niches`, `hook`, `setting`, `primary_emotion`, `brand_mentioned`), with the full transcript appended.
- `icp` — `persona` + `target_demographic` (reserved for future clustering use).

A third `trend` space (migration `027`, `item_type='viral_format'`, `item_id=viral_formats.id`) is written by `classify-formats`, not `embed-items`: one vector per viral format built by `build_trend_text` (format name/description + `fit_niches` + `product_requirements`). It powers product→trend vector recall (`POST /trends/match` → `match_item_embeddings` with `p_space='trend'`).

| Column | Type | Constraints / default | Notes |
| --- | --- | --- | --- |
| `id` | `uuid` | Primary key, default `gen_random_uuid()` | Embedding row identifier. |
| `run_id` | `uuid` | Not null, references `pipeline_runs(id)` on delete cascade | Parent run. |
| `item_type` | `text` | Not null, check in (`paid_ad`, `ugc_item`, `viral_format`) | Which table the item lives in (`viral_format` = `viral_formats.id`, migration `027`). |
| `item_id` | `uuid` | Not null | `paid_ads.paid_ad_row_id`, `ugc_items.id`, or `viral_formats.id` (no FK — points at one of several tables). |
| `space` | `text` | Not null, check in (`icp`, `search`, `trend`) | Embedding space. Never concatenated across spaces. The DB check allows the legacy values (`icp`, `format`, `hook`, `search`) plus `trend` (migration `027`); `embed-items` writes `icp` + `search`, `classify-formats` writes `trend`. |
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

### `scrape_events`

One row per UI scrape trigger (a click of Scrape / Scrape more for a platform), written by the campaigns API (`api/campaigns.py`, migration `022_scrape_events.sql`). Powers the per-scrape cost shown on the campaigns page. `estimated_cost_usd` is set before the scrape (blended $/item × new items, `costs.py`); `actual_cost_usd` is reconciled after it finishes by summing this run's `api_usage` rows since `started_at` (Apify `usageTotalUsd` + token-priced LLM/embeds). The summed total is the only thing the UI shows — costs are never broken down per provider.

| Column | Type | Constraints / default | Notes |
| --- | --- | --- | --- |
| `id` | `uuid` | Primary key, default `gen_random_uuid()` | Scrape event identifier. |
| `run_id` | `uuid` | Not null, references `pipeline_runs(id)` on delete cascade | Owning run. |
| `platform` | `text` | Not null | `facebook` / `instagram` / `tiktok`. |
| `target_count` | `integer` | Nullable | New total requested for the platform. |
| `items_ingested` | `integer` | Nullable | Rows actually written; filled on completion. |
| `estimated_cost_usd` | `numeric` | Nullable | Pre-scrape estimate. |
| `actual_cost_usd` | `numeric` | Nullable | Reconciled spend; null until the scrape finishes. |
| `status` | `text` | Not null, default `running` | `running` / `done` / `failed`. |
| `error_message` | `text` | Nullable (migration `024_scrape_events_error_message.sql`) | Out-of-credits detail for the UI; null = no billing problem. Detected after the scrape from this run's failed `source_queries` (HTTP 402 or a billing phrase) via `costs.detect_out_of_credits`, so it catches a top-up problem on either the Apify ingest or the LLM enrichment leg — including enrichment credit failures that are swallowed per item and leave the event `done`. Surfaced per-platform by `scrape-stats` as `*_scrape_error`. |
| `started_at` | `timestamptz` | Not null, default `now()` | Scrape start; the lower bound for cost reconciliation. |
| `finished_at` | `timestamptz` | Nullable | Set when the scrape completes. |

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
| `paid_ads_saved_to_supabase_at_idx` | `paid_ads` | `saved_to_supabase_at desc` | Find recently saved paid ads. |
| `ugc_items_run_id_idx` | `ugc_items` | `run_id` | Find organic items for a run. |
| `ugc_items_external_idx` | `ugc_items` | `external_id` | Lookup by provider id. |
| `ugc_items_video_id_idx` | `ugc_items` | `video_id` | Lookup platform video IDs. |
| `ugc_items_virality_idx` | `ugc_items` | `virality_score desc` | Rank organic items by virality. |
| `ugc_items_saved_to_supabase_at_idx` | `ugc_items` | `saved_to_supabase_at desc` | Find recently saved organic items. |
| `item_enrichments_run_idx` | `item_enrichments` | `run_id` | Find enrichments for a run. |
| `item_enrichments_item_idx` | `item_enrichments` | `item_type, item_id` (unique) | Upsert one enrichment per item and look it up by item. |
| `item_embeddings_run_idx` | `item_embeddings` | `run_id` | Find embeddings for a run. |
| `item_embeddings_space_idx` | `item_embeddings` | `item_type, space` | Pull one embedding space per source for clustering. |
| `item_clusters_run_idx` | `item_clusters` | `run_id` | Find cluster assignments for a run. |
| `item_clusters_cluster_idx` | `item_clusters` | `item_type, space, cluster_label` | Find members of a source/space cluster. |
| `clusters_run_idx` | `clusters` | `run_id` | Find cluster summaries for a run. |
| `clusters_lookup_idx` | `clusters` | `item_type, space` | Lookup cluster summaries by source and space. |
| `scrape_events_run_idx` | `scrape_events` | `run_id, started_at desc` | Find a run's scrapes newest-first for the cost history. |
