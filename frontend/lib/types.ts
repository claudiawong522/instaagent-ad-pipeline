export type ItemType = 'paid_ad' | 'organic_item'

export interface VideoResult {
  item_type: ItemType
  item_id: string
  run_id: string | null
  title: string | null
  platform: string | null
  video_url: string | null
  thumb_url: string | null
  original_url: string | null
  followers: number | null
  views: number | null
  likes: number | null
  virality: number | null
  hook: string | null
  ai_description: string | null
  content_format: string | null
  product_category: string | null
  video_topic: string | null
  transcript: string | null
  similarity: number | null
  // Organic-only: when the post was published (ISO timestamp); null for paid.
  date_created?: string | null
  // Paid-only longevity proxy (days the ad has been running); null for organic.
  days_live: number | null
  // Phase 4 audience fields (null/[] until migration 018 + enrich-audience populate them).
  target_generation: string | null
  price_positioning: string | null
  age_brackets: string[]
  languages: string[]
  // Multi-value production format (migration 020); supersedes content_format.
  content_formats: string[]
}

export interface SearchResponse {
  query: string
  count: number
  results: VideoResult[]
}

export interface SearchFilters {
  query: string
  item_type?: ItemType | null
  platform?: string | null
  run_id?: string | null
  min_virality?: number | null // organic-only (normalized virality score, 0-1)
  min_views?: number | null // organic-only
  min_days_live?: number | null // paid-only (days the ad has been running)
  min_date?: string | null // organic-only: only items posted on/after this ISO date
  languages?: string[] | null // multi-select, overlap match
  age_brackets?: string[] | null // multi-select, overlap match
  content_formats?: string[] | null // multi-select, overlap match (production format)
  price_tier?: string | null // single: budget|mid|premium|luxury
  limit?: number
}

export interface Campaign {
  run_id: string
  status: string | null
  product_name: string | null
  category: string | null
  target_market: string | null
  description: string | null
  campaign_name: string | null
  marketing_goals: string[]
  campaign_objective: string | null
  target_paid_count: number | null
  target_organic_count: number | null // reels (Instagram)
  target_tiktok_count: number | null
  created_at: string | null
}

export interface CreateCampaignInput {
  product_name: string
  category?: string | null
  target_market?: string | null
  notes?: string | null
  campaign_name: string
  marketing_goals: string[]
  campaign_objective?: string | null
  // Scrape targets aren't set at creation — they're chosen per-platform at scrape time.
  // Omitted here so the backend defaults apply (used only to seed keyword allocation).
  target_paid_count?: number
  target_organic_count?: number // reels (Instagram)
  target_tiktok_count?: number
}

// Editing a campaign's details in place. Same fields as create minus the scrape target
// counts (those are chosen per-platform at scrape time).
export interface UpdateCampaignInput {
  product_name: string
  category?: string | null
  target_market?: string | null
  notes?: string | null
  campaign_name: string
  marketing_goals: string[]
  campaign_objective?: string | null
}

export interface CreateCampaignResult {
  run_id: string
  product_id: string
  keyword_count: number
  warning: string | null
}

// Keyword-free viral-format discovery (the Discover page). Not tied to a product/campaign.
export interface DiscoverInput {
  region: string // ISO country code, e.g. US / GB
  target_count: number
  min_views: number // drop For-You feed-filler below this view count
}

export interface DiscoverResult {
  started: boolean
  run_id: string // the singleton discovery run; poll scrape-stats with it
  reason?: string
}

// The platforms a campaign scrape can target (and the prefixes of ScrapeStats' flat fields).
export type ScrapePlatform = 'facebook' | 'instagram' | 'tiktok'

// Per-platform enrichment breakdown. searchable = scraped video became searchable;
// expired = provider URL no longer served video; failed = analysis produced nothing;
// processing = has a video, not yet enriched. total = searchable universe (videos only).
export interface PlatformBreakdown {
  searchable: number
  expired: number
  failed: number
  processing: number
  total: number
  last_scraped: string | null
}

