## Dataflow Handwritten
- user inputs campaign detials + intended ad count + ugc count
- llm takes this info and generates keywords + target count pairs
- apify scraping for all
      - scrapes apify for paid ads (contains identity, creative, run duration)
      - scrapes apify for ugc tiktoks (has all required metadata, no llm analysis)
      - scrapes apify for ugc reels (has all required metadata, no llm analysis, but follower count often missing, thus backfilled)
      - apify backfills follower count for ugc 
      - scraped raw videos are in raw_payloads table
      - data is also inputted into paid_ads table
- download all videos
      - api returns expiring urls, but we need to render video live, thus we need our own copy of the video
      - we first download the video into RAM
      - then we upload this video into supabase storage, which is just bytes (not the database)
      - then this returns a url that points to the video in storage
      - this url is saved in the database (column: storage_video_url)
      - this kills 2 birds in 1 stone because to feed a video into openrouter later, you also need base64, which needs to be encoded from raw bytes from RAM too (not supabase storage currently)
- feed all videos (ads, reels, tiktoks) into llm (Openrouter Gemini 3 Flash)
      - checks video url isn't null, and no non-video links
      - for ads, since there's built in analysis, this is also fed into the llm
      - llm returns a JSON object with all fields below
      - the JSON object is filled into the paid_ad_enrichments table
- compute the search embedding for each video
      - reference below to see what search fields take in

for search:
┌──────────────────┬─────────────────────────────────┐
  │      Field       │              Role               │
  ├──────────────────┼─────────────────────────────────┤
  │ ai_description   │ core search text                │
  ├──────────────────┼─────────────────────────────────┤
  │ transcript_text  │ spoken content (append, capped) │
  ├──────────────────┼─────────────────────────────────┤
  │ hook             │ tag                             │
  ├──────────────────┼─────────────────────────────────┤
  │ content_format   │ tag (asmr, before_after, demo…) │
  ├──────────────────┼─────────────────────────────────┤
  │ main_category    │ tag                             │
  ├──────────────────┼─────────────────────────────────┤
  │ content_category │ tag                             │
  ├──────────────────┼─────────────────────────────────┤
  │ product_category │ tag                             │
  ├──────────────────┼─────────────────────────────────┤
  │ video_topic      │ tag                             │
  ├──────────────────┼─────────────────────────────────┤
  │ niches           │ tag                             │
  ├──────────────────┼─────────────────────────────────┤
  │ setting          │ tag                             │
  ├──────────────────┼─────────────────────────────────┤
  │ primary_emotion  │ tag                             │
  ├──────────────────┼─────────────────────────────────┤
  │ brand_mentioned  │ tag                             │
  └──────────────────┴────────────────────────────────

for ICP:
┌────────────────────┬──────────────────────────────────────┐
  │       Field        │                 Role                 │
  ├────────────────────┼──────────────────────────────────────┤
  │ persona            │ primary ICP signal                   │
  ├────────────────────┼──────────────────────────────────────┤
  │ target_demographic │ audience descriptor                  │
  ├────────────────────┼──────────────────────────────────────┤
  │ emotional_drivers  │ audience motivation                  │
  ├────────────────────┼──────────────────────────────────────┤
  │ niches             │ shared with search; audience segment │
  └────────────────────┴──────────────────────────────────────┘


## inputs and outputs to all apis
 1. Keyword Gen - Claude API
     Input: campaign details + intended ad count + ugc count
     Output: generates keywords + target count pairs
  2. Apify Meta Ads
     Input: keyword (searched unordered in Meta Ad Library, video only)
     Output: ad items — video URL (expires), thumbnail, headline, description, page name (who's page owns the ad), call to action, adArchiveID
  3. Apify UGC (TikTok + Instagram)
     Input: keyword
     Output: video URL (expires), cover, handle, view/like counts, follower count, hashtags
  4. Video Enrichment - OpenRouter → Gemini (gemini-3-flash-preview)
     Input: video (base64) + ad copy context
     Output: transcript + segments, ai_description, hook, content_format, emotion, product_category,
  niches, has_product, etc.
  5. Embeddings - Voyage (voyage-4-lite)
     Input: check table
     Output: embedding vector

