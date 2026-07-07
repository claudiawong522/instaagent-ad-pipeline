// Shared display formatters used across pages.

/** Compact count, e.g. "1.2M", "45K", "512"; "—" when missing. */
export function formatNum(n: number | null | undefined): string {
  if (n == null) return '—'
  const compact = (v: number) => (v % 1 === 0 ? String(v) : v.toFixed(1))
  // 999,950+ rounds to "1000.0K" at one decimal, so promote it to "1.0M".
  if (n >= 999_950) return `${compact(n / 1_000_000)}M`
  if (n >= 1_000) return `${compact(n / 1_000)}K`
  return String(n)
}

/** Format a USD amount compactly: a "<$0.01" floor for tiny spend, 2 decimals otherwise. */
export function money(usd: number | null | undefined): string {
  if (usd == null) return '—'
  if (usd > 0 && usd < 0.01) return '<$0.01'
  return `$${usd.toFixed(2)}`
}

/** Scrape date/time, e.g. "Jun 23, 6:31 AM". */
export function dateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}

/** Compact relative time, e.g. "just now", "5m ago", "3h ago", "2d ago". */
export function timeAgo(iso: string | null | undefined): string | null {
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

/** A URL safe to put in an href: only http(s), else undefined. Blocks scraped `javascript:`/`data:`
 *  URLs, which React renders verbatim (it only warns in dev). */
export function safeHref(url: string | null | undefined): string | undefined {
  if (!url) return undefined
  try {
    const scheme = new URL(url, window.location.origin).protocol
    return scheme === 'http:' || scheme === 'https:' ? url : undefined
  } catch {
    return undefined
  }
}

/** Short date, e.g. "Jun 23, 2026"; "—" when missing/malformed. */
export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}
