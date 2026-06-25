'use client'

import { useEffect, useState } from 'react'
import { Search, Loader2, X, HelpCircle } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { searchAds, listRuns } from '@/lib/api'
import type { ItemType, RunSummary, VideoResult } from '@/lib/types'

function formatNum(n: number | null | undefined): string {
  if (n == null) return '—'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}

const TYPE_OPTIONS: { label: string; value: ItemType | null }[] = [
  { label: 'All', value: null },
  { label: 'Paid ads', value: 'paid_ad' },
  { label: 'Organic', value: 'ugc_item' },
]

// Enum values mirror src/instaagent_pipeline/audience_enrichment.py (AGE_BRACKETS,
// PRICE_TIERS, CONTENT_FORMATS). Languages are free-form on the backend; these are the common set.
const AGE_BRACKETS = ['13-17', '18-24', '25-34', '35-44', '45-54', '55+']
const LANGUAGES = ['English', 'Spanish', 'Portuguese', 'French', 'German', 'Hindi', 'Arabic', 'Chinese', 'Japanese', 'Korean']
// Production formats — multi-value/overlapping (a video can be several at once).
const CONTENT_FORMATS = ['talking_head', 'ugc', 'product_montage', 'voiceover', 'meme', 'grwm',
  'unboxing', 'tutorial', 'testimonial', 'before_after', 'skit', 'listicle', 'asmr']
const PRICE_TIERS = [
  { label: 'Any price', value: '' },
  { label: 'Budget', value: 'budget' },
  { label: 'Mid', value: 'mid' },
  { label: 'Premium', value: 'premium' },
  { label: 'Luxury', value: 'luxury' },
]

function toggleInSet(set: Set<string>, value: string): Set<string> {
  const next = new Set(set)
  if (next.has(value)) next.delete(value)
  else next.add(value)
  return next
}

// Each ad type has its own winning signal: organic → virality, paid → days live.
// Those scales aren't comparable, so for a mixed list we rank each ad among its
// own type (0–1) and interleave by that rank — the strongest organic and strongest
// paid rise together. With the type filter set to one type, this is just a plain
// descending sort by that type's signal.
function sortByPerformance(items: VideoResult[]): VideoResult[] {
  const signal = (r: VideoResult) =>
    r.item_type === 'paid_ad' ? r.days_live ?? -1 : r.virality ?? -1
  const rank = new Map<VideoResult, number>()
  for (const type of ['paid_ad', 'ugc_item'] as const) {
    const group = items.filter((r) => r.item_type === type)
    const sorted = [...group].sort((a, b) => signal(a) - signal(b))
    sorted.forEach((r, i) => rank.set(r, group.length > 1 ? i / (group.length - 1) : 1))
  }
  return [...items].sort((a, b) => (rank.get(b) ?? 0) - (rank.get(a) ?? 0))
}

