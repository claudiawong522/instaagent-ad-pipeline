'use client'

import { useEffect, useState } from 'react'
import { Loader2, Search, Sparkles, TrendingUp, X } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { listTrendFormats, listTrendScrapeDates, matchProduct } from '@/lib/api'
import type { MatchedFormat, ViralFormat, TrendVideo } from '@/lib/types'
import { fmtDate, formatNum, safeHref } from '@/lib/format'
import { HelpPopover } from '@/components/HelpPopover'
import { ViralityHelp } from '@/components/ViralityHelp'
import { VideoTile } from '@/components/VideoTile'

// Newsletter/trend-roundup sources, kept in sync with default_trend_sources() in
// src/instaagent_pipeline/trend_sources.py — the pages these formats are scraped from.
// newengen scrapes its monthly deep-dive report, whose URL slug rolls over each month, so we
// derive the current month here the same way the backend does (_newengen_insights_url).
const NEWENGEN_MONTHS = [
  'january', 'february', 'march', 'april', 'may', 'june',
  'july', 'august', 'september', 'october', 'november', 'december',
] as const
const newengenInsightsUrl = () =>
  `https://newengen.com/insights/${NEWENGEN_MONTHS[new Date().getMonth()]}-tiktok-trends/`

const TREND_SOURCE_URLS: { name: string; url: string; cadence: string }[] = [
  { name: 'ramdam', url: 'https://www.ramd.am/blog/trends-tiktok', cadence: 'Updated weekly' },
  { name: 'newengen', url: newengenInsightsUrl(), cadence: 'Updated monthly' },
  { name: 'socialbee', url: 'https://socialbee.com/blog/tiktok-trends/', cadence: 'Updated weekly' },
  // SGE's weekly "viral hits" post is email-gated; the backend discovers the newest post each run,
  // so we just link to the site root here (no stable per-week URL to mirror).
  { name: 'socialgrowthengineers', url: 'https://www.socialgrowthengineers.com', cadence: 'Updated weekly' },
]

// The DB keys sources by their one-word slug; give multi-word names their spacing back for
// display (the `capitalize` class then title-cases each word).
const SOURCE_LABELS: Record<string, string> = {
  socialgrowthengineers: 'social growth engineers',
}
const sourceLabel = (name: string) => SOURCE_LABELS[name] ?? name

