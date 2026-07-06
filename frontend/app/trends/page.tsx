'use client'

import { useEffect, useRef, useState } from 'react'
import { HelpCircle, Loader2, Search, Sparkles, TrendingUp, X } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { listTrendFormats, matchProduct } from '@/lib/api'
import type { MatchedFormat, ViralFormat, TrendVideo } from '@/lib/types'

// Newsletter/trend-roundup sources, kept in sync with DEFAULT_TREND_SOURCES in
// src/instaagent_pipeline/trend_sources.py — the pages these formats are scraped from.
const TREND_SOURCE_URLS: { name: string; url: string }[] = [
  { name: 'ramdam', url: 'https://www.ramd.am/blog/trends-tiktok' },
  { name: 'newengen', url: 'https://newengen.com/tiktok-trends/' },
  { name: 'later', url: 'https://later.com/blog/tiktok-trends/' },
  { name: 'socialbee', url: 'https://socialbee.com/blog/tiktok-trends/' },
]

function formatNum(n: number | null | undefined): string {
  if (n == null) return '—'
  const compact = (v: number) => (v % 1 === 0 ? String(v) : v.toFixed(1))
  if (n >= 1_000_000) return `${compact(n / 1_000_000)}M`
  if (n >= 1_000) return `${compact(n / 1_000)}K`
  return String(n)
}