export default function SearchPage() {
  const [query, setQuery] = useState('')
  const [itemType, setItemType] = useState<ItemType | null>(null)
  const [platform, setPlatform] = useState<string>('')
  const [runId, setRunId] = useState<string>('')
  const [minViews, setMinViews] = useState<string>('')
  const [minVirality, setMinVirality] = useState<string>('')
  const [minDaysLive, setMinDaysLive] = useState<string>('')
  const [priceTier, setPriceTier] = useState<string>('')
  const [ageBrackets, setAgeBrackets] = useState<Set<string>>(new Set())
  const [languages, setLanguages] = useState<Set<string>>(new Set())
  const [contentFormats, setContentFormats] = useState<Set<string>>(new Set())
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [results, setResults] = useState<VideoResult[]>([])
  const [sortMode, setSortMode] = useState<'relevance' | 'performance'>('relevance')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [searched, setSearched] = useState(false)

  useEffect(() => {
    listRuns()
      .then((r) => setRuns(r.runs))
      .catch(() => setRuns([]))
  }, [])

  async function runSearch() {
    setLoading(true)
    setError(null)
    setSearched(true)
    try {
      const res = await searchAds({
        query: query.trim(),
        item_type: itemType,
        platform: platform || null,
        run_id: runId || null,
        min_views: minViews ? Number(minViews) : null,
        min_virality: minVirality ? Number(minVirality) : null,
        min_days_live: minDaysLive ? Number(minDaysLive) : null,
        price_tier: priceTier || null,
        age_brackets: ageBrackets.size ? Array.from(ageBrackets) : null,
        languages: languages.size ? Array.from(languages) : null,
        content_formats: contentFormats.size ? Array.from(contentFormats) : null,
      })
      setResults(res.results)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Search failed')
      setResults([])
    } finally {
      setLoading(false)
    }
  }

  function clearFilters() {
    setItemType(null)
    setPlatform('')
    setRunId('')
    setMinViews('')
    setMinVirality('')
    setMinDaysLive('')
    setPriceTier('')
    setAgeBrackets(new Set())
    setLanguages(new Set())
    setContentFormats(new Set())
  }

  const filtersActive =
    itemType !== null ||
    platform !== '' ||
    runId !== '' ||
    minViews !== '' ||
    minVirality !== '' ||
    minDaysLive !== '' ||
    priceTier !== '' ||
    ageBrackets.size > 0 ||
    languages.size > 0 ||
    contentFormats.size > 0

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Ad Search</h1>
        <p className="text-sm text-muted-foreground">
          Search the video database by keyword — semantic match over what each video actually shows.
        </p>
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault()
          runSearch()
        }}
        className="space-y-3"
      >
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="e.g. cleanser, acne extraction, ASMR pump, before after…"
              className="pl-9"
            />
          </div>
          <Button type="submit" disabled={loading}>
            {loading ? <Loader2 className="size-4 animate-spin" /> : query.trim() ? 'Search' : 'Show all'}
          </Button>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1 rounded-md border border-border p-0.5">
            {TYPE_OPTIONS.map((opt) => (
              <button
                key={opt.label}
                type="button"
                onClick={() => setItemType(opt.value)}
                className={cn(
                  'rounded px-2.5 py-1 text-xs font-medium transition-colors',
                  itemType === opt.value
                    ? 'bg-accent text-accent-foreground'
                    : 'text-muted-foreground hover:text-foreground',
                )}
              >
                {opt.label}
              </button>
            ))}
          </div>

          <select
            value={platform}
            onChange={(e) => setPlatform(e.target.value)}
            className="h-8 rounded-md border border-border bg-background px-2 text-xs"
          >
            <option value="">Any platform</option>
            <option value="tiktok">TikTok</option>
            <option value="instagram">Instagram</option>
            <option value="facebook">Facebook</option>
            <option value="meta">Meta</option>
          </select>

          <select
            value={runId}
            onChange={(e) => setRunId(e.target.value)}
            className="h-8 max-w-[220px] rounded-md border border-border bg-background px-2 text-xs"
          >
            <option value="">All campaigns</option>
            {runs.map((r) => (
              <option key={r.run_id} value={r.run_id}>
                {r.campaign_name || r.product_name || r.run_id.slice(0, 8)}
              </option>
            ))}
          </select>

          <select
            value={priceTier}
            onChange={(e) => setPriceTier(e.target.value)}
            className="h-8 rounded-md border border-border bg-background px-2 text-xs"
          >
            {PRICE_TIERS.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>

          {/* Performance filters are type-scoped: views/virality are organic-only, days-live is paid-only. */}
          {itemType !== 'paid_ad' && (
            <Input
              type="number"
              value={minViews}
              onChange={(e) => setMinViews(e.target.value)}
              placeholder="Min views (organic)"
              className="h-8 w-36 text-xs md:text-xs"
            />
          )}
          {itemType !== 'paid_ad' && (
            <Input
              type="number"
              min={0}
              max={1}
              step={0.05}
              value={minVirality}
              onChange={(e) => setMinVirality(e.target.value)}
              placeholder="Min virality 0–1 (organic)"
              className="h-8 w-44 text-xs md:text-xs"
            />
          )}
          {itemType !== 'ugc_item' && (
            <Input
              type="number"
              value={minDaysLive}
              onChange={(e) => setMinDaysLive(e.target.value)}
              placeholder="Min days live (paid)"
              className="h-8 w-40 text-xs md:text-xs"
            />
          )}

          {filtersActive && (
            <button
              type="button"
              onClick={clearFilters}
              className="flex h-8 items-center gap-1 rounded-md px-2 text-xs font-medium text-muted-foreground hover:text-foreground"
            >
              <X className="size-3.5" /> Clear filters
            </button>
          )}
        </div>

        <div className="flex flex-col gap-2">
          <ChipFilter label="Format" options={CONTENT_FORMATS} selected={contentFormats} onToggle={(v) => setContentFormats((s) => toggleInSet(s, v))} />
          <ChipFilter label="Age" options={AGE_BRACKETS} selected={ageBrackets} onToggle={(v) => setAgeBrackets((s) => toggleInSet(s, v))} />
          <ChipFilter label="Language" options={LANGUAGES} selected={languages} onToggle={(v) => setLanguages((s) => toggleInSet(s, v))} />
        </div>
      </form>

      {error && (
        <div className="rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      {loading && (
        <div className="flex items-center justify-center py-20 text-muted-foreground">
          <Loader2 className="mr-2 size-5 animate-spin" /> Searching…
        </div>
      )}

      {!loading && searched && results.length === 0 && !error && (
        <div className="py-20 text-center text-sm text-muted-foreground">
          No videos found. Try a broader keyword, or check that items have been enriched + embedded.
        </div>
      )}

      {!loading && results.length > 0 && (
        <>
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs text-muted-foreground">{results.length} results</p>
            <select
              value={sortMode}
              onChange={(e) => setSortMode(e.target.value as 'relevance' | 'performance')}
              className="h-8 rounded-md border border-border bg-background px-2 text-xs"
            >
              <option value="relevance">Sort: Relevance</option>
              <option value="performance">Sort: Top performing</option>
            </select>
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {(sortMode === 'performance' ? sortByPerformance(results) : results).map((r) => (
              <VideoCard key={`${r.item_type}:${r.item_id}`} result={r} />
            ))}
          </div>
        </>
      )}
    </div>
  )
}

