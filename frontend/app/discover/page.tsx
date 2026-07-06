'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { Loader2, Sparkles, ArrowRight, CheckCircle2, AlertTriangle, Wallet } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Button, buttonVariants } from '@/components/ui/button'
import { ProgressBar } from '@/components/ui/progress-bar'
import { triggerDiscovery, listRuns } from '@/lib/api'
import type { ScrapeStats, RunSummary } from '@/lib/types'
import { dateTime, money } from '@/lib/format'
import { enrichmentReasons, platformBreakdown } from '@/lib/scrape'
import { useScrapeEvents, useScrapeStatsPolling } from '@/lib/useScrapeStatsPolling'
import { HelpPopover } from '@/components/HelpPopover'

// Country For-You feeds novi supports. Codes are ISO 3166 alpha-2 (sent uppercased).
const REGIONS = [
  ['US', 'United States'], ['GB', 'United Kingdom'], ['AU', 'Australia'], ['CA', 'Canada'],
  ['DE', 'Germany'], ['FR', 'France'], ['JP', 'Japan'], ['BR', 'Brazil'], ['IN', 'India'], ['MX', 'Mexico'],
] as const

// Rough blended $/item (Apify trend pull + follower backfill + enrichment + embedding) for the
// pre-scrape estimate. Discovery does more per item than a plain scrape, so it runs a touch higher.
const COST_PER_ITEM_USD = 0.012
const DISCOVERY_PLATFORM = 'tiktok-trends'

// A discovery run mid-scrape keeps getting polled until it settles.
const discoveryRunning = (s: ScrapeStats) => s.running.includes(DISCOVERY_PLATFORM)

export default function DiscoverPage() {
  const [region, setRegion] = useState<string>('US')
  const [targetCount, setTargetCount] = useState(200)
  const [minViews, setMinViews] = useState(100000)
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { stats, refreshStats, watch } = useScrapeStatsPolling(discoveryRunning, 4000)

  const estCost = COST_PER_ITEM_USD * Math.max(0, targetCount)
  // Disable the trigger while any discovery run is mid-scrape (only one runs at a time server-side).
  const anyRunning = runs.some((r) => stats[r.run_id]?.running.includes(DISCOVERY_PLATFORM))

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

  async function onDiscover() {
    setStarting(true)
    setError(null)
    try {
      const res = await triggerDiscovery({ region, target_count: targetCount, min_views: minViews }, estCost)
      watch(res.run_id)
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
            <DiscoveryRunCard
              key={run.run_id}
              run={run}
              stats={stats[run.run_id]}
              latest={i === 0}
              onRerun={onDiscover}
              rerunDisabled={starting || anyRunning}
            />
          ))}
        </div>
      )}
    </div>
  )
}

/** One discovery run as a single top-to-bottom story: a status pill, the one number that matters
 * (how many are ready to search) shown big with a progress bar over how many were pulled, a
 * plain-English line for anything that didn't make it, and a one-line cost footer. The newest run
 * is "Latest discovery"; older ones show their date. */
function DiscoveryRunCard({
  run,
  stats,
  latest,
  onRerun,
  rerunDisabled,
}: {
  run: RunSummary
  stats: ScrapeStats | undefined
  latest: boolean
  onRerun: () => void
  rerunDisabled: boolean
}) {
  const running = !!stats?.running.includes(DISCOVERY_PLATFORM)
  const collected = stats?.tiktok_scraped ?? 0
  const ready = stats?.tiktok_searchable ?? 0
  const processing = stats?.tiktok_processing ?? 0
  // The discovery scrape ran out of Apify/OpenRouter credits — refill and re-run to finish.
  const creditError = running ? null : stats?.tiktok_scrape_error ?? null
  // Items pulled but stuck unprocessed with nothing running = the job was killed mid-enrichment.
  // The backend auto-resumes leftovers on its next restart; until then, show the truth, not "Done".
  const interrupted = !running && !creditError && processing > 0
  const state: 'running' | 'error' | 'interrupted' | 'done' =
    running ? 'running' : creditError ? 'error' : interrupted ? 'interrupted' : 'done'

  const title = latest ? 'Latest discovery' : `Discovery · ${dateTime(run.created_at)}`
  const pct = collected > 0 ? Math.round((ready / collected) * 100) : 0
  // Reasons exclude "still loading" while interrupted — the amber note below says that more clearly.
  const reasons = enrichmentReasons(platformBreakdown(stats, 'tiktok')).filter((r) => !(interrupted && r.label === 'loading'))

  return (
    <div className="flex flex-col gap-4 rounded-xl border border-border bg-card p-5">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <StatusPill state={state} />
          <h2 className="text-sm font-medium text-muted-foreground">{title}</h2>
        </div>
        <Link href="/search" className={buttonVariants({ variant: 'outline', size: 'sm' }) + ' gap-1.5'}>
          View in Search <ArrowRight className="size-3.5" />
        </Link>
      </div>

      {collected === 0 ? (
        <div className="flex flex-col gap-2 py-1">
          <span className="text-sm text-muted-foreground">
            {running ? 'Pulling viral TikToks…' : 'Nothing pulled yet.'}
          </span>
          <ProgressBar pct={0} indeterminate={running} />
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-semibold tabular-nums text-[#9d1555]">{ready}</span>
            <span className="text-sm font-medium">ready to search</span>
          </div>
          <ProgressBar pct={pct} />
          <span className="text-xs text-muted-foreground">of {collected} pulled</span>
          {reasons.length > 0 && (
            <p className="flex flex-wrap gap-x-3 gap-y-0.5 text-[11px]">
              {reasons.map((r) => (
                <span key={r.label} className={r.cls}>
                  {r.text}
                </span>
              ))}
            </p>
          )}
        </div>
      )}

      {interrupted && (
        <div className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-700">
          {processing} item{processing === 1 ? '' : 's'} pulled but not yet made searchable — the job was
          killed before finishing. The server re-runs the leftover work when it next restarts; this panel
          will update once it does.
        </div>
      )}

      {creditError && (
        <div className="flex flex-col gap-2 rounded-md border border-amber-500/50 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-500">
          <span className="flex items-center gap-1.5 font-medium">
            <Wallet className="size-3.5" /> {creditError}
          </span>
          <Button
            onClick={onRerun}
            disabled={rerunDisabled}
            size="sm"
            variant="outline"
            className="h-7 self-start gap-1.5 border-amber-500/50 text-amber-700 hover:bg-amber-500/10 dark:text-amber-500"
          >
            {rerunDisabled ? <Loader2 className="size-3.5 animate-spin" /> : <Wallet className="size-3.5" />}
            Refill &amp; re-run
          </Button>
        </div>
      )}

      <RunFooter runId={run.run_id} stats={stats} />
    </div>
  )
}

/** Where the run stands, in one glance: spinning while pulling, amber if interrupted, green once done. */
function StatusPill({ state }: { state: 'running' | 'error' | 'interrupted' | 'done' }) {
  if (state === 'running') {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-[#9d1555]/10 px-2.5 py-0.5 text-xs font-medium text-[#9d1555]">
        <Loader2 className="size-3.5 animate-spin" /> In progress
      </span>
    )
  }
  if (state === 'error') {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-500/10 px-2.5 py-0.5 text-xs font-medium text-amber-700 dark:text-amber-500">
        <Wallet className="size-3.5" /> Out of credits
      </span>
    )
  }
  if (state === 'interrupted') {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-500/10 px-2.5 py-0.5 text-xs font-medium text-amber-700">
        <AlertTriangle className="size-3.5" /> Interrupted
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/10 px-2.5 py-0.5 text-xs font-medium text-emerald-600">
      <CheckCircle2 className="size-3.5" /> Done
    </span>
  )
}

