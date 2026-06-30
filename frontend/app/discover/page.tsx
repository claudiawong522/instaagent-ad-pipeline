'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { Loader2, Sparkles, ArrowRight } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Button, buttonVariants } from '@/components/ui/button'
import { triggerDiscovery, getScrapeStats, getScrapeEvents } from '@/lib/api'
import type { ScrapeStats, ScrapeEventsResponse } from '@/lib/types'

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

/** Scrape date/time, e.g. "Jun 23, 6:31 AM". */
function dateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
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
  // Items scraped but stuck unprocessed with nothing running = the job was killed mid-enrichment.
  // The backend auto-resumes leftovers on its next restart; until then, show the truth, not "Done".
  const interrupted = !running && (stats?.tiktok_processing ?? 0) > 0
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

  // Stop polling only when the run is truly finished — not merely "not running". An interrupted
  // run keeps polling so the panel updates once the backend restarts and auto-resumes it.
  useEffect(() => {
    if (stats && !running && !interrupted && pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [stats, running, interrupted])

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
              {running ? 'Discovery in progress' : interrupted ? 'Discovery interrupted' : 'Latest discovery'}
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
          <ScrapeHistory runId={runId} stats={stats ?? undefined} />
          <SearchableBreakdown stats={stats ?? undefined} />
          {interrupted ? (
            <div className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-700">
              Interrupted — {stats?.tiktok_processing} item{stats?.tiktok_processing === 1 ? '' : 's'} scraped but not
              yet enriched (the job was killed before finishing). The server automatically re-runs the leftover
              enrichment when it next restarts; this panel will update once it does.
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">
              {running
                ? 'Scraping, enriching, and scoring — this panel updates live. You can leave; the run continues server-side.'
                : 'Done. Open Search and filter to Organic to browse the formats, sorted by virality.'}
            </p>
          )}
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

/** Per-run cost history, newest-first, each row with its date/time, item count and total cost
 * (Apify + enrichment + embeddings, summed). Cost is an estimate while running → exact once the
 * run finishes. Refetches whenever the run's state changes so a just-finished run's real cost
 * lands. Mirrors the campaigns Scrapes & cost panel, scoped to discovery's single platform. */
function ScrapeHistory({ runId, stats }: { runId: string; stats: ScrapeStats | undefined }) {
  const [data, setData] = useState<ScrapeEventsResponse | null>(null)
  const refreshKey = [stats?.running.join(','), stats?.tiktok_last_scraped].join('|')
  useEffect(() => {
    getScrapeEvents(runId)
      .then(setData)
      .catch(() => {})
  }, [runId, refreshKey])

  if (!data || data.events.length === 0) {
    return (
      <div className="rounded-md bg-muted/50 p-3 text-xs text-muted-foreground">
        No runs yet — each discovery run and its cost appears here.
      </div>
    )
  }
  const pending = data.events.some((e) => e.cost_kind === 'estimate')
  return (
    <div className="flex flex-col gap-1.5 rounded-md bg-muted/50 p-3 text-xs">
      <div className="font-medium text-muted-foreground">Runs &amp; cost</div>
      {data.events.map((e) => {
        const estimate = e.cost_kind === 'estimate'
        return (
          <div key={e.id} className="flex items-baseline justify-between gap-2">
            <span className="text-foreground">
              {e.platform === DISCOVERY_PLATFORM ? 'TikTok trends' : e.platform}
              <span className="text-muted-foreground">
                {' · '}
                {dateTime(e.when)}
                {e.items != null ? ` · ${e.items} items` : ''}
              </span>
            </span>
            <span className="shrink-0 tabular-nums">
              {estimate ? (
                <span className="text-muted-foreground/70">
                  ≈ {money(e.cost_usd)}
                  {e.status === 'running' ? ' · running…' : ''}
                </span>
              ) : (
                <span className="text-foreground">{money(e.cost_usd)}</span>
              )}
            </span>
          </div>
        )
      })}
      <div className="mt-1 flex items-baseline justify-between gap-2 border-t border-border pt-1.5 font-medium">
        <span className="text-foreground">Total spent{pending ? ' (so far)' : ''}</span>
        <span className="shrink-0 tabular-nums text-foreground">{money(data.total_spent_usd)}</span>
      </div>
    </div>
  )
}

/** "X of Y searchable" progress for the discovery pull, with expired/failed/processing
 * breakdown — how many scraped videos OpenRouter could actually ingest. Mirrors the campaigns
 * Searchable videos panel, driven straight off the tiktok_* stats. */
function SearchableBreakdown({ stats }: { stats: ScrapeStats | undefined }) {
  const total = stats?.tiktok_total ?? 0
  if (total === 0) {
    return (
      <div className="rounded-md bg-muted/50 p-3 text-xs text-muted-foreground">
        No videos scraped yet — searchable counts appear here after a run.
      </div>
    )
  }
  const searchable = stats?.tiktok_searchable ?? 0
  const expired = stats?.tiktok_expired ?? 0
  const failed = stats?.tiktok_failed ?? 0
  const processing = stats?.tiktok_processing ?? 0
  const pct = Math.round((searchable / total) * 100)
  const clean = expired === 0 && failed === 0 && processing === 0
  return (
    <div className="flex flex-col gap-2.5 rounded-md bg-muted/50 p-3 text-xs">
      <div className="font-medium text-muted-foreground">Searchable videos</div>
      <div className="flex flex-col gap-1">
        <div className="flex items-center justify-between gap-2">
          <span className="text-foreground">TikTok</span>
          <span className="tabular-nums text-muted-foreground">
            {searchable} of {total} searchable
          </span>
        </div>
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
          <div className="h-full rounded-full bg-emerald-500" style={{ width: `${pct}%` }} />
        </div>
        {clean ? (
          <span className="text-[11px] text-emerald-600 dark:text-emerald-500">✓ all searchable</span>
        ) : (
          <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[11px]">
            {expired > 0 && <span className="text-amber-600 dark:text-amber-500">⚠ {expired} expired URL</span>}
            {failed > 0 && <span className="text-red-600 dark:text-red-500">✕ {failed} failed</span>}
            {processing > 0 && <span className="text-muted-foreground">◷ {processing} processing</span>}
          </div>
        )}
      </div>
    </div>
  )
}
