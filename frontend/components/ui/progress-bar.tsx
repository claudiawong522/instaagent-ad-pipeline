/** A thin filled bar showing how much of a whole is "ready" — e.g. searchable videos out of all
 * collected. Replaces "x / y" ratios, which read like a fraction puzzle for non-technical users.
 * `indeterminate` shows a pulsing stub for the in-progress, nothing-yet-collected state. */
export function ProgressBar({ pct, indeterminate }: { pct: number; indeterminate?: boolean }) {
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
      {indeterminate ? (
        <div className="h-full w-1/3 animate-pulse rounded-full bg-[#9d1555]/60" />
      ) : (
        <div
          className="h-full rounded-full bg-[#9d1555] transition-all duration-500"
          style={{ width: `${Math.max(0, Math.min(100, pct))}%` }}
        />
      )}
    </div>
  )
}
