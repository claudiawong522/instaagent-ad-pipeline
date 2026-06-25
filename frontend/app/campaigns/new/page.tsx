'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { Loader2, Plus, ArrowLeft } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { createCampaign } from '@/lib/api'

const MARKETING_GOALS = ['Awareness', 'Traffic', 'Engagement', 'Leads', 'App promotion', 'Sales']
const NAME_MAX = 120
const OBJECTIVE_MAX = 800

export default function NewCampaignPage() {
  const router = useRouter()

  const [productName, setProductName] = useState('')
  const [category, setCategory] = useState('')
  const [targetMarket, setTargetMarket] = useState('')
  const [notes, setNotes] = useState('')
  const [campaignName, setCampaignName] = useState('')
  const [goals, setGoals] = useState<Set<string>>(new Set())
  const [objective, setObjective] = useState('')
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function toggleGoal(g: string) {
    setGoals((s) => {
      const next = new Set(s)
      if (next.has(g)) next.delete(g)
      else next.add(g)
      return next
    })
  }

  async function submit() {
    setCreating(true)
    setError(null)
    try {
      await createCampaign({
        product_name: productName.trim(),
        category: category.trim() || null,
        target_market: targetMarket.trim() || null,
        notes: notes.trim() || null,
        campaign_name: campaignName.trim(),
        marketing_goals: Array.from(goals),
        campaign_objective: objective.trim() || null,
      })
      // back to the list, where the new campaign appears and can be scraped
      router.push('/campaigns')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to create campaign')
      setCreating(false)
    }
  }

  const canCreate = productName.trim().length > 0 && campaignName.trim().length > 0 && !creating

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <div className="space-y-1">
        <Link href="/campaigns" className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
          <ArrowLeft className="size-3.5" /> Back to campaigns
        </Link>
        <h1 className="text-2xl font-semibold tracking-tight">New campaign</h1>
        <p className="text-sm text-muted-foreground">
          Set up a product + campaign. After creating, you can scrape competitor ads, reels, and TikToks.
        </p>
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault()
          if (canCreate) submit()
        }}
        className="space-y-5 rounded-xl border border-border bg-card p-5"
      >
        <Section num="01" title="Product">
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
                    active ? 'border-primary bg-primary/10 text-foreground' : 'border-border text-muted-foreground hover:text-foreground',
                  )}
                >
                  {g}
                </button>
              )
            })}
          </div>
        </Section>

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

        {error && (
          <div className="rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm text-destructive">{error}</div>
        )}

        <div className="flex items-center gap-3">
          <Button type="submit" disabled={!canCreate}>
            {creating ? <Loader2 className="size-4 animate-spin" /> : <Plus className="size-4" />}
            {creating ? 'Creating…' : 'Create campaign'}
          </Button>
          <Link href="/campaigns" className="text-sm text-muted-foreground hover:text-foreground">
            Cancel
          </Link>
        </div>
      </form>
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
