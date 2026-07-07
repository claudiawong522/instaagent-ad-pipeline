import type {
  SearchFilters,
  SearchResponse,
  RunSummary,
  Campaign,
  CreateCampaignInput,
  CreateCampaignResult,
  UpdateCampaignInput,
  DiscoverInput,
  DiscoverResult,
  ScrapePlatform,
  ScrapeStats,
  ScrapeEventsResponse,
  TrendFormatsResponse,
  MatchFormatsResponse,
} from './types'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
// Shared-secret the backend requires when API_AUTH_TOKEN is set (bot speed bump). Visible in the
// browser bundle by design — it only blocks anonymous/direct hits, not app users.
const API_TOKEN = process.env.NEXT_PUBLIC_API_TOKEN

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(API_TOKEN ? { Authorization: `Bearer ${API_TOKEN}` } : {}),
    },
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
      min_date: filters.min_date ?? null,
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

export async function listTrendFormats(opts?: {
  sourceName?: string | null
  q?: string | null
  minViews?: number | null
  scrapedOn?: string | null
}): Promise<TrendFormatsResponse> {
  const params = new URLSearchParams()
  if (opts?.sourceName) params.set('source_name', opts.sourceName)
  if (opts?.q) params.set('q', opts.q)
  if (opts?.minViews) params.set('min_views', String(opts.minViews))
  if (opts?.scrapedOn) params.set('scraped_on', opts.scrapedOn)
  const qs = params.toString()
  return request(`/trends/formats${qs ? `?${qs}` : ''}`)
}

export async function listTrendScrapeDates(
  sourceName?: string | null,
): Promise<{ dates: string[] }> {
  const qs = sourceName ? `?source_name=${encodeURIComponent(sourceName)}` : ''
  return request(`/trends/scrape-dates${qs}`)
}

export async function matchProduct(opts: {
  product: string
  limit?: number | null
}): Promise<MatchFormatsResponse> {
  return request('/trends/match', {
    method: 'POST',
    body: JSON.stringify({ product: opts.product, limit: opts.limit ?? null }),
  })
}

export async function getScrapeStats(runId: string): Promise<ScrapeStats> {
  return request(`/campaigns/${runId}/scrape-stats`)
}

export async function getScrapeEvents(runId: string): Promise<ScrapeEventsResponse> {
  return request(`/campaigns/${runId}/scrape-events`)
}

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
