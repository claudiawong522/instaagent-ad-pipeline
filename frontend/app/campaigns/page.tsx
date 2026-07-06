'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { Loader2, Plus, Facebook, Instagram, Music2, ChevronDown, ChevronUp, AlertTriangle, Pencil, Clock, Wallet } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Button, buttonVariants } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { ProgressBar } from '@/components/ui/progress-bar'
import { listCampaigns, triggerScrape, updateCampaign } from '@/lib/api'
import type { Campaign, ScrapePlatform, ScrapeStats } from '@/lib/types'
import { dateTime, money, timeAgo } from '@/lib/format'
import { emptyStats, enrichmentReasons, platformBreakdown, type PlatformCounts } from '@/lib/scrape'
import { useScrapeEvents, useScrapeStatsPolling } from '@/lib/useScrapeStatsPolling'
import { CampaignForm } from '@/components/campaigns/CampaignForm'

// Rough blended $/item (Apify + enrichment + embedding) for the pre-scrape estimate. Mirror of
// EST_COST_PER_ITEM_USD in src/instaagent_pipeline/costs.py — keep the two in sync.
const COST_PER_ITEM_USD: Record<ScrapePlatform, number> = { facebook: 0.012, instagram: 0.01, tiktok: 0.01 }

// A campaign with any platform mid-scrape keeps getting polled until it settles.
const anyPlatformRunning = (s: ScrapeStats) => s.running.length > 0

export default function CampaignsPage() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  const [loading, setLoading] = useState(true)
  const { stats, setStats, refreshStats, watch } = useScrapeStatsPolling(anyPlatformRunning, 3000)

  const refreshCampaigns = useCallback(async () => {
    const r = await listCampaigns()
    setCampaigns(r.campaigns)
    refreshStats(r.campaigns.map((c) => c.run_id))
  }, [refreshStats])

  useEffect(() => {
    refreshCampaigns()
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [refreshCampaigns])

  async function onScrape(runId: string, platform: ScrapePlatform, targetCount: number, estimatedCost: number) {
    watch(runId)
    // optimistic: show the spinner immediately
    setStats((prev) => ({
      ...prev,
      [runId]: {
        ...(prev[runId] ?? emptyStats(runId)),
        running: Array.from(new Set([...(prev[runId]?.running ?? []), platform])),
      },
    }))
    try {
      await triggerScrape(runId, platform, targetCount, estimatedCost)
    } catch {
      // ignore; the poll will reconcile the real state
    }
    refreshStats([runId])
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Campaigns</h1>
          <p className="text-sm text-muted-foreground">
            Your products + campaigns. Open one to scrape competitor Facebook ads, reels, and TikToks.
          </p>
        </div>
        <Link href="/campaigns/new" className={buttonVariants()}>
          <Plus className="size-4" /> New Campaign
        </Link>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20 text-muted-foreground">
          <Loader2 className="mr-2 size-5 animate-spin" /> Loading…
        </div>
      ) : campaigns.length === 0 ? (
        <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-border py-16 text-center">
          <p className="text-sm text-muted-foreground">No campaigns yet.</p>
          <Link href="/campaigns/new" className={buttonVariants()}>
            <Plus className="size-4" /> Create your first campaign
          </Link>
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          {campaigns.map((c) => (
            <CampaignCard key={c.run_id} campaign={c} stats={stats[c.run_id]} onScrape={onScrape} onSaved={refreshCampaigns} />
          ))}
        </div>
      )}
    </div>
  )
}

type NumericStatKey = 'facebook_ads' | 'instagram_reels' | 'tiktoks'
type LastScrapedKey = 'facebook_last_scraped' | 'instagram_last_scraped' | 'tiktok_last_scraped'
type FailedKey = 'facebook_scrape_failed' | 'instagram_scrape_failed' | 'tiktok_scrape_failed'
type ErrorKey = 'facebook_scrape_error' | 'instagram_scrape_error' | 'tiktok_scrape_error'
const PLATFORMS: {
  key: ScrapePlatform
  label: string
  icon: typeof Facebook
  statKey: NumericStatKey
  lastKey: LastScrapedKey
  failedKey: FailedKey
  errorKey: ErrorKey
}[] = [
  { key: 'facebook', label: 'Facebook ads', icon: Facebook, statKey: 'facebook_ads', lastKey: 'facebook_last_scraped', failedKey: 'facebook_scrape_failed', errorKey: 'facebook_scrape_error' },
  { key: 'instagram', label: 'Instagram reels', icon: Instagram, statKey: 'instagram_reels', lastKey: 'instagram_last_scraped', failedKey: 'instagram_scrape_failed', errorKey: 'instagram_scrape_error' },
  { key: 'tiktok', label: 'TikToks', icon: Music2, statKey: 'tiktoks', lastKey: 'tiktok_last_scraped', failedKey: 'tiktok_scrape_failed', errorKey: 'tiktok_scrape_error' },
]