/** Every pull this run has done and what each cost (Apify + enrichment + embeddings, summed).
 * Discovery reuses one run, so each "Discover" click is its own scrape — list them all (date ·
 * items pulled · cost), newest first, plus a summed total, rather than only the latest. A cost is
 * an estimate while running / unreconciled (marked "~"), exact once the run settles. Refetches
 * whenever the run's state changes so a just-finished run's real cost lands. */
function RunFooter({
  runId,
  stats,
}: {
  runId: string
  stats: ScrapeStats | undefined
}) {
  const refreshKey = [stats?.running.join(','), stats?.tiktok_last_scraped].join('|')
  const data = useScrapeEvents(runId, refreshKey)

  const events = data?.events ?? []
  const anyEstimate = events.some((e) => e.cost_kind === 'estimate')
  const total = data ? `${anyEstimate ? '~' : ''}${money(data.total_spent_usd)}` : '—'

  // An interrupted pull never recorded its own count (the killed worker lost it). When exactly one
  // pull is missing its count, it's just the run total minus the counts we do have — so fill it in
  // rather than leaving a blank. With two+ unknowns the remainder can't be split, so we show "—".
  const knownItems = events.reduce((s, e) => s + (e.items ?? 0), 0)
  const unknownCount = events.filter((e) => e.items == null).length
  const inferred = unknownCount === 1 ? Math.max(0, (stats?.tiktok_scraped ?? 0) - knownItems) : null

  return (
    <div className="flex flex-col gap-2 border-t border-border pt-3 text-xs text-muted-foreground">
      <div className="flex items-center justify-between font-medium text-foreground/80">
        <span>{events.length} pull{events.length === 1 ? '' : 's'}</span>
        <span className="flex items-center gap-1.5">
          total {total}
          <CostInfo />
        </span>
      </div>
      {events.length > 0 && (
        <ul className="flex flex-col gap-1">
          {events.map((e) => {
            const count = e.items != null ? e.items : inferred
            return (
              <li key={e.id} className="flex items-center justify-between gap-2 tabular-nums">
                <span>{dateTime(e.when)}</span>
                <span className="flex items-center gap-3">
                  <span
                    title={
                      e.items == null && count != null
                        ? 'Inferred from the run total — this pull was interrupted before recording its own count'
                        : undefined
                    }
                  >
                    {count == null ? '—' : `${count} pulled`}
                  </span>
                  <span className="w-14 text-right text-foreground/80">
                    {e.cost_kind === 'estimate' ? '~' : ''}
                    {money(e.cost_usd)}
                  </span>
                </span>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

/** A small "?" that explains what the cost figure includes. The numbers come from costs.py: Apify
 * reports a real USD scrape cost; the LLM enrichment and embeddings only log tokens, so those are
 * priced from a per-model rate table. While a pull runs the figure is a rough per-item estimate
 * (shown with "~"); once it finishes it's reconciled to the actual API spend. */
function CostInfo() {
  return (
    <HelpPopover
      ariaLabel="How cost is computed"
      wrapperClassName="inline-flex items-center"
      triggerClassName="inline-flex size-4 items-center justify-center rounded-full focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      iconClassName="size-3.5"
      panelClassName="bottom-full right-0 mb-1 w-72 font-normal leading-relaxed"
    >
      Cost is the real spend for each pull: Apify&apos;s reported scrape cost, plus the LLM
      enrichment (Gemini) and embeddings (Voyage) priced from the tokens they used — summed across
      the whole chain. While a pull is running it&apos;s a rough estimate (marked &ldquo;~&rdquo;);
      once it finishes it&apos;s reconciled to the actual API spend.
    </HelpPopover>
  )
}
