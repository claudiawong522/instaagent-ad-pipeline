-- Step 6 (clustering): groups item_embeddings rows into clusters per source,
-- created by the cluster-items command via HDBSCAN over the icp embedding space.
-- Two tables: item_clusters (one row per item = the assignment) and clusters
-- (one row per discovered cluster = label/centroid/metrics). Kept separate from
-- item_embeddings so items can be re-clustered with different params without
-- touching the embeddings. Only space = 'icp' is populated for now; the column is
-- retained for parity with item_embeddings and to add spaces later.

create extension if not exists vector;

create table if not exists item_clusters (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references pipeline_runs(id) on delete cascade,
  item_type text not null check (item_type in ('paid_ad', 'ugc_item')),
  item_id uuid not null,
  space text not null check (space in ('icp', 'format', 'hook')),
  cluster_label integer not null,
  distance_to_centroid double precision,
  clustering_params text not null,
  created_at timestamptz not null default now(),
  unique (item_type, item_id, space)
);

create index if not exists item_clusters_run_idx on item_clusters(run_id);
create index if not exists item_clusters_cluster_idx on item_clusters(item_type, space, cluster_label);

create table if not exists clusters (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references pipeline_runs(id) on delete cascade,
  item_type text not null check (item_type in ('paid_ad', 'ugc_item')),
  space text not null check (space in ('icp', 'format', 'hook')),
  cluster_label integer not null,
  name text,
  label_json jsonb,
  label_text text,
  centroid vector(1024),
  member_count integer not null,
  exemplar_item_ids jsonb,
  silhouette double precision,
  label_model text,
  clustering_params text not null,
  created_at timestamptz not null default now(),
  unique (run_id, item_type, space, cluster_label)
);

create index if not exists clusters_run_idx on clusters(run_id);
create index if not exists clusters_lookup_idx on clusters(item_type, space);
