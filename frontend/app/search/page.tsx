'use client'

import { useEffect, useState } from 'react'
import { Search, Loader2 } from 'lucide-react'
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
  { label: 'UGC', value: 'ugc_item' },
]

export default function SearchPage() {
  const [query, setQuery] = useState('')
  const [itemType, setItemType] = useState<ItemType | null>(null)
  const [platform, setPlatform] = useState<string>('')
  const [runId, setRunId] = useState<string>('')
  const [minViews, setMinViews] = useState<string>('')
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [results, setResults] = useState<VideoResult[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [searched, setSearched] = useState(false)

  useEffect(() => {
    listRuns()
      .then((r) => setRuns(r.runs))
      .catch(() => setRuns([]))
  }, [])

  async function runSearch() {
    if (!query.trim()) return
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
        limit: 24,
      })
      setResults(res.results)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Search failed')
      setResults([])
    } finally {
      setLoading(false)
    }
  }

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
          <Button type="submit" disabled={loading || !query.trim()}>
            {loading ? <Loader2 className="size-4 animate-spin" /> : 'Search'}
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
            <option value="">All runs</option>
            {runs.map((r) => (
              <option key={r.run_id} value={r.run_id}>
                {r.product_name || r.run_id.slice(0, 8)}
              </option>
            ))}
          </select>

          <Input
            type="number"
            value={minViews}
            onChange={(e) => setMinViews(e.target.value)}
            placeholder="Min views"
            className="h-8 w-28 text-xs"
          />
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
          <p className="text-xs text-muted-foreground">{results.length} results</p>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {results.map((r) => (
              <VideoCard key={`${r.item_type}:${r.item_id}`} result={r} />
            ))}
          </div>
        </>
      )}
    </div>
  )
}

function VideoCard({ result: r }: { result: VideoResult }) {
  return (
    <div className="flex flex-col overflow-hidden rounded-lg border border-border bg-card">
      {r.video_url ? (
        <video
          src={r.video_url}
          poster={r.thumb_url ?? undefined}
          controls
          playsInline
          preload="none"
          className="aspect-[9/16] w-full bg-black object-cover"
        />
      ) : (
        <div className="flex aspect-[9/16] w-full items-center justify-center bg-muted text-xs text-muted-foreground">
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
            {r.item_type === 'paid_ad' ? 'Paid' : 'UGC'}
          </Badge>
          {r.content_format && <Badge variant="outline">{r.content_format}</Badge>}
          {typeof r.similarity === 'number' && (
            <Badge variant="outline">{Math.round(r.similarity * 100)}% match</Badge>
          )}
        </div>
        <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
          {r.views != null && <span>{formatNum(r.views)} views</span>}
          {r.followers != null && <span>{formatNum(r.followers)} followers</span>}
          {r.likes != null && <span>{formatNum(r.likes)} likes</span>}
          {r.virality != null && <span>vir {Math.round(r.virality)}</span>}
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