function ChipFilter({
  label,
  options,
  selected,
  onToggle,
}: {
  label: string
  options: string[]
  selected: Set<string>
  onToggle: (value: string) => void
}) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      {options.map((opt) => {
        const active = selected.has(opt)
        return (
          <button
            key={opt}
            type="button"
            onClick={() => onToggle(opt)}
            className={cn(
              'rounded-full border px-2.5 py-0.5 text-xs transition-colors',
              active
                ? 'border-accent bg-accent text-accent-foreground'
                : 'border-border text-muted-foreground hover:text-foreground',
            )}
          >
            {opt.replace(/_/g, ' ')}
          </button>
        )
      })}
    </div>
  )
}

// Click-to-toggle explainer for the organic virality score. Click-away backdrop closes it.
function ViralityHelp() {
  const [open, setOpen] = useState(false)
  return (
    <span className="relative inline-flex items-center">
      <button
        type="button"
        aria-label="How is the virality score computed?"
        onClick={() => setOpen((v) => !v)}
        className="ml-0.5 text-muted-foreground/70 transition-colors hover:text-foreground"
      >
        <HelpCircle className="h-3 w-3" />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute bottom-full left-1/2 z-50 mb-1 w-64 -translate-x-1/2 rounded-md border border-border bg-popover p-3 text-left text-xs leading-relaxed text-popover-foreground shadow-md">
            <p className="font-medium">Virality score (0–1)</p>
            <p className="mt-1 text-muted-foreground">
              Blends how far a post escaped its own follower base with how engaging it was:
            </p>
            <p className="mt-1 font-mono text-[11px]">0.6 × reach + 0.4 × engagement</p>
            <ul className="mt-1 list-disc space-y-0.5 pl-4 text-muted-foreground">
              <li><span className="font-medium text-popover-foreground">reach</span> = views ÷ followers</li>
              <li><span className="font-medium text-popover-foreground">engagement</span> = (likes + comments + shares) ÷ views</li>
            </ul>
            <p className="mt-1 text-muted-foreground">
              Each is put on a 0–1 log curve (going viral has diminishing returns), then blended.
              Higher = reached well beyond its audience with strong engagement.
            </p>
          </div>
        </>
      )}
    </span>
  )
}