function CampaignCard({
  campaign: c,
  stats,
  onScrape,
  onSaved,
}: {
  campaign: Campaign
  stats: ScrapeStats | undefined
  onScrape: (runId: string, platform: ScrapePlatform, targetCount: number, estimatedCost: number) => void
  onSaved: () => void
}) {
  const [showInputs, setShowInputs] = useState(false)
  const [editing, setEditing] = useState(false)
  return (
    <div className="flex flex-col gap-3 rounded-xl border border-border bg-card p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="font-medium">{c.campaign_name || '(unnamed campaign)'}</div>
          <div className="text-xs text-muted-foreground">
            {c.product_name || 'unknown product'}
            {c.category ? ` · ${c.category}` : ''}
            {c.created_at ? ` · created ${timeAgo(c.created_at)}` : ''}
          </div>
        </div>
        {c.status && <Badge variant={c.status === 'failed' ? 'destructive' : 'secondary'}>{c.status}</Badge>}
      </div>

      {c.marketing_goals.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {c.marketing_goals.map((g) => (
            <Badge key={g} variant="outline">
              {g}
            </Badge>
          ))}
        </div>
      )}

      {/* Reveal scrape cost history + previously-entered inputs */}
      <button
        type="button"
        onClick={() => setShowInputs((v) => !v)}
        className="flex items-center gap-1 self-start text-xs font-medium text-muted-foreground hover:text-foreground"
      >
        {showInputs ? <ChevronUp className="size-3.5" /> : <ChevronDown className="size-3.5" />}
        {showInputs ? 'Hide details' : 'Show details'}
      </button>
      {showInputs && (
        <div className="flex flex-col gap-3">
          <ScrapeHistory runId={c.run_id} stats={stats} />
          <EnrichmentBreakdown stats={stats} />
          {editing ? (
            // Inline editor — the shared form, pre-filled; saves via PATCH /campaigns/{run_id},
            // then the parent refetches the list.
            <CampaignForm
              variant="edit"
              initial={c}
              onCancel={() => setEditing(false)}
              onSubmit={async (values) => {
                await updateCampaign(c.run_id, values)
                setEditing(false)
                onSaved()
              }}
            />
          ) : (
            <div className="flex flex-col gap-2 rounded-md bg-muted/50 p-3 text-xs">
              <div className="flex items-center justify-between">
                <span className="font-medium text-muted-foreground">Inputs</span>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  onClick={() => setEditing(true)}
                  className="h-6 gap-1 px-2 text-xs"
                >
                  <Pencil className="size-3" /> Edit
                </Button>
              </div>
              <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
                <InputRow label="Product" value={c.product_name} />
                <InputRow label="Category" value={c.category} />
                <InputRow label="Target market" value={c.target_market} />
                <InputRow label="Description" value={c.description} />
                <InputRow label="Campaign" value={c.campaign_name} />
                <InputRow label="Goals" value={c.marketing_goals.join(', ') || null} />
                <InputRow label="Objective" value={c.campaign_objective} />
              </dl>
            </div>
          )}
        </div>
      )}

      {/* Scraped counts + per-platform scrape controls */}
      <div className="grid grid-cols-3 gap-2 border-t border-border pt-3">
        {PLATFORMS.map((p) => (
          <PlatformTile
            key={p.key}
            runId={c.run_id}
            platform={p}
            count={stats?.[p.statKey] ?? 0}
            total={platformBreakdown(stats, p.key).total}
            processing={platformBreakdown(stats, p.key).processing}
            lastScraped={stats?.[p.lastKey] ?? null}
            running={stats?.running.includes(p.key) ?? false}
            failed={stats?.[p.failedKey] ?? false}
            error={stats?.[p.errorKey] ?? null}
            defaultTarget={(p.key === 'facebook' ? c.target_paid_count : p.key === 'tiktok' ? c.target_tiktok_count : c.target_ugc_count) ?? 50}
            onScrape={onScrape}
          />
        ))}
      </div>
    </div>
  )
}

