# Future Add-Ons

These are good ideas intentionally deferred to keep the first version lean.

## Competitor Mode

- Use Foreplay `GET /api/spyder/brand/ads` or brand/domain lookup first, then pull brand ads.
- Useful for customer-specific competitor research.
- Deferred because the first version should prove the keyword-led category workflow first.

## Apify Fallback

- Use Apify `data-slayer/instagram-search-reels` when TopYappers does not return enough relevant keyword results.
- Benefits: arbitrary Instagram Reels keyword search, captions, hashtags, creator metadata, engagement metrics, audio metadata, and video URLs.
- Tradeoff: the actor is not transcript-native, so a separate transcription step is needed.
- For known Instagram URLs that TopYappers saved without `subtitles`, evaluate Apify `apple_yang/instagram-transcripts-scraper` as a transcript-only fallback. It accepts one public Instagram video URL and returns `text` plus timestamped `segments`; store successful output in `ugc_transcripts`, not `ugc_items.subtitles`.
- For a broader known-URL transcript fallback, evaluate Apify `tictechid/anoxvanzi-transcriber`. It accepts `start_urls` for public Instagram, TikTok, YouTube Shorts, and Facebook videos, then returns `transcript`, `detected_language`, duration, status, and errors; this can cover non-Instagram TopYappers rows.

## Account-Size-Normalized UGC Virality

- Normalize UGC performance by creator follower count or historical baseline.
- Useful once source data quality around follower counts is confirmed.

## Human Review UI

- Add approval/rejection, notes, cluster renaming, customer fit tags, and final sales-pack curation.

## Creative Cloning Packs

- Generate scripts, shot lists, asset requirements, creator directions, and prompt-ready clone specs from selected winners.

## Keyword Quality Tuning

- Add keyword approval, rejection, regeneration, and per-provider keyword variants.
- Add competitor/domain lookup when exact brand or competitor terms matter.

## Visual Analysis

- Add OCR, frame sampling, scene detection, visual style embeddings, product-shot detection, and before/after detection.

## Compliance/IP Review

- Flag risky medical/beauty claims, direct competitor copying, creator likeness reuse, trademark risk, and platform policy issues.
