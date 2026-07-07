'use client'

import { useRef, useState, type ReactNode } from 'react'
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
  // We fullscreen this wrapper, NOT the <video>. Native video fullscreen makes Chrome render the
  // portrait clip object-cover — zoomed and cropped — and ignores our object-fit. Inside a
  // fullscreen <div> the video is an ordinary element that letterboxes (object-contain) correctly.
  const wrapperRef = useRef<HTMLDivElement>(null)
  const toggleFullscreen = () => {
    const el = wrapperRef.current
    if (!el) return
    const doc = document as Document & { webkitExitFullscreen?: () => void; webkitFullscreenElement?: Element }
    const node = el as HTMLDivElement & { webkitRequestFullscreen?: () => void }
    const active = doc.fullscreenElement ?? doc.webkitFullscreenElement
    if (active) (doc.exitFullscreen ?? doc.webkitExitFullscreen)?.call(doc)
    else (node.requestFullscreen ?? node.webkitRequestFullscreen)?.call(node)
  }
  return (
    <div className={cn('flex flex-col', className)}>
      {videoUrl && !loadFailed ? (
        <div
          ref={wrapperRef}
          className={cn(
            'group/vt relative aspect-[9/16] w-full overflow-hidden bg-black',
            // In fullscreen the wrapper fills the screen; drop the 9:16 box so the video can letterbox.
            '[&:fullscreen]:aspect-auto',
            videoClassName,
          )}
        >
          <video
            src={videoUrl}
            poster={thumbUrl ?? undefined}
            controls
            controlsList="nofullscreen" // hide native fullscreen; ours fullscreens the wrapper instead
            playsInline
            preload="metadata"
            onError={() => setLoadFailed(true)}
            // Fills + crops in the tile; object-contain (respected here, as the video isn't the
            // fullscreen element) letterboxes once the wrapper is fullscreen.
            className="h-full w-full object-cover [:fullscreen_&]:object-contain"
          />
          <button
            type="button"
            onClick={toggleFullscreen}
            aria-label="Toggle fullscreen"
            className="absolute right-2 top-2 z-10 rounded-md bg-black/50 p-1.5 text-white opacity-0 transition-opacity hover:bg-black/70 group-hover/vt:opacity-100 [:fullscreen_&]:opacity-100"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3M3 16v3a2 2 0 0 0 2 2h3m13-5v3a2 2 0 0 1-2 2h-3" />
            </svg>
          </button>
        </div>
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
