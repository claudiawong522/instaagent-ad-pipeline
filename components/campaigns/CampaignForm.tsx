'use client'

import { useState } from 'react'
import Link from 'next/link'
import { Check, Loader2, Plus } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { Campaign, UpdateCampaignInput } from '@/lib/types'

const MARKETING_GOALS = ['Awareness', 'Traffic', 'Engagement', 'Leads', 'App promotion', 'Sales']
const NAME_MAX = 120
const OBJECTIVE_MAX = 800

/** The trimmed payload the form submits — the same shape create (POST) and edit (PATCH) send. */
export type CampaignFormValues = UpdateCampaignInput

/** One campaign form for both flows: the New Campaign page ('create': numbered full-width
 * sections) and the inline card editor ('edit': compact grid, pre-filled). Same fields and
 * validation; only initial values, layout chrome, and the submit handler differ. On success the
 * caller navigates away / unmounts the form, so the busy state is left on. */
export function CampaignForm({
  variant,
  initial,
  onSubmit,
  onCancel,
}: {
  variant: 'create' | 'edit'
  initial?: Campaign
  onSubmit: (values: CampaignFormValues) => Promise<void>
  onCancel?: () => void // edit only; create cancels via the link back to /campaigns
}) {
  const [productName, setProductName] = useState(initial?.product_name ?? '')
  const [category, setCategory] = useState(initial?.category ?? '')
  const [targetMarket, setTargetMarket] = useState(initial?.target_market ?? '')
  const [notes, setNotes] = useState(initial?.description ?? '')
  const [campaignName, setCampaignName] = useState(initial?.campaign_name ?? '')
  const [goals, setGoals] = useState<Set<string>>(new Set(initial?.marketing_goals ?? []))
  const [objective, setObjective] = useState(initial?.campaign_objective ?? '')
  const [busy, setBusy] = useState(false)
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
    setBusy(true)
    setError(null)
    try {
      await onSubmit({
        product_name: productName.trim(),
        category: category.trim() || null,
        target_market: targetMarket.trim() || null,
        notes: notes.trim() || null,
        campaign_name: campaignName.trim(),
        marketing_goals: Array.from(goals),
        campaign_objective: objective.trim() || null,
      })
    } catch (e) {
      setError(e instanceof Error ? e.message : variant === 'create' ? 'Failed to create campaign' : 'Failed to save')
      setBusy(false)
    }
  }

  const canSubmit = productName.trim().length > 0 && campaignName.trim().length > 0 && !busy

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (canSubmit) submit()
  }

  if (variant === 'edit') {
    return (
      <form onSubmit={handleSubmit} className="flex flex-col gap-3 rounded-md bg-muted/50 p-3 text-xs">
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
          <Button type="submit" size="sm" disabled={!canSubmit} className="h-7 gap-1 px-3 text-xs">
            {busy ? <Loader2 className="size-3 animate-spin" /> : <Check className="size-3" />}
            {busy ? 'Saving…' : 'Save'}
          </Button>
          <Button type="button" size="sm" variant="ghost" onClick={onCancel} className="h-7 px-3 text-xs">
            Cancel
          </Button>
        </div>
      </form>
    )
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5 rounded-xl border border-border bg-card p-5">
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
        <Button type="submit" disabled={!canSubmit}>
          {busy ? <Loader2 className="size-4 animate-spin" /> : <Plus className="size-4" />}
          {busy ? 'Creating…' : 'Create campaign'}
        </Button>
        <Link href="/campaigns" className="text-sm text-muted-foreground hover:text-foreground">
          Cancel
        </Link>
      </div>
    </form>
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

function EditField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[11px] font-medium text-muted-foreground">{label}</span>
      {children}
    </label>
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
