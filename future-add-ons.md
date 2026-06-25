# Future Add-Ons

These are good ideas intentionally deferred to keep the first version lean.

## Competitor Mode

- Use Meta Ad Library page URLs or page IDs with Apify `apify/facebook-ads-scraper` to pull ads for known competitor brands.
- Useful for customer-specific competitor research.
- Deferred because the first version should prove the keyword-led category workflow first.

## Transcription Optimizations

- If the broader Apify transcript actor has poor Instagram reliability or cost, compare Apify `apple_yang/instagram-transcripts-scraper` as an Instagram-only alternative. It accepts one public Instagram video URL and returns `text` plus timestamped `segments`.
- If Apify confirms array input is stable for `tictechid/anoxvanzi-transcriber`, batch multiple known URLs into one actor run to reduce per-run base charges.

## Account-Size-Normalized Organic Virality

- Normalize organic performance by creator follower count or historical baseline.
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

## Static Image Ads

- The Meta Ad Library scrape URL currently hard-codes `media_type=video` (`apify_ads.py`), so photo-only ads never enter the pipeline.
- To include them: parameterize `media_type` (CLI `--media-type`, default `all`), and extend `enrich-paid-ads` to send the ad image + caption through the same OpenRouter descriptor schema when there is no video (transcript fields null).
- Embeddings need no changes — `embed-items` works off descriptor columns regardless of media type, and same-schema distillation keeps image and video ads clustering by creative pattern instead of input modality.
- Deferred because every scraped ad so far is a video ad and InstaAgent clones video creatives first.

