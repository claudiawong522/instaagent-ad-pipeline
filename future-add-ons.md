## ADD ONS
 1. search competitor specific ads/product ugc
 2. for database search, implement prompt expansion so that search is more comprehensive and not affected by short prompts
 3. compare `apple_yang/instagram-transcripts-scraper` actor as a possible alternative
 4. human review UI - add approval/rejection, notes
 5. add keyword approval, rejection, regeneration before scraping from campaign
 6. change newsletter scraping to email scraping for more timely trends
 7. include youtube shorts in addition to tiktoks and reels
 8. re-generate keywords on campaign edit, so new scrapes could reference different keywords, thus more varying results
 9. search bar for trends can input campaign
 10. one trend can have multiple ideas
 11. keyword virality graph (constraint: urls expire)
 12. support tiktok slideshow posts (tiktok.com/@user/photo/<id>) as trend examples — socialbee sometimes links them as a trend's only example, and they're currently invisible (VIDEO_URL_PATTERNS doesn't match /photo/), so those trends get dropped as video-less; needs the pattern + confirming the Apify TikTok actor returns something scrapeable for photo posts


## THINGS TO BEWARE
- if url form of newsletter changes, github actions scheduled scrape will fail, this requires a manual fix
  e.g. right now the month slug is hardcoded to the no-year form (july-tiktok-trends). Older months used <month>-2026-tiktok-trends. If newengen reverts, the fetch silently 404s and you get zero newengen trends with no error. Harden the URL builder to try both forms.


## THINGS TO DO NOW
- if format of newsletter changes, send an email and notify email