const MONTHS_SHORT = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
// Label a scrape date "2026-06-19" → "Jun 19" by splitting the string directly (never via
// new Date(), which would shift the day across the local timezone boundary).
function fmtScrapeChip(ymd: string): string {
  const [, m, d] = ymd.split('-')
  const month = MONTHS_SHORT[Number(m) - 1]
  return month ? `${month} ${Number(d)}` : ymd
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
  // Scrape-date filter: the distinct dates the selected source was scraped, plus the picked date.
  // Fetched separately (per source) so the chip list doesn't collapse when a date is applied.
  const [scrapeDates, setScrapeDates] = useState<string[]>([])
  const [scrapedOn, setScrapedOn] = useState<string | null>(null)

  // Product-match mode: when `matched` is set, the list is ranked by fit to a product
  // (POST /trends/match) instead of browsed. Empty box / clear returns to browse.
  const [product, setProduct] = useState('')
  const [matched, setMatched] = useState<MatchedFormat[] | null>(null)
  const [matching, setMatching] = useState(false)
  const [matchedFor, setMatchedFor] = useState('')

  const load = (opts?: { sourceName?: string | null; scrapedOn?: string | null }) => {
    setLoading(true)
    listTrendFormats({ sourceName: opts?.sourceName ?? null, scrapedOn: opts?.scrapedOn ?? null })
      .then((res) => {
        setFormats(res.formats)
        setSources((prev) => {
          const set = new Set(prev)
          res.formats.forEach((f) => f.source_name && set.add(f.source_name))
          return Array.from(set).sort()
        })
        setError(null)
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false))
  }

  // Refresh the "Scraped" chips for a source and clear any active date pick.
  const loadScrapeDates = (s: string | null) => {
    setScrapedOn(null)
    listTrendScrapeDates(s)
      .then((res) => setScrapeDates(res.dates))
      .catch(() => setScrapeDates([]))
  }

  useEffect(() => {
    load()
    loadScrapeDates(null)
  }, [])

  // Deep-link support: /trends?product=... (e.g. the example chip on the home page) runs the
  // product-match immediately. Read once on mount, using the param value directly since `product`
  // state isn't updated until the next render.
  useEffect(() => {
    const p = new URLSearchParams(window.location.search).get('product')
    if (p) {
      setProduct(p)
      runMatch(p)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const selectSource = (s: string | null) => {
    setSource(s)
    loadScrapeDates(s)
    load({ sourceName: s, scrapedOn: null })
  }

  const selectScrapedOn = (d: string | null) => {
    setScrapedOn(d)
    load({ sourceName: source, scrapedOn: d })
  }

  const runMatch = (raw: string) => {
    const q = raw.trim()
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
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setMatching(false))
  }

  const onMatch = (e: React.FormEvent) => {
    e.preventDefault()
    runMatch(product)
  }

  const clearMatch = () => {
    setMatched(null)
    setMatchedFor('')
    setProduct('')
  }

  const inMatchMode = matched !== null

  return (
    <div>
      <div className="mb-1 flex items-center gap-2">
        <TrendingUp className="h-6 w-6 text-[#9d1555]" />
        <h1 className="text-2xl font-semibold tracking-tight">Viral Formats</h1>
        <SourcesHelp />
      </div>
      <p className="mb-4 text-sm text-muted-foreground">
        Trending TikTok/Reel formats scraped from web trend pages. Describe a product to rank them
        by how well you could reuse each one — or browse all, ranked by virality
        <ViralityHelp panelClassName="left-1/2 top-full mt-1 w-72 -translate-x-1/2 leading-relaxed" />.
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
        <div className="mb-5 flex flex-col gap-1.5">
          {sources.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-xs font-medium text-muted-foreground">Source</span>
              <SourceChip label="all" active={source === null} onClick={() => selectSource(null)} />
              {sources.map((s) => (
                <SourceChip key={s} label={sourceLabel(s)} active={source === s} onClick={() => selectSource(s)} />
              ))}
            </div>
          )}
          {scrapeDates.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-xs font-medium text-muted-foreground">Scraped</span>
              <SourceChip label="any" active={scrapedOn === null} onClick={() => selectScrapedOn(null)} />
              {scrapeDates.map((d) => (
                <SourceChip
                  key={d}
                  label={fmtScrapeChip(d)}
                  active={scrapedOn === d}
                  onClick={() => selectScrapedOn(d)}
                />
              ))}
            </div>
          )}
        </div>
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
        source !== null || scrapedOn !== null ? (
          <p className="py-16 text-sm text-muted-foreground">No formats match this filter.</p>
        ) : (
          <p className="py-16 text-sm text-muted-foreground">
            No formats yet. Run <code className="rounded bg-muted px-1">ingest-trends</code> then{' '}
            <code className="rounded bg-muted px-1">classify-formats</code>.
          </p>
        )
      ) : (
        <div className="flex flex-col gap-4">
          <p className="text-xs text-muted-foreground">
            {formats.length} format{formats.length === 1 ? '' : 's'}
          </p>
          {formats.map((f) => (
            <FormatCard key={f.id} format={f} />
          ))}
        </div>
      )}
    </div>
  )
}

function SourcesHelp() {
  return (
    <HelpPopover ariaLabel="Trend sources" panelClassName="left-0 top-full mt-1.5 w-64">
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
              <span className="block text-xs font-medium capitalize text-primary">
                {sourceLabel(s.name)} <span className="font-normal text-muted-foreground">· {s.cadence}</span>
              </span>
              <span className="block truncate text-[11px] text-muted-foreground">{s.url}</span>
            </a>
          </li>
        ))}
      </ul>
    </HelpPopover>
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
              <Badge variant="secondary" className="capitalize">{sourceLabel(f.source_name)}</Badge>
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
              {f.fit === 'no' ? 'no fit' : f.fit}
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
    <VideoTile
      videoUrl={v.video_url}
      thumbUrl={v.thumb_url}
      fallback={
        v.enrichment_status === 'expired'
          ? 'video expired'
          : v.enrichment_status === 'failed'
            ? 'unavailable'
            : 'processing…'
      }
      className="overflow-hidden rounded-md border border-border bg-background"
      fallbackClassName="text-[11px]"
      bodyClassName="gap-1 p-2"
    >
      <div className="flex flex-wrap gap-x-2 text-[11px] text-muted-foreground">
        {v.views != null && <span>{formatNum(v.views)} views</span>}
        {v.likes != null && <span>{formatNum(v.likes)} likes</span>}
        {v.date_created && <span>{fmtDate(v.date_created)}</span>}
      </div>
      {v.handle && <span className="truncate text-[11px] text-muted-foreground">@{v.handle}</span>}
      {safeHref(v.original_url) && (
        <a
          href={safeHref(v.original_url)}
          target="_blank"
          rel="noreferrer"
          className="text-[11px] text-primary hover:underline"
        >
          Open ↗
        </a>
      )}
    </VideoTile>
  )
}
