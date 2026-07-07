'use client'

import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { ArrowLeft } from 'lucide-react'
import { createCampaign } from '@/lib/api'
import { CampaignForm } from '@/components/campaigns/CampaignForm'

export default function NewCampaignPage() {
  const router = useRouter()

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <div className="space-y-1">
        <Link href="/campaigns" className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
          <ArrowLeft className="size-3.5" /> Back to campaigns
        </Link>
        <h1 className="text-2xl font-semibold tracking-tight">New campaign</h1>
        <p className="text-sm text-muted-foreground">
          Set up a product + campaign. After creating, you can scrape competitor ads, reels, and TikToks.
        </p>
      </div>

      <CampaignForm
        variant="create"
        onSubmit={async (values) => {
          await createCampaign(values)
          // back to the list, where the new campaign appears and can be scraped
          router.push('/campaigns')
        }}
      />
    </div>
  )
}
