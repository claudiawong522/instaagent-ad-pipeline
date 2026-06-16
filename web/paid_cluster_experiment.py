#!/usr/bin/env python3
"""EXPERIMENT (read-only, no DB writes): how would paid ads segment into
finer clusters? Forces k=6 with KMeans and characterizes each segment by its
items' niches/hooks; also sweeps HDBSCAN min_cluster_size to show how the
natural cluster count grows as you shrink it.

Run:  python web/paid_cluster_experiment.py   (RUN_ID=<uuid> to override)
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from sklearn.cluster import HDBSCAN, KMeans  # noqa: E402
from sklearn.manifold import TSNE  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
PNG_PATH = ROOT / "web" / "paid_experiment.png"
K = 6


def load_env():
    env = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    raw = os.environ.get("SUPABASE_URL") or env.get("SUPABASE_URL")
    key = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
           or env.get("SUPABASE_SERVICE_ROLE_KEY") or env.get("SUPABASE_ANON_KEY"))
    if not raw or not key:
        sys.exit("SUPABASE_URL and a Supabase key required.")
    return re.sub(r"/rest/v1/?$", "", raw).rstrip("/"), key


def fetch(base, key, path, params):
    url = f"{base}/rest/v1/{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"apikey": key, "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310
        return json.loads(r.read().decode())


def resolve_run(base, key):
    if os.environ.get("RUN_ID"):
        return os.environ["RUN_ID"]
    rows = fetch(base, key, "clusters", {"space": "eq.icp", "select": "run_id,created_at",
                                         "order": "created_at.desc", "limit": "1"})
    if not rows:
        sys.exit("No ICP clusters found.")
    return rows[0]["run_id"]


def l2(m):
    n = np.linalg.norm(m, axis=1, keepdims=True)
    n[n == 0] = 1.0
    return m / n


def main():
    base, key = load_env()
    run_id = resolve_run(base, key)
    print(f"run_id: {run_id}\n")

    emb = fetch(base, key, "item_embeddings", {
        "run_id": f"eq.{run_id}", "item_type": "eq.paid_ad", "space": "eq.icp",
        "select": "item_id,embedding",
    })
    ids = [e["item_id"] for e in emb]
    X = l2(np.asarray([json.loads(e["embedding"]) for e in emb], dtype=float))
    print(f"{len(X)} paid-ad ICP embeddings loaded.\n")

    meta_rows = fetch(base, key, "paid_ads", {
        "paid_ad_row_id": f"in.({','.join(ids)})",
        "select": "paid_ad_row_id,name,niches,hook,video_topic",
    })
    meta = {r["paid_ad_row_id"]: r for r in meta_rows}

    # --- HDBSCAN sweep: how the natural cluster count changes with granularity ---
    print("HDBSCAN min_cluster_size sweep (current pipeline default = 5):")
    for mcs in [2, 3, 4, 5]:
        labels = HDBSCAN(min_cluster_size=mcs).fit_predict(X)
        ncl = len({l for l in labels if l != -1})
        noise = int((labels == -1).sum())
        print(f"  min_cluster_size={mcs}: {ncl} clusters, {noise} noise")
    print()

    # --- Forced k=6 with KMeans ---
    km = KMeans(n_clusters=K, random_state=42, n_init=10).fit(X)
    labels = km.labels_
    print(f"=== KMeans k={K} segmentation ===")
    order = [c for c, _ in Counter(labels.tolist()).most_common()]
    for ci in order:
        m = labels == ci
        items = [meta.get(ids[j], {}) for j in range(len(ids)) if m[j]]
        niche_counts = Counter(n for it in items for n in (it.get("niches") or []))
        top_niches = ", ".join(f"{n}×{c}" for n, c in niche_counts.most_common(6))
        topics = Counter(it.get("video_topic") or "" for it in items)
        examples = [it.get("name") or "?" for it in items][:5]
        print(f"\nCluster {ci}  (n={int(m.sum())})")
        print(f"  top niches : {top_niches or '—'}")
        print(f"  brands     : {', '.join(sorted({e for e in examples}))[:90]}")
        # one representative hook
        hooks = [it.get("hook") for it in items if it.get("hook")]
        if hooks:
            print(f"  e.g. hook  : {hooks[0][:110]}")

    # --- Plot ---
    perp = max(2, min(30, (len(X) - 1) // 3))
    xy = TSNE(n_components=2, perplexity=perp, init="pca",
              learning_rate="auto", random_state=42).fit_transform(X)
    palette = ["#ef7b65", "#4f86c6", "#5fb37a", "#c084fc", "#e8a23d", "#e76f9e"]
    fig, ax = plt.subplots(figsize=(9, 7))
    for ci in range(K):
        m = labels == ci
        ax.scatter(xy[m, 0], xy[m, 1], s=60, alpha=0.85, color=palette[ci % len(palette)],
                   label=f"seg {ci} (n={int(m.sum())})", edgecolors="white", linewidths=0.6)
    ax.set_title(f"Paid ads — KMeans k={K} (experiment) · run {run_id[:8]}",
                 fontsize=13, fontweight="bold")
    ax.set_xticks([]); ax.set_yticks([])
    ax.legend(fontsize=9, loc="best")
    fig.tight_layout()
    fig.savefig(PNG_PATH, dpi=130)
    print(f"\nWrote {PNG_PATH}")


if __name__ == "__main__":
    main()
