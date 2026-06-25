# Queries

## Find Keyword Used For An Organic Item

Use `ugc_items.raw_payload_id -> raw_payloads.source_query_id -> source_queries.request_params`.

```sql
select
  ui.id as ugc_item_id,
  ui.external_id,
  sq.provider,
  sq.endpoint,
  coalesce(
    sq.request_params ->> 'videoTopicContains',
    sq.request_params ->> 'textSearch',
    sq.request_params ->> 'query'
  ) as keyword_used,
  k.id as keyword_id,
  k.target_ugc_count,
  k.target_paid_count
from ugc_items ui
join raw_payloads rp on rp.id = ui.raw_payload_id
join source_queries sq on sq.id = rp.source_query_id
left join keywords k
  on k.run_id = ui.run_id
  and k.keyword_text = coalesce(
    sq.request_params ->> 'videoTopicContains',
    sq.request_params ->> 'textSearch',
    sq.request_params ->> 'query'
  )
where ui.id = '<UGC_ITEM_UUID>';
```

## Find Keyword Used For A Paid Ad

Use `paid_ads.raw_payload_id -> raw_payloads.source_query_id -> source_queries.request_params`.

```sql
select
  pa.paid_ad_row_id,
  pa.id as meta_ad_archive_id,
  sq.provider,
  sq.endpoint,
  coalesce(
    sq.request_params ->> 'keyword',
    sq.request_params #>> '{actor_input,startUrls,0,url}'
  ) as keyword_or_input_url,
  k.id as keyword_id,
  k.target_paid_count,
  k.target_ugc_count
from paid_ads pa
join raw_payloads rp on rp.id = pa.raw_payload_id
join source_queries sq on sq.id = rp.source_query_id
left join keywords k
  on k.run_id = pa.run_id
  and k.keyword_text = sq.request_params ->> 'keyword'
where pa.paid_ad_row_id = '<PAID_AD_ROW_UUID>';
```

If you mean Meta's ad archive ID instead of the Supabase row UUID:

```sql
where pa.id = '<META_AD_ARCHIVE_ID>';
```

## Find The Most Similar Videos Across Paid Ads And Organic

`item_embeddings` stores one pgvector row per item per space (`icp`/`search`). The `search` space embeds `ai_description` + tags + full transcript. `<=>` is cosine distance (smaller = more similar).

```sql
select
  a.item_type as type_a,
  b.item_type as type_b,
  a.source_text as content_a,
  b.source_text as content_b,
  a.embedding <=> b.embedding as cosine_distance
from item_embeddings a
join item_embeddings b
  on b.space = a.space
  and b.embedding_model = a.embedding_model
  and b.id > a.id
where a.run_id = '<RUN_UUID>'
  and b.run_id = '<RUN_UUID>'
  and a.space = 'search'
order by cosine_distance asc
limit 10;
```

## Find Items Missing Embeddings For A Run

Spaces are skipped when an item has no usable text, so missing rows are expected for sparse metadata; this shows what got skipped.

```sql
select pa.paid_ad_row_id as item_id, 'paid_ad' as item_type, s.space
from paid_ads pa
cross join (values ('icp'), ('search')) as s(space)
left join item_embeddings ie
  on ie.item_type = 'paid_ad' and ie.item_id = pa.paid_ad_row_id and ie.space = s.space
where pa.run_id = '<RUN_UUID>' and ie.id is null

union all

select ui.id, 'ugc_item', s.space
from ugc_items ui
cross join (values ('icp'), ('search')) as s(space)
left join item_embeddings ie
  on ie.item_type = 'ugc_item' and ie.item_id = ui.id and ie.space = s.space
where ui.run_id = '<RUN_UUID>' and ie.id is null;
```
