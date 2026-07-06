## Dataflow Handwritten

## How does database get populated?
- user inputs campaign detials + intended ad count + organic count
- llm takes this info and generates keywords + target count pairs
- apify scraping for all
      - scrapes apify for paid ads (contains identity, creative, run duration)
      - scrapes apify for organic tiktoks (has all required metadata, no llm analysis)
      - scrapes apify for organic reels (has all required metadata, no llm analysis, but follower count often missing, thus backfilled)
      - apify backfills follower count for organic 
      - scraped raw videos are in raw_payloads table
      - data is also inputted into paid_ads table
- download all videos
      - api returns expiring urls, but we need to render video live, thus we need our own copy of the video
      - we first download the video into RAM
      - then we upload this video into supabase storage, which is just bytes (not the database)
      - then this returns a url that points to the video in storage
      - this url is saved in the database (column: storage_video_url)
      - this kills 2 birds in 1 stone because to feed a video into openrouter later, you also need base64, which needs to be encoded from raw bytes from RAM too (not supabase storage currently)
      - note: sometimes even the url you fetch is expired
- feed all videos (ads, reels, tiktoks) into llm (Openrouter Gemini 3 Flash)
      - passes the storage url to openrouter, only fallback to base64 if fails
      - checks video url isn't null, and no non-video links
      - for ads, since there's built in analysis, this is also fed into the llm
      - llm returns a JSON object with all fields below
      - the JSON object is filled into the paid_ad_enrichments table
      - if api hiccup will rerun 3 times
- compute the embeddings for each video
      - compute both search + icp embedding
      - reference below to see what search fields take in
      - note: if enrichment fails, no embedding created

  ┌───────────────────────────┬─────────────────┬──────────────┬──────────────────────────────┐
  │           Field           │     Search      │     ICP      │            Filter            │
  │                           │    embedding    │  embedding   │                              │
  ├───────────────────────────┼─────────────────┼──────────────┼──────────────────────────────┤
  │ ai_description            │  ● (base text)  │              │                              │
  ├───────────────────────────┼─────────────────┼──────────────┼──────────────────────────────┤
  │ transcript_text           │  ● (appended)   │              │                              │
  ├───────────────────────────┼─────────────────┼──────────────┼──────────────────────────────┤
  │ content_formats ✅        │    ● format:    │              │   ● multi-select, overlap    │
  ├───────────────────────────┼─────────────────┼──────────────┼──────────────────────────────┤
  │ main_category             │   ● category:   │              │                              │
  ├───────────────────────────┼─────────────────┼──────────────┼──────────────────────────────┤
  │ content_category          │ ● subcategory:  │              │                              │
  ├───────────────────────────┼─────────────────┼──────────────┼──────────────────────────────┤
  │ product_category          │   ● product:    │              │                              │
  ├───────────────────────────┼─────────────────┼──────────────┼──────────────────────────────┤
  │ video_topic               │    ● topic:     │              │                              │
  ├───────────────────────────┼─────────────────┼──────────────┼──────────────────────────────┤
  │ niches                    │    ● niches:    │              │                              │
  ├───────────────────────────┼─────────────────┼──────────────┼──────────────────────────────┤
  │ hook                      │     ● hook:     │              │                              │
  ├───────────────────────────┼─────────────────┼──────────────┼──────────────────────────────┤
  │ setting                   │   ● setting:    │              │                              │
  ├───────────────────────────┼─────────────────┼──────────────┼──────────────────────────────┤
  │ primary_emotion           │   ● emotion:    │  ● emotion:  │                              │
  ├───────────────────────────┼─────────────────┼──────────────┼──────────────────────────────┤
  │ brand_mentioned           │    ● brands:    │              │                              │
  ├───────────────────────────┼─────────────────┼──────────────┼──────────────────────────────┤
  │ persona                   │                 │  ● persona:  │                              │
  ├───────────────────────────┼─────────────────┼──────────────┼──────────────────────────────┤
  │ target_demographic        │                 │ ● audience:  │                              │
  ├───────────────────────────┼─────────────────┼──────────────┼──────────────────────────────┤
  │ target_generation         │                 │      ●       │                              │
  │                           │                 │ generation:  │                              │
  ├───────────────────────────┼─────────────────┼──────────────┼──────────────────────────────┤
  │ content_tone              │                 │   ● tone:    │                              │
  ├───────────────────────────┼─────────────────┼──────────────┼──────────────────────────────┤
  │ visual_style              │                 │   ● style:   │                              │
  ├───────────────────────────┼─────────────────┼──────────────┼──────────────────────────────┤
  │ production_quality ✅     │                 │  ● quality:  │                              │
  ├───────────────────────────┼─────────────────┼──────────────┼──────────────────────────────┤
  │ emotional_drivers ✅      │                 │  ● drivers:  │                              │
  ├───────────────────────────┼─────────────────┼──────────────┼──────────────────────────────┤
  │ price_positioning         │                 │              │ ● single, exact (price_tier) │
  ├───────────────────────────┼─────────────────┼──────────────┼──────────────────────────────┤
  │ age_brackets              │                 │              │   ● multi-select, overlap    │
  ├───────────────────────────┼─────────────────┼──────────────┼──────────────────────────────┤
  │ languages                 │                 │              │   ● multi-select, overlap    │
  ├───────────────────────────┼─────────────────┼──────────────┼──────────────────────────────┤
  │ content_format (legacy)   │   ~~removed~~   │              │        superseded by         │
  │ ✅                        │                 │              │       content_formats        │
  └───────────────────────────┴─────────────────┴──────────────┴──────────────────────────────┘


