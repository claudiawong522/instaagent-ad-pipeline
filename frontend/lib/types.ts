export type ItemType = 'paid_ad' | 'ugc_item'

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
  // Paid-only longevity proxy (days the ad has been running); null for UGC.
  days_live: number | null
  // Phase 4 audience fields (null/[] until migration 018 + enrich-audience populate them).
  target_generation: string | null
  price_positioning: string | null
  age_brackets: string[]
  languages: string[]
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
  min_virality?: number | null // UGC-only (engagement rate %)
  min_views?: number | null // UGC-only
  min_days_live?: number | null // paid-only (days the ad has been running)
  languages?: string[] | null // multi-select, overlap match
  age_brackets?: string[] | null // multi-select, overlap match
  price_tier?: string | null // single: budget|mid|premium|luxury
  limit?: number
}

export interface Product {
  id: string
  name: string
  category: string | null
  target_market: string | null
  notes: string | null
  created_at: string | null
}

export interface Campaign {
  run_id: string
  status: string | null
  product_name: string | null
  category: string | null
  target_market: string | null
  campaign_name: string | null
  marketing_goals: string[]
  campaign_objective: string | null
  target_paid_count: number | null
  target_ugc_count: number | null
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
  target_paid_count: number
  target_ugc_count: number
}

export interface CreateCampaignResult {
  run_id: string
  product_id: string
  keyword_count: number
  warning: string | null
}

export interface ScrapeStats {
  run_id: string
  facebook_ads: number
  instagram_reels: number
  tiktoks: number
  running: string[] // platforms mid-scrape: facebook | instagram | tiktok
}

export interface RunSummary {
  run_id: string
  status: string | null
  product_name: string | null
  category: string | null
  target_paid_count: number | null
  target_ugc_count: number | null
  created_at: string | null
}
