-- Add a relevance floor to the search-space KNN.
--
-- match_item_embeddings was a pure K-nearest-neighbour lookup: it always returned
-- p_limit rows ordered by cosine distance, no matter how far away they were. For a
-- query with no real match in the corpus (e.g. "watermelon" against a skincare-only
-- corpus) that meant 15-20 wholly unrelated results. Measured cosine similarities
-- show a clean separation: genuine matches sit at ~0.50+ while noise clusters at
-- ~0.25-0.28, so we add an optional p_min_similarity cutoff (default 0.0 keeps the
-- old behaviour for any caller that does not pass it).
--
-- Adding a parameter changes the function signature, so `create or replace` would
-- leave the previous 6-arg overload in place and PostgREST would 300 (ambiguous).
-- Drop the old signature first so only the new function remains.

drop function if exists match_item_embeddings(vector, text, text, text, uuid, int);

create or replace function match_item_embeddings(
  p_query vector(1024),
  p_space text default 'search',
  p_item_type text default null,
  p_model text default 'voyage-4-lite',
  p_run_id uuid default null,
  p_limit int default 20,
  p_min_similarity double precision default 0.0
)
returns table (
  item_type text,
  item_id uuid,
  source_text text,
  similarity double precision
)
language sql
stable
as $$
  select
    ie.item_type,
    ie.item_id,
    ie.source_text,
    1 - (ie.embedding <=> p_query) as similarity
  from item_embeddings ie
  where ie.space = p_space
    and ie.embedding_model = p_model
    and (p_item_type is null or ie.item_type = p_item_type)
    and (p_run_id is null or ie.run_id = p_run_id)
    and (1 - (ie.embedding <=> p_query)) >= p_min_similarity
  order by ie.embedding <=> p_query
  limit p_limit;
$$;
