import type {
  SearchFilters,
  SearchResponse,
  RunSummary,
  VideoResult,
  ItemType,
  Campaign,
  CreateCampaignInput,
  CreateCampaignResult,
  UpdateCampaignInput,
  DiscoverInput,
  DiscoverResult,
  Product,
  ScrapeStats,
  ScrapeEventsResponse,
} from './types'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(`API ${res.status}: ${body}`)
  }
  return res.json()
}

export async function searchAds(filters: SearchFilters): Promise<SearchResponse> {
  return request('/search', {
    method: 'POST',
    body: JSON.stringify({
      query: filters.query,
      item_type: filters.item_type ?? null,
      platform: filters.platform ?? null,
      run_id: filters.run_id ?? null,
      min_virality: filters.min_virality ?? null,
      min_views: filters.min_views ?? null,
      min_days_live: filters.min_days_live ?? null,
      languages: filters.languages?.length ? filters.languages : null,
      age_brackets: filters.age_brackets?.length ? filters.age_brackets : null,
      content_formats: filters.content_formats?.length ? filters.content_formats : null,
      price_tier: filters.price_tier ?? null,
      limit: filters.limit ?? null,
    }),
  })
}

export async function listRuns(): Promise<{ runs: RunSummary[] }> {
  return request('/runs')
}

export async function getItem(itemType: ItemType, itemId: string): Promise<VideoResult> {
  return request(`/items/${itemType}/${itemId}`)
}

export async function listProducts(): Promise<{ products: Product[] }> {
  return request('/products')
}

export async function listCampaigns(): Promise<{ campaigns: Campaign[] }> {
  return request('/campaigns')
}

export async function createCampaign(input: CreateCampaignInput): Promise<CreateCampaignResult> {
  return request('/campaigns', { method: 'POST', body: JSON.stringify(input) })
}

export async function updateCampaign(
  runId: string,
  input: UpdateCampaignInput,
): Promise<{ run_id: string; product_id: string }> {
  return request(`/campaigns/${runId}`, { method: 'PATCH', body: JSON.stringify(input) })
}

export async function triggerDiscovery(
  input: DiscoverInput,
  estimatedCostUsd?: number,
): Promise<DiscoverResult> {
  return request('/discover/scrape', {
    method: 'POST',
    body: JSON.stringify({ ...input, estimated_cost_usd: estimatedCostUsd ?? null }),
  })
}

export async function getScrapeStats(runId: string): Promise<ScrapeStats> {
  return request(`/campaigns/${runId}/scrape-stats`)
}

export async function getScrapeEvents(runId: string): Promise<ScrapeEventsResponse> {
  return request(`/campaigns/${runId}/scrape-events`)
}

export type ScrapePlatform = 'facebook' | 'instagram' | 'tiktok'

export async function triggerScrape(
  runId: string,
  platform: ScrapePlatform,
  targetCount?: number,
  estimatedCostUsd?: number,
): Promise<{ started: boolean; platform: string; reason?: string }> {
  return request(`/campaigns/${runId}/scrape`, {
    method: 'POST',
    body: JSON.stringify({
      platform,
      target_count: targetCount ?? null,
      estimated_cost_usd: estimatedCostUsd ?? null,
    }),
  })
}
