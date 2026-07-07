// Helpers for reading the flat per-platform ScrapeStats shape, shared by the Campaigns and
// Discover pages.

import type { ScrapePlatform, ScrapeStats } from './types'

// The per-platform counters in ScrapeStats (`${platform}_${key}`). One list shared by the
// breakdown reader and emptyStats, so a new counter only needs adding here and to the type.
const COUNT_KEYS = ['searchable', 'expired', 'failed', 'processing', 'total', 'scraped', 'no_video'] as const

const PLATFORM_PREFIXES: ScrapePlatform[] = ['facebook', 'instagram', 'tiktok']

export type PlatformCounts = Record<(typeof COUNT_KEYS)[number], number>

/** Pull one platform's enrichment breakdown out of the flat ScrapeStats (0s when absent). */
export function platformBreakdown(stats: ScrapeStats | undefined, platform: ScrapePlatform): PlatformCounts {
  const out = {} as PlatformCounts
  for (const k of COUNT_KEYS) {
    out[k] = stats ? (stats as unknown as Record<string, number>)[`${platform}_${k}`] ?? 0 : 0
  }
  return out
}

/** Plain-English reasons a collected video isn't ready to search yet, nonzero only. Single source
 * of truth for the discovery and campaign summaries, so the wording stays identical. */
export function enrichmentReasons(b: PlatformCounts) {
  return [
    { label: 'loading', n: b.processing, text: `${b.processing} still loading`, cls: 'text-muted-foreground' },
    { label: 'expired', n: b.expired, text: `${b.expired} couldn't be loaded (removed)`, cls: 'text-amber-600 dark:text-amber-500' },
    { label: 'failed', n: b.failed, text: `${b.failed} couldn't be processed`, cls: 'text-red-600 dark:text-red-500' },
    { label: 'novideo', n: b.no_video, text: `${b.no_video} weren't videos`, cls: 'text-muted-foreground' },
  ].filter((r) => r.n > 0)
}

/** Zeroed stats for optimistic UI before the first poll returns — built from the field lists
 * above rather than hand-mirroring every ScrapeStats key. */
export function emptyStats(runId: string): ScrapeStats {
  const s: Record<string, unknown> = {
    run_id: runId,
    facebook_ads: 0,
    instagram_reels: 0,
    tiktoks: 0,
    running: [],
  }
  for (const p of PLATFORM_PREFIXES) {
    for (const k of COUNT_KEYS) s[`${p}_${k}`] = 0
    s[`${p}_last_scraped`] = null
    s[`${p}_scrape_failed`] = false
    s[`${p}_scrape_error`] = null
  }
  return s as unknown as ScrapeStats
}
