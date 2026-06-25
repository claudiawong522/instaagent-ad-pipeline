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
- compute the embeddings for each video
      - compute both search + icp embedding
      - reference below to see what search fields take in

for search:
  ┌───────────────────────┬──────────────────┐
  │         Field         │  Source column   │
  ├───────────────────────┼──────────────────┤
  │ AI visual description │ ai_description   │
  ├───────────────────────┼──────────────────┤
  │ format                │ content_format   │
  ├───────────────────────┼──────────────────┤
  │ category              │ main_category    │
  ├───────────────────────┼──────────────────┤
  │ subcategory           │ content_category │
  ├───────────────────────┼──────────────────┤
  │ product               │ product_category │
  ├───────────────────────┼──────────────────┤
  │ topic                 │ video_topic      │
  ├───────────────────────┼──────────────────┤
  │ niches                │ niches           │
  ├───────────────────────┼──────────────────┤
  │ hook                  │ hook             │
  ├───────────────────────┼──────────────────┤
  │ setting               │ setting          │
  ├───────────────────────┼──────────────────┤
  │ emotion               │ primary_emotion  │
  ├───────────────────────┼──────────────────┤
  │ brands                │ brand_mentioned  │
  ├───────────────────────┼──────────────────┤
  │ transcript            │ transcript_text  │
  └───────────────────────┴──────────────────┘

for ICP:
  ┌────────────────────┬────────────────────┐
  │       Field        │   Source column    │
  ├────────────────────┼────────────────────┤
  │ persona            │ persona (jsonb)    │
  ├────────────────────┼────────────────────┤
  │ target demographic │ target_demographic │
  ├────────────────────┼────────────────────┤
  │ tone               │ content_tone       │
  ├────────────────────┼────────────────────┤
  │ visual style       │ visual_style       │
  ├────────────────────┼────────────────────┤
  │ primary emotion    │ primary_emotion    │
  ├────────────────────┼────────────────────┤
  │ target generation  │ target_generation  │
  └────────────────────┴────────────────────

tags for both:
 ┌────────────────┬──────────────────┬────────────────────────────────────────────────────────┐
  │     Filter     │       Type       │                         Values                         │
  ├────────────────┼──────────────────┼────────────────────────────────────────────────────────┤
  │ price tier     │ finite enum      │ budget / mid / premium / luxury                        │
  ├────────────────┼──────────────────┼────────────────────────────────────────────────────────┤
  │ target         │ finite enum      │ gen_z / millennial / gen_x / boomer / mixed            │
  │ generation     │                  │                                                        │
  ├────────────────┼──────────────────┼────────────────────────────────────────────────────────┤
  │ platform       │ finite enum      │ tiktok / instagram / meta                              │
  ├────────────────┼──────────────────┼────────────────────────────────────────────────────────┤
  │ age bracket    │ finite buckets   │ 13–17 / 18–24 / 25–34 / 35–44 / 45–54 / 55+ (bucketed  │
  │                │                  │ from the raw age int)                                  │
  ├────────────────┼──────────────────┼────────────────────────────────────────────────────────┤
  │ language       │ dynamic,         │ derived from data, but snapped to canonical names      │
  │                │ normalized       │                                                        │
  ├────────────────┼──────────────────┼────────────────────────────────────────────────────────┤
  │ views          │ numeric range    │ min/max or slider — no enum                            │
  ├────────────────┼──────────────────┼────────────────────────────────────────────────────────┤
  │ virality       │ numeric range    │ min threshold or slider — no enum                      │
  └────────────────┴──────────────────┴────────────────────────────────────────────────────────┘


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

## search flow
1. user inputs search query
2. search in the search embedding + icp embedding with HNSW, producing about 100 shorlisted videos each
3. combine videos + dedupe same results across both embeddings
4. then we rerank the 200ish videos
5. get actual data(we only have scores now), apply filters, dedupe same video different entry
6. return the rest