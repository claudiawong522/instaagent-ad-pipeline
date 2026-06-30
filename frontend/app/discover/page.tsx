'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { Loader2, Sparkles, ArrowRight } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Button, buttonVariants } from '@/components/ui/button'
import { triggerDiscovery, getScrapeStats } from '@/lib/api'
import type { ScrapeStats } from '@/lib/types'

// Country For-You feeds novi supports. Codes are ISO 3166 alpha-2 (sent uppercased).
const REGIONS = [
  ['US', 'United States'], ['GB', 'United Kingdom'], ['AU', 'Australia'], ['CA', 'Canada'],
  ['DE', 'Germany'], ['FR', 'France'], ['JP', 'Japan'], ['BR', 'Brazil'], ['IN', 'India'], ['MX', 'Mexico'],
] as const

// Rough blended $/item (Apify trend pull + follower backfill + enrichment + embedding) for the
// pre-scrape estimate. Discovery does more per item than a plain scrape, so it runs a touch higher.
const COST_PER_ITEM_USD = 0.012
const DISCOVERY_PLATFORM = 'tiktok-trends'

function money(usd: number): string {
  if (usd > 0 && usd < 0.01) return '<$0.01'
  return `$${usd.toFixed(2)}`
}

export default function DiscoverPage() {
  const [region, setRegion] = useState<string>('US')
  const [targetCount, setTargetCount] = useState(200)
  const [minViews, setMinViews] = useState(100000)
  const [runId, setRunId] = useState<string | null>(null)
  const [stats, setStats] = useState<ScrapeStats | null>(null)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const running = !!stats?.running.includes(DISCOVERY_PLATFORM)
  const estCost = COST_PER_ITEM_USD * Math.max(0, targetCount)

  const poll = useCallback(async (id: string) => {
    try {
      setStats(await getScrapeStats(id))
    } catch {
      /* transient — keep the last good stats */
    }
  }, [])

  // Poll while a discovery run is in flight; stop once the backend reports it's no longer running.
  useEffect(() => {
    if (!runId) return
    poll(runId)
    pollRef.current = setInterval(() => poll(runId), 4000)
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [runId, poll])

  useEffect(() => {
    if (stats && !running && pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [stats, running])

  async function onDiscover() {
    setStarting(true)
    setError(null)
    try {
      const res = await triggerDiscovery({ region, target_count: targetCount, min_views: minViews }, estCost)
      setRunId(res.run_id)
      setStats(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to start discovery')
    } finally {
      setStarting(false)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Discover viral formats</h1>
        <p className="text-sm text-muted-foreground">
          Pull TikTok&apos;s For You feed for a country — no keyword, no product. Study what&apos;s going
          viral, then find the winners in Search under the Organic filter.
        </p>
      </div>

      <div className="flex flex-col gap-4 rounded-xl border border-border bg-card p-5">
        <div className="grid gap-4 sm:grid-cols-3">
          <label className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-muted-foreground">Region</span>
            <select
              value={region}
              onChange={(e) => setRegion(e.target.value)}
              className="h-9 rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              {REGIONS.map(([code, name]) => (
                <option key={code} value={code}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-muted-foreground">How many to pull</span>
            <Input
              type="number"
              min={1}
              max={1000}
              value={targetCount}
              onChange={(e) => setTargetCount(Math.max(1, Math.min(1000, Number(e.target.value) || 0)))}
              className="h-9"
            />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-muted-foreground">Min views (drops feed-filler)</span>
            <Input
              type="number"
              min={0}
              step={10000}
              value={minViews}
              onChange={(e) => setMinViews(Math.max(0, Number(e.target.value) || 0))}
              className="h-9"
            />
          </label>
        </div>

        <div className="flex items-center justify-between gap-3">
          <p className="text-xs text-muted-foreground">
            Est. ~{money(estCost)} · runs the full chain (scrape → enrich → backfill followers → score).
            Takes a few minutes.
          </p>
          <Button onClick={onDiscover} disabled={starting || running} className="gap-1.5">
            {starting || running ? <Loader2 className="size-4 animate-spin" /> : <Sparkles className="size-4" />}
            {running ? 'Discovering…' : starting ? 'Starting…' : 'Discover viral formats'}
          </Button>
        </div>

        {error && (
          <div className="rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive">
            {error}
          </div>
        )}
      </div>

      {runId && (
        <div className="flex flex-col gap-3 rounded-xl border border-border bg-card p-5">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium">
              {running ? 'Discovery in progress' : 'Latest discovery'}
            </h2>
            <Link href="/search" className={buttonVariants({ variant: 'outline', size: 'sm' }) + ' gap-1.5'}>
              View in Search <ArrowRight className="size-3.5" />
            </Link>
          </div>
          <div className="grid grid-cols-3 gap-3 text-center">
            <Stat label="Scraped" value={stats?.tiktok_total} />
            <Stat label="Processing" value={stats?.tiktok_processing} />
            <Stat label="Searchable" value={stats?.tiktok_searchable} highlight />
          </div>
          <p className="text-xs text-muted-foreground">
            {running
              ? 'Scraping, enriching, and scoring — this panel updates live. You can leave; the run continues server-side.'
              : 'Done. Open Search and filter to Organic to browse the formats, sorted by virality.'}
          </p>
        </div>
      )}
    </div>
  )
}

function Stat({ label, value, highlight }: { label: string; value: number | undefined; highlight?: boolean }) {
  return (
    <div className="rounded-lg bg-muted/50 p-3">
      <div className={highlight ? 'text-2xl font-semibold text-[#9d1555]' : 'text-2xl font-semibold'}>
        {value ?? '—'}
      </div>
      <div className="text-xs text-muted-foreground">{label}</div>
    </div>
  )
}
