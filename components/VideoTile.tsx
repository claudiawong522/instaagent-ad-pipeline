'use client'

import { useState, type ReactNode } from 'react'
import { cn } from '@/lib/utils'

/** Portrait video card shell shared by search results and trend example cards: the 9:16 <video>
 * with poster (or a same-size fallback message when there's no playable URL), then the page's own
 * metadata rows as children. Border/rounding, fallback text, and body spacing differ per page —
 * all passed as classes. */
export function VideoTile({
  videoUrl,
  thumbUrl,
  fallback,
  className,
  videoClassName,
  fallbackClassName,
  bodyClassName,
  children,
}: {
  videoUrl: string | null
  thumbUrl: string | null
  fallback: ReactNode // shown inside the 9:16 box when there's no video
  className?: string // card shell (border, rounding, background)
  videoClassName?: string // extra classes on the video/fallback box, e.g. 'rounded-t-lg'
  fallbackClassName?: string // fallback-only classes, e.g. text size
  bodyClassName?: string // metadata area (padding, gap)
  children: ReactNode
}) {
  // A stored/provider URL can 404 or expire; without this the browser shows a dead black player.
  const [loadFailed, setLoadFailed] = useState(false)
  return (
    <div className={cn('flex flex-col', className)}>
      {videoUrl && !loadFailed ? (
        <video
          src={videoUrl}
          poster={thumbUrl ?? undefined}
          controls
          playsInline
          preload="none"
          onError={() => setLoadFailed(true)}
          className={cn('aspect-[9/16] w-full bg-black object-cover', videoClassName)}
        />
      ) : (
        <div
          className={cn(
            'flex aspect-[9/16] w-full items-center justify-center bg-muted text-muted-foreground',
            videoClassName,
            fallbackClassName,
          )}
        >
          {loadFailed ? 'video unavailable' : fallback}
        </div>
      )}
      <div className={cn('flex flex-col', bodyClassName)}>{children}</div>
    </div>
  )
}
