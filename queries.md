# Queries

## Find Keyword Used For A UGC Item

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
