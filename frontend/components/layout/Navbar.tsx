'use client'

import Link from 'next/link'
import Image from 'next/image'
import { usePathname } from 'next/navigation'
import { cn } from '@/lib/utils'

const navLinks = [
  { href: '/search', label: 'Video Database', primary: true },
  { href: '/campaigns', label: 'By Campaign' },
  { href: '/discover', label: 'By Virality' },
  { href: '/trends', label: 'Trend Database', primary: true, divider: true },
]

export function Navbar() {
  const pathname = usePathname()

  return (
    <header className="sticky top-0 z-50 border-b border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4 sm:px-6">
        <Link href="/" className="flex items-center gap-2">
          <Image
            src="/instaagent-wordmark.png"
            alt="InstaAgent"
            width={803}
            height={139}
            priority
            className="h-7 w-auto opacity-90"
          />
          <span className="text-muted-foreground text-sm font-medium">· Personal Ad Intelligence</span>
        </Link>
        <nav className="flex items-center gap-1">
          {navLinks.map(({ href, label, primary, divider }) => {
            const isActive = pathname.startsWith(href)
            return (
              <div key={href} className="flex items-center gap-1">
                {divider && <span className="mx-1 h-6 w-px bg-border" aria-hidden />}
                <Link
                  href={href}
                  className={cn(
                    'rounded-md px-3 py-1.5 text-sm transition-colors',
                    primary ? 'font-bold' : 'font-medium',
                    isActive
                      ? 'bg-[#fdedf4] text-[#9d1555]'
                      : 'text-muted-foreground hover:text-foreground hover:bg-accent/50',
                  )}
                >
                  {label}
                </Link>
              </div>
            )
          })}
        </nav>
      </div>
    </header>
  )
}
