'use client'

import { useEffect, useRef, useState, type ReactNode } from 'react'
import { HelpCircle } from 'lucide-react'
import { cn } from '@/lib/utils'

/** Small "?" icon that toggles an explainer panel; clicking outside closes it. The pages differ
 * only in icon size, trigger styling, and where the panel opens — all passed as classes. */
export function HelpPopover({
  ariaLabel,
  wrapperClassName,
  triggerClassName,
  iconClassName,
  panelClassName,
  children,
}: {
  ariaLabel: string
  wrapperClassName?: string
  triggerClassName?: string
  iconClassName?: string
  panelClassName?: string // placement + width, e.g. 'left-0 top-full mt-1.5 w-64'
  children: ReactNode
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  return (
    <span ref={ref} className={cn('relative', wrapperClassName)}>
      <button
        type="button"
        aria-label={ariaLabel}
        onClick={() => setOpen((o) => !o)}
        className={cn('text-muted-foreground transition-colors hover:text-foreground', triggerClassName)}
      >
        <HelpCircle className={iconClassName ?? 'h-4 w-4'} />
      </button>
      {open && (
        <div
          className={cn(
            'absolute z-50 rounded-md border border-border bg-popover p-3 text-left text-xs text-popover-foreground shadow-md',
            panelClassName,
          )}
        >
          {children}
        </div>
      )}
    </span>
  )
}
