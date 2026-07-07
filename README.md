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

InstaAgent is **fully self-hosted** — your database, your keys, one deploy. The dashboard and its backend API live in a **single Vercel project**: the Next.js UI plus the Python pipeline running as serverless functions. No separate server to run.

1. **Database** — your Supabase project (paste `supabase/schema.sql` once).
2. **Deploy** — import this repo into Vercel. Add your Supabase + provider keys as project **Environment Variables**. The service-role key stays server-side — it's never prefixed `NEXT_PUBLIC_`, so it can't reach the browser. Vercel builds the UI and the `/api` functions together.
3. **Auto-deploy** — every push to `main` ships production via GitHub Actions (`.github/workflows/deploy-vercel.yml`); set the `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID`, and `VERCEL_TOKEN` repo secrets.

The dashboard never touches Supabase directly — the browser calls the same-origin `/api`, which reads through your backend, so your data never leaves your own stack.

**Local dev** runs the two pieces as separate processes (Next's dev server can't run the Python functions):
```bash
PYTHONPATH=src uvicorn instaagent_pipeline.api.app:app --port 8000   # backend
npm run dev                                                          # dashboard → http://localhost:3000
```
with `NEXT_PUBLIC_API_URL=http://localhost:8000` in `.env.local` (in production it's unset and the UI uses same-origin `/api`).

## 📚 Going deeper

Building on top of it? See **`AGENTS.md`** (how it's structured), **`database.md`** (the data), and the dashboard app at the repo root (**`app/`**, **`components/`**, **`lib/`**).

<div align="center">

Made for marketers who'd rather copy a proven winner than gamble on a hunch. 💸

</div>
