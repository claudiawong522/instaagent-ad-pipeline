<div align="center">

# 🎯 InstaAgent

### Find the ads that actually work — before you spend a dollar.

InstaAgent studies the ads and videos already winning in your market, then hands you the patterns worth copying.

![Self-hosted](https://img.shields.io/badge/self--hosted-bring%20your%20own%20DB-brightgreen?style=for-the-badge)
![For](https://img.shields.io/badge/for-marketers%20%26%20founders-blue?style=for-the-badge)
![Powered by](https://img.shields.io/badge/powered%20by-AI-8b5cf6?style=for-the-badge)

**Run your own instance** — on your Supabase and your API keys. No shared or hosted database; your data stays yours.

</div>

---

## 💡 Why use it

Launching a product? Don't guess what creative will land. InstaAgent finds what's **already working** for your competitors and shows you why.

- 🔍 **See the winners** — the paid ads and organic videos pulling attention in your niche, including which ones have run the longest (the real sign an ad is profitable).
- 🎬 **Understand the hook** — every video is watched and broken down for you: the message, the format, the angle.
- 🧩 **Spot the patterns** — similar creative is grouped together, so themes that keep winning jump out.
- 🔥 **Ride the trends** — a daily feed of viral video *formats* pulled from the top trend trackers.
- 🖥️ **Browse it all** — a clean dashboard to search, explore, and get inspired.

## ✨ How it works

```
   🕵️  Find          🎬  Analyze          🧩  Group          📊  Explore
competitor ads   →   watch &        →   cluster by     →   in your
& viral video        break down          audience           dashboard
```

You give it your product and market. It does the rest.

## 🚀 Get started

```bash
# 1. Install
python3 -m pip install -e .

# 2. Add your keys — copy the example file and fill it in
cp .env.example .env

# 3. Set up your database (paste supabase/schema.sql into Supabase)

# 4. Tell it about your product, then let it work
PYTHONPATH=src python3 -m instaagent_pipeline.cli init-run \
  --product-name "QE cleanser" --category "skincare" \
  --target-market "US skincare buyers" \
  --campaign-guidelines "Competitor ads for a gentle cleanser launch." \
  --target-paid-count 1000 --target-organic-count 2500

PYTHONPATH=src python3 -m instaagent_pipeline.cli ingest-apify-ads --run-id "<run_id>"
PYTHONPATH=src python3 -m instaagent_pipeline.cli ingest-tiktok    --run-id "<run_id>"
```

That's it — the videos get analyzed automatically, and your results show up in the dashboard. Add `--dry-run` to any step to preview without saving.

## 🔑 What you'll need

A few free/low-cost accounts to plug in (keys go in your `.env` file):

| Service | What it's for |
|---------|---------------|
| **Supabase** | Stores your results |
| **Apify** | Pulls the ads and videos |
| **OpenRouter** · **Claude** · **Voyage** | The AI that watches and understands each video |

> 🔒 Your keys stay in `.env`, which is never committed. Keep them private.

## 🌍 Deploy your own dashboard

InstaAgent is **fully self-hosted** — three pieces, all yours, wired only to each other. Nothing points at a shared instance.

1. **Database** — your Supabase project (paste `supabase/schema.sql` once).
2. **Backend API** — the service that reads and writes *your* DB. Run it anywhere that hosts Python (Render, Railway, Fly, a VM):
   ```bash
   PYTHONPATH=src uvicorn instaagent_pipeline.api.app:app --port 8000
   ```
   It uses the service-role key from your `.env` — keep it server-side only, never in the frontend.
3. **Dashboard** — deploy `frontend/` to your own Vercel. Set one env var so the UI talks to *your* backend:
   ```
   NEXT_PUBLIC_API_URL=https://your-backend-url
   ```

The dashboard never touches Supabase directly — it only reads through your backend, so your data never leaves your own stack.

## 📚 Going deeper

Building on top of it? See **`AGENTS.md`** (how it's structured), **`database.md`** (the data), and **`frontend/`** (the dashboard app).

<div align="center">

Made for marketers who'd rather copy a proven winner than gamble on a hunch. 💸

</div>