export default function TrendsPage() {
  const [formats, setFormats] = useState<ViralFormat[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [source, setSource] = useState<string | null>(null)
  // Chips persist across filtered loads: accumulate every source ever seen
  // (the initial unfiltered load seeds the full set) instead of deriving from
  // the currently filtered `formats`.
  const [sources, setSources] = useState<string[]>([])

  // Product-match mode: when `matched` is set, the list is ranked by fit to a product
  // (POST /trends/match) instead of browsed. Empty box / clear returns to browse.
  const [product, setProduct] = useState('')
  const [matched, setMatched] = useState<MatchedFormat[] | null>(null)
  const [matching, setMatching] = useState(false)
  const [matchedFor, setMatchedFor] = useState('')

  const load = (opts?: { sourceName?: string | null }) => {
    setLoading(true)
    listTrendFormats({ sourceName: opts?.sourceName ?? null })
      .then((res) => {
        setFormats(res.formats)
        setSources((prev) => {
          const set = new Set(prev)
          res.formats.forEach((f) => f.source_name && set.add(f.source_name))
          return Array.from(set).sort()
        })
        setError(null)
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
  }, [])

  const selectSource = (s: string | null) => {
    setSource(s)
    load({ sourceName: s })
  }

  const onMatch = (e: React.FormEvent) => {
    e.preventDefault()
    const q = product.trim()
    if (!q) {
      clearMatch()
      return
    }
    setMatching(true)
    setError(null)
    matchProduct({ product: q })
      .then((res) => {
        setMatched(res.formats)
        setMatchedFor(q)
      })
      .catch((e) => setError(String(e)))
      .finally(() => setMatching(false))
  }

  const clearMatch = () => {
    setMatched(null)
    setMatchedFor('')
    setProduct('')
  }

  const inMatchMode = matched !== null

  return (
    <div className="mx-auto max-w-6xl px-4 py-6 sm:px-6">
      <div className="mb-1 flex items-center gap-2">
        <TrendingUp className="h-5 w-5 text-[#9d1555]" />
        <h1 className="text-lg font-semibold">Viral Formats</h1>
        <SourcesHelp />
      </div>
      <p className="mb-4 text-sm text-muted-foreground">
        Trending TikTok/Reel formats scraped from web trend pages. Describe a product to rank them
        by how well you could reuse each one — or browse all, ranked by live views.
      </p>

      <form onSubmit={onMatch} className="mb-3 flex items-center gap-2">
        <div className="relative flex-1">
          <Sparkles className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-[#9d1555]" />
          <Input
            value={product}
            onChange={(e) => setProduct(e.target.value)}
            placeholder="Describe your product, e.g. magnesium sleep gummy…"
            className="pl-8"
          />
        </div>
        <button
          type="submit"
          disabled={matching}
          className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-md bg-[#9d1555] px-3 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          {matching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
          Match
        </button>
      </form>

      {inMatchMode ? (
        <div className="mb-5 flex items-center gap-2">
          <span className="text-sm text-muted-foreground">
            Ranked for <span className="font-medium text-foreground">{matchedFor}</span>
          </span>
          <button
            type="button"
            onClick={clearMatch}
            className="inline-flex items-center gap-1 rounded-full border border-border px-2 py-0.5 text-xs text-muted-foreground hover:text-foreground"
          >
            <X className="h-3 w-3" /> clear
          </button>
        </div>
      ) : (
        sources.length > 0 && (
          <div className="mb-5 flex flex-wrap items-center gap-1.5">
            <span className="text-xs font-medium text-muted-foreground">Source</span>
            <SourceChip label="all" active={source === null} onClick={() => selectSource(null)} />
            {sources.map((s) => (
              <SourceChip key={s} label={s} active={source === s} onClick={() => selectSource(s)} />
            ))}
          </div>
        )
      )}

      {matching ? (
        <div className="flex items-center gap-2 py-16 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Matching formats to your product…
        </div>
      ) : loading && !inMatchMode ? (
        <div className="flex items-center gap-2 py-16 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading formats…
        </div>
      ) : error ? (
        <p className="py-16 text-sm text-destructive">{error}</p>
      ) : inMatchMode ? (
        matched.length === 0 ? (
          <p className="py-16 text-sm text-muted-foreground">No formats to match yet.</p>
        ) : (
          <div className="flex flex-col gap-4">
            {matched.map((f) => (
              <FormatCard key={f.id} format={f} />
            ))}
          </div>
        )
      ) : formats.length === 0 ? (
        <p className="py-16 text-sm text-muted-foreground">
          No formats yet. Run <code className="rounded bg-muted px-1">ingest-trends</code> then{' '}
          <code className="rounded bg-muted px-1">classify-formats</code>.
        </p>
      ) : (
        <div className="flex flex-col gap-4">
          {formats.map((f) => (
            <FormatCard key={f.id} format={f} />
          ))}
        </div>
      )}
    </div>
  )
}

function SourcesHelp() {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-label="Trend sources"
        className="text-muted-foreground transition-colors hover:text-foreground"
      >
        <HelpCircle className="h-4 w-4" />
      </button>
      {open && (
        <div className="absolute left-0 top-full z-10 mt-1.5 w-64 rounded-md border border-border bg-popover p-3 text-popover-foreground shadow-md">
          <p className="mb-2 text-xs font-medium">Formats are scraped from these trend newsletters:</p>
          <ul className="flex flex-col gap-2">
            {TREND_SOURCE_URLS.map((s) => (
              <li key={s.name} className="min-w-0">
                <a
                  href={s.url}
                  target="_blank"
                  rel="noreferrer"
                  className="block min-w-0 hover:underline"
                >
                  <span className="block text-xs font-medium capitalize text-primary">{s.name}</span>
                  <span className="block truncate text-[11px] text-muted-foreground">{s.url}</span>
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function SourceChip({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'rounded-full border px-2.5 py-0.5 text-xs capitalize transition-colors',
        active ? 'border-accent bg-accent text-accent-foreground' : 'border-border text-muted-foreground hover:text-foreground',
      )}
    >
      {label}
    </button>
  )
}

const VERSATILITY_STYLES: Record<string, string> = {
  universal: 'border-transparent bg-emerald-100 text-emerald-700',
  broad: 'border-transparent bg-amber-100 text-amber-700',
  niche: 'border-transparent bg-muted text-muted-foreground',
}

const FIT_STYLES: Record<string, string> = {
  great: 'border-transparent bg-emerald-100 text-emerald-700',
  workable: 'border-transparent bg-amber-100 text-amber-700',
  no: 'border-transparent bg-muted text-muted-foreground',
}

function FormatCard({ format: f }: { format: ViralFormat & Partial<MatchedFormat> }) {
  const isNoFit = f.fit === 'no'
  return (
    <div className={cn('rounded-lg border border-border bg-card p-4', isNoFit && 'opacity-60')}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-base font-semibold">{f.format_name || 'untitled format'}</h2>
            {f.versatility && (
              <Badge className={cn('capitalize', VERSATILITY_STYLES[f.versatility])}>{f.versatility}</Badge>
            )}
            {f.source_name && (
              <Badge variant="secondary" className="capitalize">{f.source_name}</Badge>
            )}
          </div>
          {f.format_description && (
            <p className="mt-1 max-w-3xl text-sm text-muted-foreground">{f.format_description}</p>
          )}
        </div>
        <div className="whitespace-nowrap text-right text-xs text-muted-foreground">
          {f.fit ? (
            <Badge className={cn('capitalize', FIT_STYLES[f.fit])}>
              {f.score != null ? `${f.score} · ` : ''}
              {f.fit}
            </Badge>
          ) : (
            <>
              <div className="text-sm font-semibold text-foreground">{formatNum(f.total_views)} views</div>
              <div>{f.video_count} example{f.video_count === 1 ? '' : 's'}</div>
            </>
          )}
        </div>
      </div>

      {/* Match mode shows how to use the format for the product; browse mode shows the constraint. */}
      {f.fit && f.idea ? (
        <div className="mt-2 flex items-start gap-1.5">
          <Badge variant="outline" className="shrink-0">idea</Badge>
          <p className="text-sm">{f.idea}</p>
        </div>
      ) : !f.fit && f.niche_constraint ? (
        <div className="mt-2 flex items-start gap-1.5">
          <Badge variant="outline" className="shrink-0">constraint</Badge>
          <p className="text-sm">{f.niche_constraint}</p>
        </div>
      ) : !f.fit ? (
        <p className="mt-2 text-xs italic text-muted-foreground">
          Not yet classified — run <code className="rounded bg-muted px-1">classify-formats</code>.
        </p>
      ) : null}

      {f.videos.length > 0 ? (
        <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
          {f.videos.map((v) => (
            <TrendVideoCard key={v.id} video={v} />
          ))}
        </div>
      ) : f.ingest_note ? (
        <p className="mt-3 text-xs italic text-muted-foreground">No example video — {f.ingest_note}</p>
      ) : null}
    </div>
  )
}

function TrendVideoCard({ video: v }: { video: TrendVideo }) {
  return (
    <div className="flex flex-col overflow-hidden rounded-md border border-border bg-background">
      {v.video_url ? (
        <video
          src={v.video_url}
          poster={v.thumb_url ?? undefined}
          controls
          playsInline
          preload="none"
          className="aspect-[9/16] w-full bg-black object-cover"
        />
      ) : (
        <div className="flex aspect-[9/16] w-full items-center justify-center bg-muted text-[11px] text-muted-foreground">
          {v.enrichment_status === 'expired' ? 'video expired' : 'processing…'}
        </div>
      )}
      <div className="flex flex-col gap-1 p-2">
        <div className="flex flex-wrap gap-x-2 text-[11px] text-muted-foreground">
          {v.views != null && <span>{formatNum(v.views)} views</span>}
          {v.likes != null && <span>{formatNum(v.likes)} likes</span>}
        </div>
        {v.handle && <span className="truncate text-[11px] text-muted-foreground">@{v.handle}</span>}
        {v.original_url && (
          <a
            href={v.original_url}
            target="_blank"
            rel="noreferrer"
            className="text-[11px] text-primary hover:underline"
          >
            Open ↗
          </a>
        )}
      </div>
    </div>
  )
}
