'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { Loader2, Sparkles, ArrowRight, CheckCircle2, Circle } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Button, buttonVariants } from '@/components/ui/button'
import { triggerDiscovery, getScrapeStats, getScrapeEvents, listRuns } from '@/lib/api'
import type { ScrapeStats, ScrapeEventsResponse, RunSummary } from '@/lib/types'

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
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [stats, setStats] = useState<Record<string, ScrapeStats>>({})
  const [loading, setLoading] = useState(true)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const estCost = COST_PER_ITEM_USD * Math.max(0, targetCount)
  // Disable the trigger while any discovery run is mid-scrape (only one runs at a time server-side).
  const anyRunning = runs.some((r) => stats[r.run_id]?.running.includes(DISCOVERY_PLATFORM))

  const refreshStats = useCallback(async (runIds: string[]) => {
    const results = await Promise.allSettled(runIds.map((id) => getScrapeStats(id)))
    setStats((prev) => {
      const next = { ...prev }
      results.forEach((res, i) => {
        if (res.status === 'fulfilled') next[runIds[i]] = res.value
      })
      return next
    })
  }, [])

  // Load every past discovery run (newest first) on mount, then its stats — so the latest run and
  // all previous ones show without needing to re-trigger. Mirrors the campaigns list.
  const loadRuns = useCallback(async () => {
    const r = await listRuns()
    const discovery = r.runs
      .filter((run) => run.discovery)
      .sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? ''))
    setRuns(discovery)
    refreshStats(discovery.map((run) => run.run_id))
  }, [refreshStats])

  useEffect(() => {
    loadRuns()
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [loadRuns])

  // Poll stats for any run still scraping (plus ones we just kicked off) until they settle.
  const pollRef = useRef<Set<string>>(new Set())
  useEffect(() => {
    const id = setInterval(() => {
      const active = runs
        .filter((r) => stats[r.run_id]?.running.includes(DISCOVERY_PLATFORM))
        .map((r) => r.run_id)
      const toPoll = new Set(active.concat(Array.from(pollRef.current)))
      if (toPoll.size === 0) return
      refreshStats(Array.from(toPoll))
      pollRef.current.forEach((rid) => {
        if (stats[rid] && !stats[rid].running.includes(DISCOVERY_PLATFORM)) pollRef.current.delete(rid)
      })
    }, 4000)
    return () => clearInterval(id)
  }, [runs, stats, refreshStats])

  async function onDiscover() {
    setStarting(true)
    setError(null)
    try {
      const res = await triggerDiscovery({ region, target_count: targetCount, min_views: minViews }, estCost)
      pollRef.current.add(res.run_id)
      await loadRuns()
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
          <Button onClick={onDiscover} disabled={starting || anyRunning} className="gap-1.5">
            {starting || anyRunning ? <Loader2 className="size-4 animate-spin" /> : <Sparkles className="size-4" />}
            {anyRunning ? 'Discovering…' : starting ? 'Starting…' : 'Discover viral formats'}
          </Button>
        </div>

        {error && (
          <div className="rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive">
            {error}
          </div>
        )}
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-16 text-muted-foreground">
          <Loader2 className="mr-2 size-5 animate-spin" /> Loading…
        </div>
      ) : runs.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border py-12 text-center text-sm text-muted-foreground">
          No discovery runs yet — start one above and its progress and cost will show here.
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          {runs.map((run, i) => (
            <DiscoveryRunCard key={run.run_id} run={run} stats={stats[run.run_id]} latest={i === 0} />
          ))}
        </div>
      )}
    </div>
  )
}

/** One discovery run's live panel: phase status, scraped/processing/searchable stats, the
 * runs-&-cost log, and the searchable breakdown. The newest run is labelled "Latest discovery";
 * older ones show their date. Identical content to the campaigns scrape panel, per run. */
