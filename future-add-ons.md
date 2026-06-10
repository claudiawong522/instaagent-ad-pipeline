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

## Account-Size-Normalized UGC Virality

- Normalize UGC performance by creator follower count or historical baseline.
- Useful once source data quality around follower counts is confirmed.

## Human Review UI

- Add approval/rejection, notes, cluster renaming, customer fit tags, and final sales-pack curation.

## Creative Cloning Packs

- Generate scripts, shot lists, asset requirements, creator directions, and prompt-ready clone specs from selected winners.

## Automated Keyword Expansion

- Use LLM/category research to generate provider-specific keyword variants, competitor terms, ingredient terms, pain-point terms, and adjacent category terms.
- Keep exact product phrases in run context, then automatically choose broader provider API inputs such as `gentle cleanser` for Foreplay and `cleanser`/`skincare` for TopYappers viral-content when exact brand terms are too sparse.

## Visual Analysis

- Add OCR, frame sampling, scene detection, visual style embeddings, product-shot detection, and before/after detection.

## Compliance/IP Review

- Flag risky medical/beauty claims, direct competitor copying, creator likeness reuse, trademark risk, and platform policy issues.
