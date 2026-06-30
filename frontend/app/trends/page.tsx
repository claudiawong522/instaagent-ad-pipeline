'use client'

import { useEffect, useMemo, useState } from 'react'
import { Loader2, Search, TrendingUp } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { listTrendFormats } from '@/lib/api'
import type { ViralFormat, TrendVideo } from '@/lib/types'

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
  const [query, setQuery] = useState('')

  // The full unfiltered set drives the source chips; source/query filtering hits the API.
  const load = (opts?: { sourceName?: string | null; q?: string | null }) => {
    setLoading(true)
    listTrendFormats({ sourceName: opts?.sourceName ?? null, q: opts?.q ?? null })
      .then((res) => {
        setFormats(res.formats)
        setError(null)
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
  }, [])

  const sources = useMemo(() => {
    const set = new Set<string>()
    formats.forEach((f) => f.source_name && set.add(f.source_name))
    return Array.from(set).sort()
  }, [formats])

  const selectSource = (s: string | null) => {
    setSource(s)
    load({ sourceName: s, q: query.trim() || null })
  }

  const onSearch = (e: React.FormEvent) => {
    e.preventDefault()
    load({ sourceName: source, q: query.trim() || null })
  }

  return (
    <div className="mx-auto max-w-6xl px-4 py-6 sm:px-6">
      <div className="mb-1 flex items-center gap-2">
        <TrendingUp className="h-5 w-5 text-[#9d1555]" />
        <h1 className="text-lg font-semibold">Viral Formats</h1>
      </div>
      <p className="mb-4 text-sm text-muted-foreground">
        Trending TikTok/Reel formats scraped from web trend pages, ranked by their example
        videos&rsquo; live views. Each card shows the format&rsquo;s marketing constraint.
      </p>

      <form onSubmit={onSearch} className="mb-3 flex items-center gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter by constraint, e.g. beauty, food, universal…"
            className="pl-8"
          />
        </div>
      </form>

      {sources.length > 0 && (
        <div className="mb-5 flex flex-wrap items-center gap-1.5">
          <span className="text-xs font-medium text-muted-foreground">Source</span>
          <SourceChip label="all" active={source === null} onClick={() => selectSource(null)} />
          {sources.map((s) => (
            <SourceChip key={s} label={s} active={source === s} onClick={() => selectSource(s)} />
          ))}
        </div>
      )}

      {loading ? (
        <div className="flex items-center gap-2 py-16 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading formats…
        </div>
      ) : error ? (
        <p className="py-16 text-sm text-destructive">{error}</p>
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

function FormatCard({ format: f }: { format: ViralFormat }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-base font-semibold">{f.format_name || 'untitled format'}</h2>
            {f.source_name && (
              <Badge variant="secondary" className="capitalize">{f.source_name}</Badge>
            )}
          </div>
          {f.format_description && (
            <p className="mt-1 max-w-3xl text-sm text-muted-foreground">{f.format_description}</p>
          )}
        </div>
        <div className="whitespace-nowrap text-right text-xs text-muted-foreground">
          <div className="text-sm font-semibold text-foreground">{formatNum(f.total_views)} views</div>
          <div>{f.video_count} example{f.video_count === 1 ? '' : 's'}</div>
        </div>
      </div>

      {f.niche_constraint ? (
        <div className="mt-2 flex items-start gap-1.5">
          <Badge variant="outline" className="shrink-0">constraint</Badge>
          <p className="text-sm">{f.niche_constraint}</p>
        </div>
      ) : (
        <p className="mt-2 text-xs italic text-muted-foreground">
          Not yet classified — run <code className="rounded bg-muted px-1">classify-formats</code>.
        </p>
      )}

      {f.videos.length > 0 && (
        <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
          {f.videos.map((v) => (
            <TrendVideoCard key={v.id} video={v} />
          ))}
        </div>
      )}
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