function VideoCard({ result: r }: { result: VideoResult }) {
  return (
    <div className="flex flex-col rounded-lg border border-border bg-card">
      {r.video_url ? (
        <video
          src={r.video_url}
          poster={r.thumb_url ?? undefined}
          controls
          playsInline
          preload="none"
          className="aspect-[9/16] w-full rounded-t-lg bg-black object-cover"
        />
      ) : (
        <div className="flex aspect-[9/16] w-full items-center justify-center rounded-t-lg bg-muted text-xs text-muted-foreground">
          no video
        </div>
      )}
      <div className="flex flex-1 flex-col gap-2 p-3">
        <div className="flex items-center justify-between gap-2">
          <span className="truncate text-sm font-medium">{r.title || 'untitled'}</span>
          {r.platform && <Badge variant="secondary">{r.platform}</Badge>}
        </div>
        <div className="flex flex-wrap gap-1">
          <Badge variant={r.item_type === 'paid_ad' ? 'default' : 'outline'}>
            {r.item_type === 'paid_ad' ? 'Paid' : 'Organic'}
          </Badge>
          {r.content_formats.map((f) => (
            <Badge key={`fmt-${f}`} variant="outline">{f}</Badge>
          ))}
          {typeof r.similarity === 'number' && (
            <Badge variant="outline">{Math.round(r.similarity * 100)}% relevance</Badge>
          )}
          {r.price_positioning && <Badge variant="outline">{r.price_positioning}</Badge>}
          {r.target_generation && <Badge variant="outline">{r.target_generation}</Badge>}
        </div>
        {(r.age_brackets.length > 0 || r.languages.length > 0) && (
          <div className="flex flex-wrap gap-1 text-xs text-muted-foreground">
            {r.age_brackets.map((a) => (
              <span key={`age-${a}`} className="rounded bg-muted px-1.5 py-0.5">{a}</span>
            ))}
            {r.languages.map((l) => (
              <span key={`lang-${l}`} className="rounded bg-muted px-1.5 py-0.5">{l}</span>
            ))}
          </div>
        )}
        <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
          {r.views != null && <span>{formatNum(r.views)} views</span>}
          {r.followers != null && <span>{formatNum(r.followers)} followers</span>}
          {r.likes != null && <span>{formatNum(r.likes)} likes</span>}
          {r.virality != null && (
            <span className="inline-flex items-center">
              vir {r.virality.toFixed(2)}
              <ViralityHelp />
            </span>
          )}
          {r.days_live != null && <span>{Math.round(r.days_live)}d live</span>}
        </div>
        {r.hook && (
          <p className="text-xs">
            <span className="font-medium">Hook:</span> {r.hook}
          </p>
        )}
        {r.ai_description && (
          <p className="line-clamp-4 text-xs text-muted-foreground">{r.ai_description}</p>
        )}
        {r.original_url && (
          <a
            href={r.original_url}
            target="_blank"
            rel="noreferrer"
            className="mt-auto text-xs text-primary hover:underline"
          >
            Open original ↗
          </a>
        )}
      </div>
    </div>
  )
}
