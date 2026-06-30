'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { Loader2, Plus, Facebook, Instagram, Music2, ChevronDown, ChevronUp, AlertTriangle, Pencil, Check, Clock } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Button, buttonVariants } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { listCampaigns, getScrapeStats, getScrapeEvents, triggerScrape, updateCampaign, type ScrapePlatform } from '@/lib/api'
import type { Campaign, ScrapeStats, ScrapeEventsResponse } from '@/lib/types'

// Rough blended $/item (Apify + enrichment + embedding) for the pre-scrape estimate. Mirror of
// EST_COST_PER_ITEM_USD in src/instaagent_pipeline/costs.py — keep the two in sync.
const COST_PER_ITEM_USD: Record<ScrapePlatform, number> = { facebook: 0.012, instagram: 0.01, tiktok: 0.01 }

/** Format a USD amount compactly: a "<$0.01" floor for tiny spend, 2 decimals otherwise. */
function money(usd: number | null | undefined): string {
  if (usd == null) return '—'
  if (usd > 0 && usd < 0.01) return '<$0.01'
  return `$${usd.toFixed(2)}`
}

export default function CampaignsPage() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  const [stats, setStats] = useState<Record<string, ScrapeStats>>({})
  const [loading, setLoading] = useState(true)

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

  // Poll scrape stats for any campaign with an in-flight scrape until it settles.
  const pollRef = useRef<Set<string>>(new Set())
  useEffect(() => {
    const id = setInterval(() => {
      const active = Object.values(stats)
        .filter((s) => s.running.length > 0)
        .map((s) => s.run_id)
      const toPoll = new Set(active.concat(Array.from(pollRef.current)))
      if (toPoll.size === 0) return
      refreshStats(Array.from(toPoll))
      pollRef.current.forEach((rid) => {
        if (stats[rid] && stats[rid].running.length === 0) pollRef.current.delete(rid)
      })
    }, 3000)
    return () => clearInterval(id)
  }, [stats, refreshStats])

  async function onScrape(runId: string, platform: ScrapePlatform, targetCount: number, estimatedCost: number) {
    pollRef.current.add(runId)
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

/** Compact relative time, e.g. "just now", "5m ago", "3h ago", "2d ago". */
function timeAgo(iso: string | null | undefined): string | null {
  if (!iso) return null
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return null
  const secs = Math.max(0, Math.round((Date.now() - then) / 1000))
  if (secs < 45) return 'just now'
  const mins = Math.round(secs / 60)
  if (mins < 60) return `${mins}m ago`
  const hours = Math.round(mins / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.round(hours / 24)
  return `${days}d ago`
}

/** Zeroed stats for optimistic UI before the first poll returns. */
function emptyStats(runId: string): ScrapeStats {
  return {
    run_id: runId,
    facebook_ads: 0,
    instagram_reels: 0,
    tiktoks: 0,
    facebook_searchable: 0,
    facebook_expired: 0,
    facebook_failed: 0,
    facebook_processing: 0,
    facebook_total: 0,
    facebook_scraped: 0,
    facebook_no_video: 0,
    facebook_last_scraped: null,
    instagram_searchable: 0,
    instagram_expired: 0,
    instagram_failed: 0,
    instagram_processing: 0,
    instagram_total: 0,
    instagram_scraped: 0,
    instagram_no_video: 0,
    instagram_last_scraped: null,
    tiktok_searchable: 0,
    tiktok_expired: 0,
    tiktok_failed: 0,
    tiktok_processing: 0,
    tiktok_total: 0,
    tiktok_scraped: 0,
    tiktok_no_video: 0,
    tiktok_last_scraped: null,
    facebook_scrape_failed: false,
    instagram_scrape_failed: false,
    tiktok_scrape_failed: false,
    running: [],
  }
}

type PlatformPrefix = 'facebook' | 'instagram' | 'tiktok'

/** Pull one platform's enrichment breakdown out of the flat ScrapeStats. */
function pbreak(stats: ScrapeStats | undefined, prefix: PlatformPrefix) {
  const g = (k: string) =>
    stats ? (stats as unknown as Record<string, number>)[`${prefix}_${k}`] ?? 0 : 0
  return {
    searchable: g('searchable'),
    expired: g('expired'),
    failed: g('failed'),
    processing: g('processing'),
    total: g('total'),
    scraped: g('scraped'),
    no_video: g('no_video'),
  }
}

type NumericStatKey = 'facebook_ads' | 'instagram_reels' | 'tiktoks'
type LastScrapedKey = 'facebook_last_scraped' | 'instagram_last_scraped' | 'tiktok_last_scraped'
type FailedKey = 'facebook_scrape_failed' | 'instagram_scrape_failed' | 'tiktok_scrape_failed'
const PLATFORMS: {
  key: ScrapePlatform
  label: string
  icon: typeof Facebook
  statKey: NumericStatKey
  lastKey: LastScrapedKey
  failedKey: FailedKey
}[] = [
  { key: 'facebook', label: 'Facebook ads', icon: Facebook, statKey: 'facebook_ads', lastKey: 'facebook_last_scraped', failedKey: 'facebook_scrape_failed' },
  { key: 'instagram', label: 'Instagram reels', icon: Instagram, statKey: 'instagram_reels', lastKey: 'instagram_last_scraped', failedKey: 'instagram_scrape_failed' },
  { key: 'tiktok', label: 'TikToks', icon: Music2, statKey: 'tiktoks', lastKey: 'tiktok_last_scraped', failedKey: 'tiktok_scrape_failed' },
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
            <CampaignEditor
              campaign={c}
              onCancel={() => setEditing(false)}
              onSaved={() => {
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
            total={pbreak(stats, p.key).total}
            processing={pbreak(stats, p.key).processing}
            lastScraped={stats?.[p.lastKey] ?? null}
            running={stats?.running.includes(p.key) ?? false}
            failed={stats?.[p.failedKey] ?? false}
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
          estimated cost{scraped ? '; may re-fetch dupes' : ''}
        </span>
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
      <span className="text-xl font-semibold tabular-nums">{scraped ? `${count} / ${total}` : count}</span>
      <span className="text-[11px] text-muted-foreground">{label} searchable</span>
      {scraped && (
        <span className="text-[10px] text-muted-foreground/70">of {total} scraped</span>
      )}
      {processing > 0 && (
        <span className="flex items-center gap-1 text-[10px] leading-tight text-sky-600 dark:text-sky-400">
          {running ? <Loader2 className="size-3 animate-spin" /> : <Clock className="size-3" />}
          {processing} enriching{running ? '…' : ' (resumes on next scrape)'}
        </span>
      )}
      <span className="text-[10px] text-muted-foreground/80">
        {running ? 'scraping now' : failed ? 'last scrape failed' : last ? `last ${last}` : 'not yet'}
      </span>
      {running ? (
        <Button type="button" size="sm" variant="outline" disabled className="h-7 w-full gap-1 px-2 text-xs">
          <Loader2 className="size-3 animate-spin" /> Scraping…
        </Button>
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

/** Scrape date/time, e.g. "Jun 23, 6:31 AM". */
function dateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}

/** Per-scrape cost history: one row per platform scrape, newest-first, each with its date/time and
 * total cost (Apify + enrichment + embeddings, summed). UI scrapes are exact (estimate while
 * running → actual once done); spend from before tracking is reconstructed per-platform. Refetches
 * whenever the campaign's scrape state changes so a just-finished scrape's real cost lands. */
function ScrapeHistory({ runId, stats }: { runId: string; stats: ScrapeStats | undefined }) {
  const [data, setData] = useState<ScrapeEventsResponse | null>(null)
  // Re-fetch on a scrape state change: a platform mid-scrape, or a new last-scraped timestamp.
  const refreshKey = [
    stats?.running.join(','),
    stats?.facebook_last_scraped,
    stats?.instagram_last_scraped,
    stats?.tiktok_last_scraped,
  ].join('|')
  useEffect(() => {
    getScrapeEvents(runId)
      .then(setData)
      .catch(() => {})
  }, [runId, refreshKey])

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

/** "X of Y searchable" per platform, with expired/failed/processing breakdown. Shown
 * inside View inputs so you can see how many scraped videos OpenRouter could actually
 * ingest (expired Apify URLs never become searchable). */
function EnrichmentBreakdown({ stats }: { stats: ScrapeStats | undefined }) {
  const rows = PLATFORMS.map((p) => ({ p, b: pbreak(stats, p.key) })).filter((r) => r.b.total > 0)
  if (rows.length === 0) {
    return (
      <div className="rounded-md bg-muted/50 p-3 text-xs text-muted-foreground">
        No videos scraped yet — searchable counts appear here after a scrape.
      </div>
    )
  }
  return (
    <div className="flex flex-col gap-2.5 rounded-md bg-muted/50 p-3 text-xs">
      <div className="font-medium text-muted-foreground">Searchable videos</div>
      {rows.map(({ p, b }) => (
        <SearchableRow key={p.key} label={p.label} b={b} />
      ))}
    </div>
  )
}

/** One platform's scrape → attempt → searchable funnel, compact (inline numbers + loss line) so
 * three platforms stack cleanly. Attempted = searchable + expired + failed (verdict reached);
 * processing / no video haven't been (or can't be) attempted. Mirrors the Discover funnel. */
function SearchableRow({ label, b }: { label: string; b: ReturnType<typeof pbreak> }) {
  const attempted = b.searchable + b.expired + b.failed
  const losses = [
    { label: 'no video', n: b.no_video, cls: 'text-muted-foreground' },
    { label: 'processing', n: b.processing, cls: 'text-muted-foreground' },
    { label: 'expired', n: b.expired, cls: 'text-amber-600 dark:text-amber-500' },
    { label: 'failed', n: b.failed, cls: 'text-red-600 dark:text-red-500' },
  ].filter((l) => l.n > 0)
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between gap-2">
        <span className="text-foreground">{label}</span>
        <span className="tabular-nums text-muted-foreground">
          {b.scraped} scraped <span className="text-muted-foreground/40">→</span> {attempted} attempted{' '}
          <span className="text-muted-foreground/40">→</span>{' '}
          <span className="font-medium text-foreground">{b.searchable} searchable</span>
        </span>
      </div>
      {losses.length === 0 ? (
        <span className="text-[11px] text-emerald-600 dark:text-emerald-500">✓ every scraped video is searchable</span>
      ) : (
        <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[11px]">
          {losses.map((l) => (
            <span key={l.label} className={l.cls}>
              {l.n} {l.label}
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

const MARKETING_GOALS = ['Awareness', 'Traffic', 'Engagement', 'Leads', 'App promotion', 'Sales']
const NAME_MAX = 120
const OBJECTIVE_MAX = 800

/** Inline editor for a campaign's details — same fields as the New Campaign form, pre-filled.
 * Saves via PATCH /campaigns/{run_id}; on success the parent refetches the list. */
function CampaignEditor({
  campaign: c,
  onCancel,
  onSaved,
}: {
  campaign: Campaign
  onCancel: () => void
  onSaved: () => void
}) {
  const [productName, setProductName] = useState(c.product_name ?? '')
  const [category, setCategory] = useState(c.category ?? '')
  const [targetMarket, setTargetMarket] = useState(c.target_market ?? '')
  const [notes, setNotes] = useState(c.description ?? '')
  const [campaignName, setCampaignName] = useState(c.campaign_name ?? '')
  const [goals, setGoals] = useState<Set<string>>(new Set(c.marketing_goals))
  const [objective, setObjective] = useState(c.campaign_objective ?? '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function toggleGoal(g: string) {
    setGoals((s) => {
      const next = new Set(s)
      if (next.has(g)) next.delete(g)
      else next.add(g)
      return next
    })
  }

  async function save() {
    setSaving(true)
    setError(null)
    try {
      await updateCampaign(c.run_id, {
        product_name: productName.trim(),
        category: category.trim() || null,
        target_market: targetMarket.trim() || null,
        notes: notes.trim() || null,
        campaign_name: campaignName.trim(),
        marketing_goals: Array.from(goals),
        campaign_objective: objective.trim() || null,
      })
      onSaved()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save')
      setSaving(false)
    }
  }

  const canSave = productName.trim().length > 0 && campaignName.trim().length > 0 && !saving

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        if (canSave) save()
      }}
      className="flex flex-col gap-3 rounded-md bg-muted/50 p-3 text-xs"
    >
      <div className="grid gap-2 sm:grid-cols-2">
        <EditField label="Product name *">
          <Input value={productName} onChange={(e) => setProductName(e.target.value)} className="h-8 text-sm" />
        </EditField>
        <EditField label="Category">
          <Input value={category} onChange={(e) => setCategory(e.target.value)} className="h-8 text-sm" />
        </EditField>
        <EditField label="Target market">
          <Input value={targetMarket} onChange={(e) => setTargetMarket(e.target.value)} className="h-8 text-sm" />
        </EditField>
        <EditField label="Description">
          <Input value={notes} onChange={(e) => setNotes(e.target.value)} className="h-8 text-sm" />
        </EditField>
        <EditField label="Campaign name *">
          <Input
            value={campaignName}
            onChange={(e) => setCampaignName(e.target.value.slice(0, NAME_MAX))}
            className="h-8 text-sm"
          />
        </EditField>
      </div>
      <EditField label="Marketing goals">
        <div className="flex flex-wrap gap-1.5">
          {MARKETING_GOALS.map((g) => {
            const active = goals.has(g)
            return (
              <button
                key={g}
                type="button"
                onClick={() => toggleGoal(g)}
                className={cn(
                  'rounded-md border px-2.5 py-1 text-xs transition-colors',
                  active
                    ? 'border-primary bg-primary/10 text-foreground'
                    : 'border-border text-muted-foreground hover:text-foreground',
                )}
              >
                {g}
              </button>
            )
          })}
        </div>
      </EditField>
      <EditField label="Objective">
        <Textarea
          value={objective}
          onChange={(e) => setObjective(e.target.value.slice(0, OBJECTIVE_MAX))}
          className="min-h-20 text-sm"
        />
      </EditField>
      {error && (
        <div className="rounded-md border border-destructive/40 bg-destructive/5 px-2 py-1.5 text-destructive">{error}</div>
      )}
      <div className="flex items-center gap-2">
        <Button type="submit" size="sm" disabled={!canSave} className="h-7 gap-1 px-3 text-xs">
          {saving ? <Loader2 className="size-3 animate-spin" /> : <Check className="size-3" />}
          {saving ? 'Saving…' : 'Save'}
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onCancel} className="h-7 px-3 text-xs">
          Cancel
        </Button>
      </div>
    </form>
  )
}

function EditField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[11px] font-medium text-muted-foreground">{label}</span>
      {children}
    </label>
  )
}