export interface ScrapeStats {
  run_id: string
  // Headline counts = searchable only (the tiles show successful videos).
  facebook_ads: number
  instagram_reels: number
  tiktoks: number
  // Funnel per platform: scraped (every row) ≥ total (has a video) ≥ attempted
  // (searchable+expired+failed, derived in the UI) ≥ searchable. no_video = scraped − total.
  facebook_searchable: number
  facebook_expired: number
  facebook_failed: number
  facebook_processing: number
  facebook_total: number
  facebook_scraped: number
  facebook_no_video: number
  facebook_last_scraped: string | null
  instagram_searchable: number
  instagram_expired: number
  instagram_failed: number
  instagram_processing: number
  instagram_total: number
  instagram_scraped: number
  instagram_no_video: number
  instagram_last_scraped: string | null
  tiktok_searchable: number
  tiktok_expired: number
  tiktok_failed: number
  tiktok_processing: number
  tiktok_total: number
  tiktok_scraped: number
  tiktok_no_video: number
  tiktok_last_scraped: string | null
  // Most recent finished scrape attempt for the platform ended in error (e.g. a network drop
  // mid-write). A platform mid-scrape is never flagged failed.
  facebook_scrape_failed: boolean
  instagram_scrape_failed: boolean
  tiktok_scrape_failed: boolean
  // Out-of-credits message for the latest scrape (null when there's no billing problem). When set,
  // the UI shows a "refill and re-run" prompt. Set even on an otherwise-done scrape whose enrichment
  // ran out of credits.
  facebook_scrape_error: string | null
  instagram_scrape_error: string | null
  tiktok_scrape_error: string | null
  running: string[] // platforms mid-scrape: facebook | instagram | tiktok
}

// One platform scrape and its total cost (Apify + enrichment + embeddings, summed). cost_kind:
// 'actual' = finished UI scrape (reconciled), 'estimate' = UI scrape still running, 'reconstructed'
// = spend from before per-scrape tracking, rebuilt per-platform from api_usage.
export interface ScrapeEvent {
  id: string
  platform: string // facebook | instagram | tiktok
  when: string | null // scrape date/time (ISO)
  cost_usd: number
  cost_kind: 'actual' | 'estimate' | 'reconstructed'
  items: number | null
  status: string // running | done | failed
}

export interface ScrapeEventsResponse {
  events: ScrapeEvent[] // newest-first, tracked + reconstructed
  total_spent_usd: number
  total_actual_usd: number
}

// Trends dashboard: a viral format scraped from a web trend page, with its example videos.
export interface TrendVideo {
  id: string
  video_url: string | null // storage MP4 (falls back to provider URL)
  thumb_url: string | null
  original_url: string | null // the TikTok/Reel page
  views: number | null
  likes: number | null
  virality: number | null
  handle: string | null
  description: string | null
  enrichment_status: string | null
  date_created: string | null // when the video was posted (ISO)
}

export interface ViralFormat {
  id: string
  source_name: string | null // e.g. ramdam, socialbee
  source_url: string | null
  issue_date: string | null
  format_name: string | null
  format_description: string | null
  niche_constraint: string | null // free-form, LLM-written marketing constraint
  versatility?: 'universal' | 'broad' | 'niche' | null // coarse reuse bucket (classify-formats)
  fit_niches?: string[] // niches the format suits ([] = any product)
  product_requirements?: string[] // what a product must show to reuse it ([] = any product)
  ingest_note?: string | null // why the format has no playable video (null when it has one)
  video_count: number
  total_views: number // aggregate live views across example videos (ranking key)
  videos: TrendVideo[]
}

export interface TrendFormatsResponse {
  formats: ViralFormat[]
}

// A viral format ranked against a product by POST /trends/match: ViralFormat + fit fields.
export interface MatchedFormat extends ViralFormat {
  fit: 'great' | 'workable' | 'no'
  score: number // 0-100, how well the product suits the format (ranking key)
  idea: string // one-line how-to-use-it-for-your-product ('' when fit is 'no')
}

export interface MatchFormatsResponse {
  formats: MatchedFormat[]
}

export interface RunSummary {
  run_id: string
  status: string | null
  campaign_name: string | null // from run config (campaign wizard); null for bare CLI runs
  discovery?: boolean // true for the keyword-free Viral Discovery run
  product_name: string | null
  category: string | null
  target_paid_count: number | null
  target_organic_count: number | null // reels (Instagram)
  target_tiktok_count: number | null
  created_at: string | null
}