## Inputs and outputs to all apis
 1. Keyword Gen - Claude API
     Input: campaign details + intended ad count + organic count
     Output: generates keywords + target count pairs
2. Apify Meta Ads
     Input: keyword (searched unordered in Meta Ad Library, video only)
     Output: ad items — video URL (expires), thumbnail, headline, description, page name (who's page owns the ad), call to action, adArchiveID
3. Apify Organic (TikTok + Instagram)
     Input: keyword
     Output: video URL (expires), cover, handle, view/like counts, follower count, hashtags
4. Video Enrichment - OpenRouter → Gemini (gemini-3-flash-preview)
     Input: video (base64) + ad copy context
     Output: transcript + segments, ai_description, hook, content_format, emotion, product_category, niches, has_product, etc.
5. Embeddings - Voyage (voyage-4-lite)
     Input: check table
     Output: embedding vector

## How does search work?
1. user inputs search query
2. search in the search embedding + icp embedding with HNSW, producing about 100 shorlisted videos each
3. combine videos + dedupe same results across both embeddings
4. then we rerank the 200ish videos
5. get actual data(we only have scores now), apply filters, dedupe same video different entry
6. return the rest

## Trend Scraping

## How do trends get populated?
- we track 4 webpages- ramdam, newengen, socialbee, socialgrowthengineers
- either, plain http request, or for js rendered websites, use a apify headless browser with actor website-content-crawler, waits till page rendered
   - SGE is special: it has a structured json api (/api/formats/), so skip fetch+LLM entirely, just read the api and copy fields across
- then it strips to only text and keeps video links; 'you might also like' links are filtered out
- compares content's hash to source, if no difference, skip scrape
- an openrouter call to google/gemini-3-flash with page inputs returns [{format_name, format_description, video_urls[]}]
- dedupe formats: sometimes the llm returns the same trend under multiple names, they're now collapsed into one
- 2 guards
   - if 0 formats got a video, incomplete render, retry
   - if a format has no video, it's a name-drop, drop the trend
- rescrape video url with apify for live metrics
- log cost
- enrichment



- saves each search into a dedicated row in *product* so identical searches persists