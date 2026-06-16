#!/usr/bin/env python3
"""Visualize the ICP embedding space and its HDBSCAN clusters.

Pulls item_embeddings (space=icp) + item_clusters for the latest run,
projects the 1024-d vectors to 2D with t-SNE, and writes:
  web/embeddings.png   — static two-panel scatter (paid ads | UGC)
  web/embeddings.html  — interactive Plotly version (hover = item + cluster)

Run:  python web/embed_viz.py   (RUN_ID=<uuid> to override)
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from sklearn.manifold import TSNE  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
PNG_PATH = ROOT / "web" / "embeddings.png"
HTML_PATH = ROOT / "web" / "embeddings.html"


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


def tsne_2d(vectors: np.ndarray) -> np.ndarray:
    n = len(vectors)
    if n < 3:
        # too few points to project; lay them on a line
        return np.column_stack([np.arange(n), np.zeros(n)]).astype(float)
    perp = max(2, min(30, (n - 1) // 3))
    ts = TSNE(n_components=2, perplexity=perp, init="pca",
              learning_rate="auto", random_state=42)
    return ts.fit_transform(vectors)


def collect(base, key, run_id, item_type, table, pk, name_field):
    emb = fetch(base, key, "item_embeddings", {
        "run_id": f"eq.{run_id}", "item_type": f"eq.{item_type}", "space": "eq.icp",
        "select": "item_id,embedding",
    })
    clusters = fetch(base, key, "item_clusters", {
        "run_id": f"eq.{run_id}", "item_type": f"eq.{item_type}", "space": "eq.icp",
        "select": "item_id,cluster_label",
    })
    label_of = {c["item_id"]: c["cluster_label"] for c in clusters}
    names = fetch(base, key, "clusters", {
        "run_id": f"eq.{run_id}", "item_type": f"eq.{item_type}", "space": "eq.icp",
        "select": "cluster_label,name,member_count",
    })
    cname = {c["cluster_label"]: (c.get("name") or "") for c in names}
    csize = {c["cluster_label"]: c.get("member_count") for c in names}

    ids = [e["item_id"] for e in emb]
    items = {}
    if ids:
        rows = fetch(base, key, table, {pk: f"in.({','.join(ids)})",
                                        "select": f"{pk},{name_field}"})
        items = {r[pk]: (r.get(name_field) or "") for r in rows}

    vecs, labels, hovers = [], [], []
    for e in emb:
        vecs.append(json.loads(e["embedding"]))
        lab = label_of.get(e["item_id"], -1)
        labels.append(lab)
        hovers.append(items.get(e["item_id"], e["item_id"][:8]))
    return {
        "X": np.asarray(vecs, dtype=float) if vecs else np.empty((0, 1024)),
        "labels": np.asarray(labels, dtype=int) if labels else np.empty(0, int),
        "hovers": hovers, "cname": cname, "csize": csize,
    }


PALETTE = ["#ef7b65", "#4f86c6", "#5fb37a", "#c084fc", "#e8a23d",
           "#e76f9e", "#3bb9bf", "#9a8c98", "#8bc34a", "#ff8a65"]


def project(d):
    if len(d["X"]):
        d["xy"] = tsne_2d(d["X"])
    else:
        d["xy"] = np.empty((0, 2))
    return d


def real_clusters(d):
    return sorted(int(l) for l in set(d["labels"].tolist()) if l != -1)


def draw_png(paid, ugc, run_id):
    fig, axes = plt.subplots(1, 2, figsize=(15, 6.5))
    for ax, (title, d) in zip(axes, [("Paid Ads", paid), ("UGC", ugc)]):
        rc = real_clusters(d)
        for i, lab in enumerate(rc):
            m = d["labels"] == lab
            nm = (d["cname"].get(lab, "") or f"cluster {lab}")
            nm = nm[:34] + "…" if len(nm) > 34 else nm
            ax.scatter(d["xy"][m, 0], d["xy"][m, 1], s=55, alpha=0.85,
                       color=PALETTE[i % len(PALETTE)],
                       label=f"{lab}: {nm} (n={int(m.sum())})")
        noise = d["labels"] == -1
        if noise.any():
            ax.scatter(d["xy"][noise, 0], d["xy"][noise, 1], s=30, alpha=0.5,
                       marker="x", color="#b0b0b0", label=f"noise (n={int(noise.sum())})")
        ax.set_title(f"{title} — {len(d['X'])} items, {len(rc)} clusters",
                     fontsize=13, fontweight="bold")
        ax.set_xticks([]); ax.set_yticks([])
        ax.legend(fontsize=7, loc="upper left", framealpha=0.9)
    fig.suptitle(f"ICP embedding space (t-SNE 2D) · run {run_id[:8]}",
                 fontsize=15, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(PNG_PATH, dpi=130)
    print(f"Wrote {PNG_PATH}")


def panel_traces(d):
    traces = []
    for i, lab in enumerate(real_clusters(d)):
        m = d["labels"] == lab
        nm = d["cname"].get(lab, "") or f"cluster {lab}"
        traces.append({
            "x": d["xy"][m, 0].tolist(), "y": d["xy"][m, 1].tolist(),
            "mode": "markers", "type": "scatter",
            "name": f"{lab}: {nm[:38]}",
            "marker": {"size": 10, "color": PALETTE[i % len(PALETTE)],
                       "line": {"width": 1, "color": "#fff"}},
            "text": [d["hovers"][j] for j in range(len(d["labels"])) if m[j]],
            "hovertemplate": "%{text}<br>" + nm[:60] + "<extra></extra>",
        })
    noise = d["labels"] == -1
    if noise.any():
        traces.append({
            "x": d["xy"][noise, 0].tolist(), "y": d["xy"][noise, 1].tolist(),
            "mode": "markers", "type": "scatter", "name": "noise",
            "marker": {"size": 7, "color": "#b0b0b0", "symbol": "x"},
            "text": [d["hovers"][j] for j in range(len(d["labels"])) if noise[j]],
            "hovertemplate": "%{text}<br>(unclustered)<extra></extra>",
        })
    return traces


def draw_html(paid, ugc, run_id):
    blocks = [
        ("UGC", ugc, len(real_clusters(ugc))),
        ("Paid Ads", paid, len(real_clusters(paid))),
    ]
    divs, scripts = [], []
    for k, (title, d, ncl) in enumerate(blocks):
        did = f"plot{k}"
        divs.append(
            f'<h2>{title} — {len(d["X"])} items, {ncl} visible cluster(s)</h2>'
            f'<div id="{did}" class="plot"></div>')
        scripts.append(
            f'Plotly.newPlot("{did}", {json.dumps(panel_traces(d))}, '
            f'{{margin:{{t:10}},height:480,legend:{{font:{{size:11}}}},'
            f'xaxis:{{visible:false}},yaxis:{{visible:false}},'
            f'hovermode:"closest"}}, {{displayModeBar:false,responsive:true}});')
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>ICP embeddings · {run_id[:8]}</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
 body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:0;padding:28px 36px;
   background:#f4f4f5;color:#1c1c1e}}
 h1{{font-size:26px;margin:0 0 4px}} .sub{{color:#6b7280;margin-bottom:24px}}
 h2{{font-size:16px;margin:26px 0 6px}} .plot{{background:#fff;border:1px solid #e7e7ea;
   border-radius:14px;padding:8px}}
 a{{color:#ef7b65}}
</style></head><body>
<h1>ICP embedding space</h1>
<div class="sub">t-SNE projection of 1024-d Voyage embeddings · run {run_id[:8]} ·
 each point = one item, colored by HDBSCAN cluster · grey ✕ = unclustered (noise).
 <a href="strategy.html">← back to Strategy</a></div>
{''.join(divs)}
<script>{''.join(scripts)}</script>
</body></html>"""
    HTML_PATH.write_text(html)
    print(f"Wrote {HTML_PATH}")


def main():
    base, key = load_env()
    run_id = resolve_run(base, key)
    print(f"run_id: {run_id}")
    paid = project(collect(base, key, run_id, "paid_ad", "paid_ads", "paid_ad_row_id", "name"))
    ugc = project(collect(base, key, run_id, "ugc_item", "ugc_items", "id", "handle"))
    for nm, d in [("Paid Ads", paid), ("UGC", ugc)]:
        print(f"{nm}: {len(d['X'])} items, {len(real_clusters(d))} clusters, "
              f"{int((d['labels'] == -1).sum())} noise")
    draw_png(paid, ugc, run_id)
    draw_html(paid, ugc, run_id)


if __name__ == "__main__":
    main()
