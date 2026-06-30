#!/usr/bin/env bash
# Scrape-safe API launch: NO --reload.
#
# uvicorn's --reload restarts the server whenever a .py file changes, which kills
# any in-flight scrape worker thread mid-enrichment (the event stays stuck at
# "running", its items stuck at "processing", until the next startup's auto-resume
# limps it back). A long scrape must NOT run under a hot-reloading server.
#
# Use this to run the backend while scraping. Backend code edits won't take effect
# until you stop (Ctrl-C) and re-run this — that's the price of not interrupting scrapes.
# Only add --reload manually for quick backend iteration when nothing is scraping.
set -euo pipefail
exec uvicorn instaagent_pipeline.api.app:app --port "${PORT:-8000}"
