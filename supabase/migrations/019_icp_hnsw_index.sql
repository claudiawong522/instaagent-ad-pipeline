-- Search speed: the search path (api/search.py) runs match_item_embeddings over BOTH
-- the 'search' and 'icp' spaces, but only 'search' had an HNSW index (migrations/015).
-- The 'icp' query therefore fell back to a full sequential scan — O(N) per search,
-- which becomes seconds of latency as the corpus grows toward 100k+ items.
--
-- This adds the matching partial HNSW index for 'icp', so both space queries are
-- sub-linear. Mirrors the 'search' index in 015.
--
-- Run in the Supabase SQL editor after 018. CONCURRENTLY avoids locking the table
-- during the build (which can take minutes on a large corpus); it cannot run inside a
-- transaction block, so execute this statement on its own.
create index concurrently if not exists item_embeddings_icp_hnsw
  on item_embeddings using hnsw (embedding vector_cosine_ops)
  where space = 'icp';
