'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { Loader2, Plus, Facebook, Instagram, Music2, ChevronDown, ChevronUp, AlertTriangle } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Button, buttonVariants } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { listCampaigns, getScrapeStats, triggerScrape, type ScrapePlatform } from '@/lib/api'
import type { Campaign, ScrapeStats } from '@/lib/types'

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

  async function onScrape(runId: string, platform: ScrapePlatform, targetCount: number) {
    pollRef.current.add(runId)
    // optimistic: show the spinner immediately
    setStats((prev) => ({
      ...prev,
      [runId]: {
        ...(prev[runId] ?? {
          run_id: runId,
          facebook_ads: 0,
          instagram_reels: 0,
          tiktoks: 0,
          facebook_last_scraped: null,
          instagram_last_scraped: null,
          tiktok_last_scraped: null,
          running: [],
        }),
        running: Array.from(new Set([...(prev[runId]?.running ?? []), platform])),
      },
    }))
    try {
      await triggerScrape(runId, platform, targetCount)
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
            <CampaignCard key={c.run_id} campaign={c} stats={stats[c.run_id]} onScrape={onScrape} />
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

type NumericStatKey = 'facebook_ads' | 'instagram_reels' | 'tiktoks'
type LastScrapedKey = 'facebook_last_scraped' | 'instagram_last_scraped' | 'tiktok_last_scraped'
const PLATFORMS: {
  key: ScrapePlatform
  label: string
  icon: typeof Facebook
  statKey: NumericStatKey
  lastKey: LastScrapedKey
}[] = [
  { key: 'facebook', label: 'Facebook ads', icon: Facebook, statKey: 'facebook_ads', lastKey: 'facebook_last_scraped' },
  { key: 'instagram', label: 'Instagram reels', icon: Instagram, statKey: 'instagram_reels', lastKey: 'instagram_last_scraped' },
  { key: 'tiktok', label: 'TikToks', icon: Music2, statKey: 'tiktoks', lastKey: 'tiktok_last_scraped' },
]

function CampaignCard({
  campaign: c,
  stats,
  onScrape,
}: {
  campaign: Campaign
  stats: ScrapeStats | undefined
  onScrape: (runId: string, platform: ScrapePlatform, targetCount: number) => void
}) {
  const [showInputs, setShowInputs] = useState(false)
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

      {c.campaign_objective && <p className="line-clamp-3 text-xs text-muted-foreground">{c.campaign_objective}</p>}

      {/* View previously-entered inputs */}
      <button
        type="button"
        onClick={() => setShowInputs((v) => !v)}
        className="flex items-center gap-1 self-start text-xs font-medium text-muted-foreground hover:text-foreground"
      >
        {showInputs ? <ChevronUp className="size-3.5" /> : <ChevronDown className="size-3.5" />}
        {showInputs ? 'Hide inputs' : 'View inputs'}
      </button>
      {showInputs && (
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 rounded-md bg-muted/50 p-3 text-xs">
          <InputRow label="Product" value={c.product_name} />
          <InputRow label="Category" value={c.category} />
          <InputRow label="Target market" value={c.target_market} />
          <InputRow label="Description" value={c.description} />
          <InputRow label="Campaign" value={c.campaign_name} />
          <InputRow label="Goals" value={c.marketing_goals.join(', ') || null} />
          <InputRow label="Objective" value={c.campaign_objective} />
          <InputRow label="Scrape targets" value={`${c.target_paid_count ?? '—'} ads · ${c.target_ugc_count ?? '—'} UGC`} />
        </dl>
      )}

      {/* Scraped counts + per-platform scrape controls */}
      <div className="grid grid-cols-3 gap-2 border-t border-border pt-3">
        {PLATFORMS.map((p) => (
          <PlatformTile
            key={p.key}
            runId={c.run_id}
            platform={p}
            count={stats?.[p.statKey] ?? 0}
            lastScraped={stats?.[p.lastKey] ?? null}
            running={stats?.running.includes(p.key) ?? false}
            defaultTarget={(p.key === 'facebook' ? c.target_paid_count : c.target_ugc_count) ?? 50}
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
  lastScraped,
  running,
  defaultTarget,
  onScrape,
}: {
  runId: string
  platform: (typeof PLATFORMS)[number]
  count: number
  lastScraped: string | null
  running: boolean
  defaultTarget: number
  onScrape: (runId: string, platform: ScrapePlatform, targetCount: number) => void
}) {
  const [confirming, setConfirming] = useState(false)
  const [target, setTarget] = useState('')
  const scraped = count > 0
  const last = timeAgo(lastScraped)

  function openConfirm() {
    // new TOTAL to fetch: a real increase over what's there, or the campaign target for a first scrape
    setTarget(String(scraped ? count + 50 : defaultTarget))
    setConfirming(true)
  }

  function confirm() {
    const n = Math.max(1, Number(target) || defaultTarget)
    setConfirming(false)
    onScrape(runId, key, n)
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
        <span className="flex items-start gap-1 text-[10px] leading-tight text-amber-600 dark:text-amber-500">
          <AlertTriangle className="mt-px size-3 shrink-0" />
          costs Apify credits{scraped ? '; may re-fetch dupes' : ''}
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
      <span className="text-xl font-semibold tabular-nums">{count}</span>
      <span className="text-[11px] text-muted-foreground">{label} scraped</span>
      <span className="text-[10px] text-muted-foreground/80">
        {running ? 'scraping now' : last ? `last ${last}` : 'not yet'}
      </span>
      {running ? (
        <Button type="button" size="sm" variant="outline" disabled className="h-7 w-full gap-1 px-2 text-xs">
          <Loader2 className="size-3 animate-spin" /> Scraping…
        </Button>
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

function InputRow({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <>
      <dt className="font-medium text-muted-foreground">{label}</dt>
      <dd className="text-foreground">{value || <span className="text-muted-foreground/60">—</span>}</dd>
    </>
  )
}
