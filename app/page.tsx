import Link from 'next/link'
import { Database, Megaphone, Flame, TrendingUp, ArrowRight, Clapperboard, LineChart, Search, Users, type LucideIcon } from 'lucide-react'

export const metadata = {
  title: 'InstaAgent · Personal Ad Intelligence',
  description: 'A searchable database of paid ads and organic videos, plus a daily-refreshed feed of viral formats.',
}

// Concrete examples beat an empty box. Each chip deep-links into the page that answers it: the
// Database (search reads ?q=) for a product or a persona, the Trend Database (reads ?product=) to
// match a product against live trends.
const EXAMPLE_TRIES: { label: string; hint: string; href: string; icon: LucideIcon }[] = [
  { label: 'vitamin C serum', hint: 'a product', href: '/search?q=vitamin%20C%20serum', icon: Search },
  { label: 'busy moms, sensitive skin', hint: 'a persona', href: '/search?q=busy%20moms%2C%20sensitive%20skin', icon: Users },
  { label: 'collagen supplement', hint: 'match to a trend', href: '/trends?product=collagen%20supplement', icon: TrendingUp },
]

export default function HomePage() {
  return (
    <div className="space-y-10">
      {/* Hero */}
      <div className="space-y-3">
        <h1 className="text-3xl font-semibold tracking-tight">InstaAgent&apos;s Personal Ad Intelligence</h1>
        <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">
          Two libraries in one tool. The <span className="font-medium text-foreground">Video Database</span> is
          your own searchable collection of real ads and organic clips, filled by scraping reels, TikToks,
          and Meta ads. The <span className="font-medium text-foreground">Trend Database</span> is an
          auto-updating feed of viral formats, scraped off human-curated trend research blogs every day. Pick
          a starting point below.
        </p>
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <span className="text-xs font-medium text-muted-foreground">Try:</span>
          {EXAMPLE_TRIES.map(({ label, hint, href, icon: Icon }) => (
            <Link
              key={href}
              href={href}
              className="group/chip flex items-center gap-1.5 rounded-full border border-border bg-card px-3 py-1 text-xs font-medium text-foreground transition-colors hover:border-[#9d1555]/40 hover:bg-[#fdedf4] hover:text-[#9d1555]"
            >
              <Icon className="size-3 text-muted-foreground group-hover/chip:text-[#9d1555]" />
              {label}
              <span className="text-muted-foreground/70">· {hint}</span>
            </Link>
          ))}
        </div>
      </div>

      {/* How it works: 1-2-3 */}
      <div className="grid gap-3 sm:grid-cols-3">
        <Step n={1} title="Scrape" desc="Fill your database with competitor ads and viral clips." />
        <Step n={2} title="Search" desc="Filter by ICP persona, format, or what the video shows." />
        <Step n={3} title="Win" desc="Match a proven trend to your product and twist it to fit." />
      </div>

      {/* Two columns */}
      <div className="grid gap-6 lg:grid-cols-2">
        {/* LEFT: Video Database */}
        <section className="flex flex-col gap-4 rounded-xl border border-border bg-card p-6">
          <div className="flex items-center gap-2">
            <Clapperboard className="size-5 text-[#9d1555]" />
            <h2 className="text-lg font-semibold tracking-tight">Video Database</h2>
          </div>
          <p className="text-sm leading-relaxed text-muted-foreground">
            Enter a product campaign and search for relevant clips, or just scrape the most viral clips
            regardless of product fit, above a minimum view count.
          </p>

          <div className="space-y-3">
            <FeatureRow
              href="/campaigns"
              icon={<Megaphone className="size-4" />}
              title="By Campaign"
              desc="Add a product campaign, then run a scrape. It pulls paid Facebook / Meta ads with metadata, plus reels and TikToks, into the video database. Every video is downloaded to storage, so you never lose it even if the source URL expires."
            />
            <FeatureRow
              href="/discover"
              icon={<Flame className="size-4" />}
              title="By Virality"
              desc="Pull TikTok's For You feed for a country: no keyword, no product. Pure trending organic video, dropped into the same database."
            />
            <FeatureRow
              href="/search"
              icon={<Database className="size-4" />}
              title="Database"
              desc="Search by ICP persona, or by what the video actually shows, then filter by format, platform, price tier, or paid vs organic. It renders results both ways."
            />
          </div>
        </section>

        {/* RIGHT: Trend Database */}
        <section className="flex flex-col gap-4 rounded-xl border border-border bg-card p-6">
          <div className="flex items-center gap-2">
            <TrendingUp className="size-5 text-[#9d1555]" />
            <h2 className="text-lg font-semibold tracking-tight">Trend Database</h2>
          </div>
          <p className="text-sm leading-relaxed text-muted-foreground">
            Auto-scrapes newsletters for viral trends, with video examples, e.g. the cutting-fruit trend, or
            the &ldquo;rich in life because&hellip;&rdquo; trend.
          </p>

          <div className="space-y-3">
            <FeatureRow
              icon={<LineChart className="size-4" />}
              title="Scrapes itself, daily"
              desc="A GitHub Action runs every morning: it reads marketing 'top TikTok trends' blogs, an AI structures each format, then it re-scrapes the example TikToks to fact-check live view counts. Unchanged blogs are skipped, so quiet days are nearly free."
            />
            <FeatureRow
              href="/trends"
              icon={<Flame className="size-4" />}
              title="By Trend"
              desc="Browse the collected formats, sorted by a carefully curated virality score, not raw views. Enter your product in the search bar to match a trend to it, with a one-line idea on how to twist the trend to fit."
            />
          </div>
        </section>
      </div>
    </div>
  )
}

function FeatureRow({
  href,
  icon,
  title,
  desc,
}: {
  href?: string
  icon: React.ReactNode
  title: string
  desc: string
}) {
  const inner = (
    <div className="flex gap-3 rounded-lg border border-border bg-background/50 p-3 transition-colors group-hover:border-[#9d1555]/40 group-hover:bg-[#fdedf4]/40">
      <div className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-md bg-[#fdedf4] text-[#9d1555]">
        {icon}
      </div>
      <div className="space-y-1">
        <div className="flex items-center gap-1.5 text-sm font-medium">
          {title}
          {href && <ArrowRight className="size-3.5 opacity-0 transition-opacity group-hover:opacity-100" />}
        </div>
        <p className="text-xs leading-relaxed text-muted-foreground">{desc}</p>
      </div>
    </div>
  )

  if (!href) return <div className="group">{inner}</div>
  return (
    <Link href={href} className="group block">
      {inner}
    </Link>
  )
}

function Step({ n, title, desc }: { n: number; title: string; desc: string }) {
  return (
    <div className="flex gap-3 rounded-lg border border-border bg-card p-4">
      <div className="flex size-6 shrink-0 items-center justify-center rounded-full bg-[#9d1555] text-xs font-bold text-white">
        {n}
      </div>
      <div className="space-y-0.5">
        <div className="text-sm font-semibold">{title}</div>
        <p className="text-xs leading-relaxed text-muted-foreground">{desc}</p>
      </div>
    </div>
  )
}
