## ADD ONS
 1. search competitor specific ads/product ugc
    - e.g. type "Athletic Greens" and get back all their live Meta ads plus creator UGC for the product
 2. for database search, implement prompt expansion so that search is more comprehensive and not affected by short prompts
    - e.g. a search for "gym" also matches clips tagged "workout", "fitness", "training" instead of only literal "gym"
 3. compare `apple_yang/instagram-transcripts-scraper` actor as a possible alternative
    - e.g. run the same 10 reels through both actors and diff transcript accuracy + cost per run
 4. human review UI - add approval/rejection, notes
    - e.g. a reviewer clicks ✓/✗ on each scraped ad and leaves "hook is too slow" before it enters the library
 5. add keyword approval, rejection, regeneration before scraping from campaign
    - e.g. campaign suggests "protein powder, bcaa, creatine" — user drops "bcaa" and hits regenerate for fresh terms
 6. change newsletter scraping to email scraping for more timely trends
    - e.g. read trends straight from the TikTok-trends email inbox the day it arrives instead of waiting for the web archive
 7. include youtube shorts in addition to tiktoks and reels
    - e.g. a trending sound surfaces from a YouTube Short even when no TikTok/Reel example exists yet
 8. re-generate keywords on campaign edit, so new scrapes could reference different keywords, thus more varying results
    - e.g. editing a campaign's audience from "students" to "new parents" regenerates keywords so the next scrape pulls different clips
 9. search bar for trends can input campaign
    - e.g. pick "Summer Hydration" campaign in the trends search and only see trends relevant to that campaign
 10. one trend can have multiple ideas
    - e.g. the "get ready with me" trend spawns three ad ideas: skincare, coffee, and commute
 11. keyword virality graph (constraint: urls expire)
    - e.g. a line chart showing a keyword's view count climbing over the past 2 weeks (caveat: source URLs 404 after expiry)
 12. support tiktok slideshow posts (tiktok.com/@user/photo/<id>) as trend examples — socialbee sometimes links them as a trend's only example, and they're currently invisible (VIDEO_URL_PATTERNS doesn't match /photo/), so those trends get dropped as video-less; needs the pattern + confirming the Apify TikTok actor returns something scrapeable for photo posts
    - e.g. a trend whose only example is tiktok.com/@user/photo/123 currently vanishes; after the fix it shows up as a slideshow card


## THINGS TO BEWARE
- if url form of newsletter changes, github actions scheduled scrape will fail, this requires a manual fix, an email notifies instaagenttool@gmail.com
  e.g. right now the month slug is hardcoded to the no-year form (july-tiktok-trends). Older months used <month>-2026-tiktok-trends. If newengen reverts, the fetch silently 404s and you get zero newengen trends with no error. 