function PlatformTile({
  runId,
  platform: { key, label, icon: Icon },
  count,
  total,
  processing,
  lastScraped,
  running,
  failed,
  error,
  defaultTarget,
  onScrape,
}: {
  runId: string
  platform: (typeof PLATFORMS)[number]
  count: number // searchable videos (the headline number)
  total: number // all scraped videos (searchable + expired + failed + processing)
  processing: number // scraped but not yet enriched/embedded (not searchable yet)
  lastScraped: string | null
  running: boolean
  failed: boolean // last finished scrape attempt errored out
  error: string | null // out-of-credits message for the latest scrape (refill & re-run)
  defaultTarget: number
  onScrape: (runId: string, platform: ScrapePlatform, targetCount: number, estimatedCost: number) => void
}) {
  const [confirming, setConfirming] = useState(false)
  const [target, setTarget] = useState('')
  const scraped = total > 0
  const last = timeAgo(lastScraped)

  // Live estimate: blended $/item × the items this scrape would newly fetch (requested total minus
  // what's already scraped). "Scrape more" past the current count costs ~nothing new but may re-fetch dupes.
  const requested = Math.max(1, Number(target) || defaultTarget)
  const newItems = Math.max(0, requested - total)
  const estCost = newItems * COST_PER_ITEM_USD[key]

  function openConfirm() {
    // new TOTAL to fetch: a real increase over what's there, or the campaign target for a first scrape
    setTarget(String(scraped ? total + 50 : defaultTarget))
    setConfirming(true)
  }

  function confirm() {
    setConfirming(false)
    onScrape(runId, key, requested, Number(estCost.toFixed(4)))
  }

  if (confirming) {
    return (
      <div className="flex flex-col items-center gap-1.5 rounded-md bg-muted/40 p-2 text-center">
        <span className="text-[11px] font-medium">Fetch up to</span>
        <Input
          type="number"
          min={1}
          value={target}
          autoFocus
          onChange={(e) => setTarget(e.target.value)}
          className="h-7 w-20 text-center text-sm"
        />
        <span className="text-[11px] font-medium tabular-nums">
          ≈ {money(estCost)}
          <span className="font-normal text-muted-foreground"> · {newItems} new</span>
        </span>
        <span className="flex items-start gap-1 text-[10px] leading-tight text-amber-600 dark:text-amber-500">
          <AlertTriangle className="mt-px size-3 shrink-0" />
          estimated cost
        </span>
        {key === 'instagram' && (
          <span className="flex items-start gap-1 text-[10px] leading-tight text-amber-600 dark:text-amber-500">
            <AlertTriangle className="mt-px size-3 shrink-0" />
            Re-running mostly returns the same reels, so extra runs barely grow the pool — fetch a
            large batch in one go.
          </span>
        )}
        <span className="text-[10px] leading-tight text-muted-foreground/80">
          Split evenly across the campaign’s keywords, so the final count can land a bit under your
          number (e.g. 50 → ~48). Thin keywords or videoless results lower it further.
        </span>
        <div className="flex w-full gap-1">
          <Button type="button" size="sm" variant="ghost" onClick={() => setConfirming(false)} className="h-6 flex-1 px-1 text-xs">
            Cancel
          </Button>
          <Button type="button" size="sm" onClick={confirm} className="h-6 flex-1 px-1 text-xs">
            Confirm
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col items-center gap-1.5 text-center">
      <span className="text-xl font-semibold tabular-nums text-[#9d1555]">{count}</span>
      <span className="text-[11px] text-muted-foreground">{label} searchable</span>
      {scraped && (
        <>
          <ProgressBar pct={(count / total) * 100} />
          <span className="text-[10px] text-muted-foreground/70">of {total} scraped</span>
        </>
      )}
      {processing > 0 && (
        <span className="flex items-center gap-1 text-[10px] leading-tight text-sky-600 dark:text-sky-400">
          {running ? <Loader2 className="size-3 animate-spin" /> : <Clock className="size-3" />}
          {processing} enriching{running ? '…' : ' (resumes on next scrape)'}
        </span>
      )}
      <span className="text-[10px] text-muted-foreground/80">
        {running ? 'scraping now' : error ? 'out of credits' : failed ? 'last scrape failed' : last ? `last ${last}` : 'not yet'}
      </span>
      {running ? (
        <Button type="button" size="sm" variant="outline" disabled className="h-7 w-full gap-1 px-2 text-xs">
          <Loader2 className="size-3 animate-spin" /> Scraping…
        </Button>
      ) : error ? (
        // Out of credits: tell the user to refill, then the same button re-runs the scrape.
        <div className="flex w-full flex-col items-center gap-1">
          <span className="flex items-center gap-1 text-[11px] font-medium text-amber-600 dark:text-amber-500">
            <Wallet className="size-3" /> Out of credits
          </span>
          <span className="text-[10px] leading-tight text-muted-foreground">{error}</span>
          <Button type="button" size="sm" variant="outline" onClick={openConfirm} className="h-7 w-full gap-1 border-amber-500/50 px-2 text-xs text-amber-700 hover:bg-amber-500/10 dark:text-amber-500">
            <Wallet className="size-3" /> Refill &amp; re-run
          </Button>
        </div>
      ) : failed ? (
        <div className="flex w-full flex-col items-center gap-1">
          <span className="flex items-center gap-1 text-[11px] font-medium text-destructive">
            <AlertTriangle className="size-3" /> Scrape failed{scraped ? ' (partial)' : ''}
          </span>
          <Button type="button" size="sm" variant="destructive" onClick={openConfirm} className="h-7 w-full gap-1 px-2 text-xs">
            <Icon className="size-3" /> Retry scrape
          </Button>
        </div>
      ) : scraped ? (
        <div className="flex w-full flex-col items-center gap-1">
          <span className="text-[11px] font-medium text-emerald-600 dark:text-emerald-500">Scraped ✓</span>
          <Button type="button" size="sm" variant="outline" onClick={openConfirm} className="h-7 w-full gap-1 px-2 text-xs">
            <Icon className="size-3" /> Scrape more
          </Button>
        </div>
      ) : (
        <Button type="button" size="sm" variant="outline" onClick={openConfirm} className="h-7 w-full gap-1 px-2 text-xs">
          <Icon className="size-3" /> Scrape
        </Button>
      )}
    </div>
  )
}

const PLATFORM_LABEL: Record<string, string> = {
  facebook: 'Facebook ads',
  instagram: 'Instagram reels',
  tiktok: 'TikToks',
}

/** Per-scrape cost history: one row per platform scrape, newest-first, each with its date/time and
 * total cost (Apify + enrichment + embeddings, summed). UI scrapes are exact (estimate while
 * running → actual once done); spend from before tracking is reconstructed per-platform. Refetches
 * whenever the campaign's scrape state changes so a just-finished scrape's real cost lands. */
function ScrapeHistory({ runId, stats }: { runId: string; stats: ScrapeStats | undefined }) {
  // Re-fetch on a scrape state change: a platform mid-scrape, or a new last-scraped timestamp.
  const refreshKey = [
    stats?.running.join(','),
    stats?.facebook_last_scraped,
    stats?.instagram_last_scraped,
    stats?.tiktok_last_scraped,
  ].join('|')
  const data = useScrapeEvents(runId, refreshKey)

  if (!data || data.events.length === 0) {
    return (
      <div className="rounded-md bg-muted/50 p-3 text-xs text-muted-foreground">
        No scrapes yet — each scrape and its cost appears here.
      </div>
    )
  }
  const pending = data.events.some((e) => e.cost_kind === 'estimate')
  return (
    <div className="flex flex-col gap-1.5 rounded-md bg-muted/50 p-3 text-xs">
      <div className="font-medium text-muted-foreground">Scrapes &amp; cost</div>
      {data.events.map((e) => {
        const estimate = e.cost_kind === 'estimate'
        return (
          <div key={e.id} className="flex items-baseline justify-between gap-2">
            <span className="text-foreground">
              {PLATFORM_LABEL[e.platform] ?? e.platform}
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

/** Per-platform "collected → ready to search" summary with a plain-English reason for any gap.
 * Shown inside View inputs so you can see how many collected videos are actually usable (videos
 * whose Apify URL expired before enrichment can never become ready). */
function EnrichmentBreakdown({ stats }: { stats: ScrapeStats | undefined }) {
  const rows = PLATFORMS.map((p) => ({ p, b: platformBreakdown(stats, p.key) })).filter((r) => r.b.total > 0)
  if (rows.length === 0) {
    return (
      <div className="rounded-md bg-muted/50 p-3 text-xs text-muted-foreground">
        Nothing collected yet — counts appear here after a scrape.
      </div>
    )
  }
  return (
    <div className="flex flex-col gap-2.5 rounded-md bg-muted/50 p-3 text-xs">
      <div className="font-medium text-muted-foreground">Ready to search</div>
      {rows.map(({ p, b }) => (
        <SearchableRow key={p.key} label={p.label} b={b} />
      ))}
    </div>
  )
}

/** One platform's plain-English summary: how many videos we collected vs how many are ready to
 * search, with a one-line reason for anything in between. Compact so three platforms stack
 * cleanly; the reasons come from the shared enrichmentReasons, so the wording matches the
 * Discover summary exactly (no jargon, no internal denominators). */
function SearchableRow({ label, b }: { label: string; b: PlatformCounts }) {
  const reasons = enrichmentReasons(b)
  const pct = b.scraped > 0 ? (b.searchable / b.scraped) * 100 : 0
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-foreground">{label}</span>
        <span className="tabular-nums text-muted-foreground">
          <span className="font-medium text-foreground">{b.searchable}</span> of {b.scraped} ready to search
        </span>
      </div>
      <ProgressBar pct={pct} />
      {reasons.length === 0 ? (
        <span className="text-[11px] text-emerald-600 dark:text-emerald-500">✓ all ready to search</span>
      ) : (
        <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[11px]">
          {reasons.map((r) => (
            <span key={r.label} className={r.cls}>
              {r.text}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

function InputRow({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <>
      <dt className="font-medium text-muted-foreground">{label}</dt>
      <dd className="text-foreground">{value || <span className="text-muted-foreground/60">—</span>}</dd>
    </>
  )
}