function DiscoveryRunCard({
  run,
  stats,
  latest,
}: {
  run: RunSummary
  stats: ScrapeStats | undefined
  latest: boolean
}) {
  const running = !!stats?.running.includes(DISCOVERY_PLATFORM)
  // Items scraped but stuck unprocessed with nothing running = the job was killed mid-enrichment.
  // The backend auto-resumes leftovers on its next restart; until then, show the truth, not "Done".
  const interrupted = !running && (stats?.tiktok_processing ?? 0) > 0
  const heading = running
    ? 'Discovery in progress'
    : interrupted
      ? 'Discovery interrupted'
      : latest
        ? 'Latest discovery'
        : `Discovery · ${dateTime(run.created_at)}`

  return (
    <div className="flex flex-col gap-3 rounded-xl border border-border bg-card p-5">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium">{heading}</h2>
        <Link href="/search" className={buttonVariants({ variant: 'outline', size: 'sm' }) + ' gap-1.5'}>
          View in Search <ArrowRight className="size-3.5" />
        </Link>
      </div>
      <PhaseStatus stats={stats} running={running} />
      <DiscoveryFunnel stats={stats} />
      <ScrapeHistory runId={run.run_id} stats={stats} />
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

/** Two-phase truth of a discovery run: items are scraped first, then enriched (made searchable).
 * Scraped ticks once items land; Enriched stays a spinner while anything is still processing and
 * only ticks when enrichment is genuinely complete (nothing left in processing). */
function PhaseStatus({ stats, running }: { stats: ScrapeStats | undefined; running: boolean }) {
  const collected = stats?.tiktok_scraped ?? 0
  const processing = stats?.tiktok_processing ?? 0
  const ready = stats?.tiktok_searchable ?? 0

  const collectState = collected > 0 ? 'done' : running ? 'active' : 'pending'
  // "Ready" ticks only when nothing is left loading; spins while videos are still being made
  // ready; stays pending until something has been collected.
  const readyState = collected === 0 ? 'pending' : processing > 0 ? 'active' : 'done'

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-sm">
      <Phase
        label="Collected"
        state={collectState}
        detail={collected > 0 ? String(collected) : collectState === 'active' ? '…' : undefined}
      />
      <span className="text-muted-foreground/40">→</span>
      <Phase label="Ready to search" state={readyState} detail={collected > 0 ? String(ready) : undefined} />
    </div>
  )
}

function Phase({
  label,
  state,
  detail,
}: {
  label: string
  state: 'done' | 'active' | 'pending'
  detail?: string
}) {
  const icon =
    state === 'done' ? (
      <CheckCircle2 className="size-4 text-emerald-500" />
    ) : state === 'active' ? (
      <Loader2 className="size-4 animate-spin text-[#9d1555]" />
    ) : (
      <Circle className="size-4 text-muted-foreground/40" />
    )
  return (
    <span className="inline-flex items-center gap-1.5">
      {icon}
      <span className={state === 'pending' ? 'text-muted-foreground' : 'font-medium text-foreground'}>
        {label}
      </span>
      {detail && <span className="tabular-nums text-muted-foreground">{detail}</span>}
    </span>
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

/** Plain-English summary of a discovery pull: how many videos we collected vs how many are ready
 * to search, with a one-line reason for anything in between (still loading / couldn't be loaded /
 * weren't videos). Deliberately avoids jargon ("scraped", "enriched") and internal denominators. */
function DiscoveryFunnel({ stats }: { stats: ScrapeStats | undefined }) {
  const collected = stats?.tiktok_scraped ?? 0
  if (collected === 0) {
    return (
      <div className="rounded-md bg-muted/50 p-3 text-center text-xs text-muted-foreground">
        Nothing collected yet — counts appear here after a run.
      </div>
    )
  }
  const ready = stats?.tiktok_searchable ?? 0
  const reasons = enrichmentReasons(stats, 'tiktok')

  return (
    <div className="flex flex-col gap-2.5">
      <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-1 text-center">
        <Stat label="Collected" value={collected} />
        <span className="text-muted-foreground/40">→</span>
        <Stat label="Ready to search" value={ready} highlight />
      </div>
      {reasons.length === 0 ? (
        <p className="text-center text-[11px] text-emerald-600 dark:text-emerald-500">✓ all ready to search</p>
      ) : (
        <p className="flex flex-wrap justify-center gap-x-3 gap-y-0.5 text-[11px]">
          {reasons.map((r) => (
            <span key={r.label} className={r.cls}>
              {r.text}
            </span>
          ))}
        </p>
      )}
    </div>
  )
}

/** Plain-English reasons a collected video isn't ready to search yet, nonzero only. Shared by the
 * discovery and (via the same field names) campaign summaries so the wording stays identical. */
function enrichmentReasons(stats: ScrapeStats | undefined, prefix: 'tiktok' | 'facebook' | 'instagram') {
  const g = (k: string) => (stats ? (stats as unknown as Record<string, number>)[`${prefix}_${k}`] ?? 0 : 0)
  return [
    { label: 'loading', n: g('processing'), text: `${g('processing')} still loading`, cls: 'text-muted-foreground' },
    { label: 'expired', n: g('expired'), text: `${g('expired')} couldn't be loaded (removed)`, cls: 'text-amber-600 dark:text-amber-500' },
    { label: 'failed', n: g('failed'), text: `${g('failed')} couldn't be processed`, cls: 'text-red-600 dark:text-red-500' },
    { label: 'novideo', n: g('no_video'), text: `${g('no_video')} weren't videos`, cls: 'text-muted-foreground' },
  ].filter((r) => r.n > 0)
}
