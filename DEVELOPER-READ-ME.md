## IF YOU ARE A DEVELOPER, READ!!!
For a future developer taking over this project, read this in extreme detail. This note is hand-written, intended to be concise, and draws out the skeleton of this repo and explains how data flows. A thorough understanding of this md will make future development much smoother.
Please aim to update this doc handwritten, and not with AI. This is because AI docs currently do not enforce the same level of concisenss, even if you turn this into a skill or explicitly as it to reference this md.

There are 2 skills that are repo specific:
1. the e2e report skill. this is such that end to end tests deliver reports that actually explain what it did. this repo has a lot of pipelines, thus you will have to run many flows.
2. the trend scraping skill. whenever you add a new source newsletter, beware that every single page renders differently. you might need to take different measures to make sure that a. all trends are correctly populated, all videos are saved, all saved videos match its corresponding trend. this usually requires a few trial and errors, and this skill documents the tried and failed runs. please update it as you add new newsletters.

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
     - SGE is special: it's url is unstable, now we find the latest post, get past the email gate with a cookie, then usual html stuff
- then it uses a static parser to get trend metadata and video link, llm fallback if fails
     - SGE is special: bad naming conventions thus passes through an LLM every time
     - if detects change in blog format, will send email to instaagenttool@gmail.com, signalling to manual change parser
- compares content's hash to source, if no difference, skip scrape
- an openrouter call to google/gemini-3-flash with page inputs returns [{format_name, format_description, video_urls[]}]
- dedupe formats: sometimes the llm returns the same trend under multiple names, they're now collapsed into one
- 2 guards
   - if 0 formats got a video, incomplete render, retry, only for js pages
   - if a format has no video, it's a name-drop, drop the trend
- route video back to format: the LLM gave us url → format. But when Apify scrapes those videos, it hands the results back as a flat list keyed by numeric video-id, not grouped by format. So we need the reverse map — video-id → format_id — to route each scraped video back to the right row. 
- if a video link is dead (deleted/private/expired), the format isn't written
- rescrape video url with apify for live metrics + video download
     - before rescrape, it checks if video exists in organic_items (to save cost, but highly unlikely)
- annotate: write ingest_note explaining video-less formats; delete formats with zero linked videos
- log cost
- alert owner if parser is broken via email with github actions
- enrichment > writes ai_description + transcript
- llm classifies the fit tags > outputs {versatility, fit_niches, product_requirements, niche_constraint}
- compute embeddings (voyage-4-lite)
     -It concatenates:{format_name}. {format_description}
     Works for: {fit_niches}  ({versatility}).
     Needs a product with: {product_requirements}.

## How does search work?
1. pull up to 2000 recent viral formats
2. vector similarity search to find top 20; 10 universal formats
3. 1 openrouter call that takes in these 30, returns a fit verdict (great/workable/no), a 0–100 score, and a one-line idea for using the format with your product
4. attatch example videos to format, ordered by views
5. search result ordered by fit score, no fit verdicts sink to bottom

