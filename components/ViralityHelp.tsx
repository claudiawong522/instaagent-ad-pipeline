import { HelpPopover } from '@/components/HelpPopover'

// Shared "?" explainer for the organic virality score (used on the search results and the
// trends board). Keep the formula here only — it must match src/instaagent_pipeline/virality.py.
export function ViralityHelp({ panelClassName }: { panelClassName?: string }) {
  return (
    <HelpPopover
      ariaLabel="How is the virality score computed?"
      wrapperClassName="inline-flex items-center"
      triggerClassName="ml-0.5 text-muted-foreground/70"
      iconClassName="h-3 w-3"
      panelClassName={panelClassName ?? 'bottom-full left-1/2 mb-1 w-72 -translate-x-1/2 leading-relaxed'}
    >
      <p className="font-medium">Virality score (0–1)</p>
      <p className="mt-1 text-muted-foreground">
        Blends how far a post escaped its follower base, how fast it got there, and how
        engaging it was:
      </p>
      <p className="mt-1 font-mono text-[11px]">0.3 × reach + 0.3 × velocity + 0.4 × engagement</p>
      <ul className="mt-1 list-disc space-y-0.5 pl-4 text-muted-foreground">
        <li><span className="font-medium text-popover-foreground">reach</span> = views ÷ followers</li>
        <li><span className="font-medium text-popover-foreground">velocity</span> = reach ÷ days since posted</li>
        <li><span className="font-medium text-popover-foreground">engagement</span> = (likes + comments + shares) ÷ views</li>
      </ul>
      <p className="mt-1 text-muted-foreground">
        Each is put on a 0–1 log curve (going viral has diminishing returns), then blended.
        Velocity keeps newer posts from being out-scored just because older ones had longer
        to rack up views. Higher = reached far beyond its audience, fast, with strong engagement.
      </p>
    </HelpPopover>
  )
}
