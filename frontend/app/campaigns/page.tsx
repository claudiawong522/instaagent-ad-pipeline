'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { Loader2, Plus, Facebook, Instagram, Music2 } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import {
  listProducts,
  listCampaigns,
  createCampaign,
  getScrapeStats,
  triggerScrape,
  type ScrapePlatform,
} from '@/lib/api'
import type { Campaign, Product, ScrapeStats } from '@/lib/types'

const MARKETING_GOALS = ['Awareness', 'Traffic', 'Engagement', 'Leads', 'App promotion', 'Sales']
const NAME_MAX = 120
const OBJECTIVE_MAX = 800

export default function CampaignsPage() {
  // --- create form state ---
  const [productName, setProductName] = useState('')
  const [category, setCategory] = useState('')
  const [targetMarket, setTargetMarket] = useState('')
  const [notes, setNotes] = useState('')
  const [campaignName, setCampaignName] = useState('')
  const [goals, setGoals] = useState<Set<string>>(new Set())
  const [objective, setObjective] = useState('')
  const [paidTarget, setPaidTarget] = useState('50')
  const [ugcTarget, setUgcTarget] = useState('50')
  const [creating, setCreating] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [formNotice, setFormNotice] = useState<string | null>(null)

  // --- data state ---
  const [products, setProducts] = useState<Product[]>([])
  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  const [stats, setStats] = useState<Record<string, ScrapeStats>>({})

  const refreshProducts = useCallback(() => {
    listProducts().then((r) => setProducts(r.products)).catch(() => {})
  }, [])

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
    refreshProducts()
    refreshCampaigns().catch(() => {})
  }, [refreshProducts, refreshCampaigns])

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
      // Drop runs that have finished (no longer running) from the manual poll set.
      pollRef.current.forEach((rid) => {
        if (stats[rid] && stats[rid].running.length === 0) pollRef.current.delete(rid)
      })
    }, 3000)
    return () => clearInterval(id)
  }, [stats, refreshStats])

  function toggleGoal(g: string) {
    setGoals((s) => {
      const next = new Set(s)
      next.has(g) ? next.delete(g) : next.add(g)
      return next
    })
  }

  function prefillFromProduct(p: Product) {
    setProductName(p.name)
    setCategory(p.category ?? '')
    setTargetMarket(p.target_market ?? '')
    setNotes(p.notes ?? '')
  }

  async function submit() {
    setCreating(true)
    setFormError(null)
    setFormNotice(null)
    try {
      const res = await createCampaign({
        product_name: productName.trim(),
        category: category.trim() || null,
        target_market: targetMarket.trim() || null,
        notes: notes.trim() || null,
        campaign_name: campaignName.trim(),
        marketing_goals: Array.from(goals),
        campaign_objective: objective.trim() || null,
        target_paid_count: Math.max(1, Number(paidTarget) || 50),
        target_ugc_count: Math.max(1, Number(ugcTarget) || 50),
      })
      setFormNotice(
        res.warning
          ? `Campaign created, but ${res.warning}. You can still scrape once keywords exist.`
          : `Campaign created with ${res.keyword_count} keyword${res.keyword_count === 1 ? '' : 's'}. Scroll down to scrape.`,
      )
      // reset campaign-specific fields, keep product for convenience
      setCampaignName('')
      setGoals(new Set())
      setObjective('')
      refreshProducts()
      await refreshCampaigns()
    } catch (e) {
      setFormError(e instanceof Error ? e.message : 'Failed to create campaign')
    } finally {
      setCreating(false)
    }
  }

  async function onScrape(runId: string, platform: ScrapePlatform) {
    pollRef.current.add(runId)
    // optimistic: show the spinner immediately
    setStats((prev) => ({
      ...prev,
      [runId]: {
        ...(prev[runId] ?? { run_id: runId, facebook_ads: 0, instagram_reels: 0, tiktoks: 0, running: [] }),
        running: Array.from(new Set([...(prev[runId]?.running ?? []), platform])),
      },
    }))
    try {
      await triggerScrape(runId, platform)
    } catch {
      // ignore; the poll will reconcile the real state
    }
    refreshStats([runId])
  }

  const canCreate = productName.trim().length > 0 && campaignName.trim().length > 0 && !creating

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Campaigns</h1>
        <p className="text-sm text-muted-foreground">
          Set up a product + campaign, then scrape competitor Facebook ads, Instagram reels, and TikToks.
        </p>
      </div>

      {/* ---------- Create campaign ---------- */}
      <form
        onSubmit={(e) => {
          e.preventDefault()
          if (canCreate) submit()
        }}
        className="space-y-5 rounded-xl border border-border bg-card p-5"
      >
        {/* 01 Product */}
        <Section num="01" title="Product">
          {products.length > 0 && (
            <div className="mb-3 flex flex-wrap gap-2">
              {products.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => prefillFromProduct(p)}
                  className="rounded-md border border-border px-2.5 py-1 text-xs text-muted-foreground hover:border-accent hover:text-foreground"
                  title="Use this product's details"
                >
                  {p.name}
                  {p.category ? ` · ${p.category}` : ''}
                </button>
              ))}
            </div>
          )}
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Product name *">
              <Input value={productName} onChange={(e) => setProductName(e.target.value)} placeholder="QV Face Gentle Cleanser" />
            </Field>
            <Field label="Category">
              <Input value={category} onChange={(e) => setCategory(e.target.value)} placeholder="skincare" />
            </Field>
            <Field label="Target market">
              <Input value={targetMarket} onChange={(e) => setTargetMarket(e.target.value)} placeholder="HK / APAC, sensitive-skin" />
            </Field>
            <Field label="Description">
              <Input value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="soap-free creamy facial cleanser…" />
            </Field>
          </div>
        </Section>

        {/* 02 Campaign name */}
        <Section num="02" title="Name your campaign">
          <div className="relative">
            <Input
              value={campaignName}
              onChange={(e) => setCampaignName(e.target.value.slice(0, NAME_MAX))}
              placeholder="QV Summer Product Launch"
            />
            <span className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-xs text-muted-foreground">
              {campaignName.length}/{NAME_MAX}
            </span>
          </div>
        </Section>

        {/* 03 Marketing goal */}
        <Section num="03" title="Marketing goal">
          <div className="flex flex-wrap gap-2">
            {MARKETING_GOALS.map((g) => {
              const active = goals.has(g)
              return (
                <button
                  key={g}
                  type="button"
                  onClick={() => toggleGoal(g)}
                  className={cn(
                    'rounded-lg border px-4 py-2 text-sm transition-colors',
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
        </Section>

        {/* 04 Campaign objective */}
        <Section num="04" title="Campaign objective">
          <div className="relative">
            <Textarea
              value={objective}
              onChange={(e) => setObjective(e.target.value.slice(0, OBJECTIVE_MAX))}
              placeholder="What should the creative show and achieve? e.g. clear on-camera application of the cleanser with the new bottle prominently featured…"
              className="min-h-28 pr-14"
            />
            <span className="pointer-events-none absolute bottom-2 right-3 text-xs text-muted-foreground">
              {objective.length}/{OBJECTIVE_MAX}
            </span>
          </div>
        </Section>

        {/* 05 Scrape targets */}
        <Section num="05" title="Scrape targets">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Facebook ads to scrape">
              <Input type="number" min={1} value={paidTarget} onChange={(e) => setPaidTarget(e.target.value)} className="w-32" />
            </Field>
            <Field label="UGC videos (reels + TikTok)">
              <Input type="number" min={1} value={ugcTarget} onChange={(e) => setUgcTarget(e.target.value)} className="w-32" />
            </Field>
          </div>
        </Section>

        {formError && (
          <div className="rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm text-destructive">{formError}</div>
        )}
        {formNotice && (
          <div className="rounded-md border border-emerald-500/40 bg-emerald-500/5 px-3 py-2 text-sm text-emerald-700 dark:text-emerald-400">
            {formNotice}
          </div>
        )}

        <div className="flex items-center gap-3">
          <Button type="submit" disabled={!canCreate}>
            {creating ? <Loader2 className="size-4 animate-spin" /> : <Plus className="size-4" />}
            {creating ? 'Creating…' : 'Create campaign'}
          </Button>
          <span className="text-xs text-muted-foreground">
            Creating a campaign generates search keywords; then you can kick off scraping below.
          </span>
        </div>
      </form>

      {/* ---------- Tracker ---------- */}
      <div className="space-y-3">
        <h2 className="text-lg font-semibold">Your campaigns ({campaigns.length})</h2>
        {campaigns.length === 0 ? (
          <p className="py-10 text-center text-sm text-muted-foreground">No campaigns yet — create one above.</p>
        ) : (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {campaigns.map((c) => (
              <CampaignCard key={c.run_id} campaign={c} stats={stats[c.run_id]} onScrape={onScrape} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function Section({ num, title, children }: { num: string; title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <div className="flex items-center gap-2">
        <span className="rounded bg-muted px-1.5 py-0.5 text-xs font-semibold text-muted-foreground">{num}</span>
        <h3 className="text-sm font-semibold">{title}</h3>
      </div>
      {children}
    </section>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      {children}
    </label>
  )
}

type NumericStatKey = 'facebook_ads' | 'instagram_reels' | 'tiktoks'
const PLATFORMS: { key: ScrapePlatform; label: string; icon: typeof Facebook; statKey: NumericStatKey }[] = [
  { key: 'facebook', label: 'Facebook ads', icon: Facebook, statKey: 'facebook_ads' },
  { key: 'instagram', label: 'Instagram reels', icon: Instagram, statKey: 'instagram_reels' },
  { key: 'tiktok', label: 'TikToks', icon: Music2, statKey: 'tiktoks' },
]

function CampaignCard({
  campaign: c,
  stats,
  onScrape,
}: {
  campaign: Campaign
  stats: ScrapeStats | undefined
  onScrape: (runId: string, platform: ScrapePlatform) => void
}) {
  return (
    <div className="flex flex-col gap-3 rounded-xl border border-border bg-card p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="font-medium">{c.campaign_name || '(unnamed campaign)'}</div>
          <div className="text-xs text-muted-foreground">
            {c.product_name || 'unknown product'}
            {c.category ? ` · ${c.category}` : ''}
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

      {/* Scraped counts + kick-off buttons */}
      <div className="grid grid-cols-3 gap-2 border-t border-border pt-3">
        {PLATFORMS.map(({ key, label, icon: Icon, statKey }) => {
          const count = stats?.[statKey] ?? 0
          const running = stats?.running.includes(key) ?? false
          return (
            <div key={key} className="flex flex-col items-center gap-1.5 text-center">
              <div className="flex items-baseline gap-1">
                <span className="text-xl font-semibold tabular-nums">{count}</span>
              </div>
              <span className="text-[11px] text-muted-foreground">{label} scraped</span>
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={running}
                onClick={() => onScrape(c.run_id, key)}
                className="h-7 w-full gap-1 px-2 text-xs"
              >
                {running ? <Loader2 className="size-3 animate-spin" /> : <Icon className="size-3" />}
                {running ? 'Scraping…' : 'Scrape'}
              </Button>
            </div>
          )
        })}
      </div>
    </div>
  )
}
