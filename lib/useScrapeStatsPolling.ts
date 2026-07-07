'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { getScrapeEvents, getScrapeStats } from './api'
import type { ScrapeEventsResponse, ScrapeStats } from './types'

/** Scrape-stats store + poller shared by the Campaigns and Discover pages. `refreshStats` fetches
 * a batch of runs' stats (failed fetches keep the previous value); every `intervalMs` the hook
 * re-polls any run `isActive` says is mid-scrape — plus runs registered via `watch` (just-triggered
 * scrapes the server doesn't report as running yet) — until they settle. `isActive` must be a
 * stable reference (define it at module level). */
export function useScrapeStatsPolling(isActive: (s: ScrapeStats) => boolean, intervalMs: number) {
  const [stats, setStats] = useState<Record<string, ScrapeStats>>({})

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

  // Runs to keep polling even before their stats show them running (optimistic kick-offs).
  const pollRef = useRef<Set<string>>(new Set())
  const watch = useCallback((runId: string) => {
    pollRef.current.add(runId)
  }, [])

  useEffect(() => {
    const id = setInterval(() => {
      const active = Object.values(stats)
        .filter(isActive)
        .map((s) => s.run_id)
      const toPoll = new Set(active.concat(Array.from(pollRef.current)))
      if (toPoll.size === 0) return
      refreshStats(Array.from(toPoll))
      pollRef.current.forEach((rid) => {
        if (stats[rid] && !isActive(stats[rid])) pollRef.current.delete(rid)
      })
    }, intervalMs)
    return () => clearInterval(id)
  }, [stats, isActive, intervalMs, refreshStats])

  return { stats, setStats, refreshStats, watch }
}

/** A run's scrape events (per-scrape cost history), refetched whenever `refreshKey` changes —
 * callers derive the key from the run's scrape state so a just-finished scrape's real cost lands. */
export function useScrapeEvents(runId: string, refreshKey: string): ScrapeEventsResponse | null {
  const [data, setData] = useState<ScrapeEventsResponse | null>(null)
  useEffect(() => {
    getScrapeEvents(runId)
      .then(setData)
      .catch(() => {})
  }, [runId, refreshKey])
  return data
}
