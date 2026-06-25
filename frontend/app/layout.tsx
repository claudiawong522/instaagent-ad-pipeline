import type { Metadata } from 'next'
import localFont from 'next/font/local'
import './globals.css'
import { Navbar } from '@/components/layout/Navbar'
import { TooltipProvider } from '@/components/ui/tooltip'

const geist = localFont({
  src: './fonts/GeistVF.woff',
  variable: '--font-sans',
  weight: '100 900',
})

export const metadata: Metadata = {
  title: 'InstaAgent — Ad Search',
  description: 'Semantic search over a database of paid ads and organic videos.',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={geist.variable}>
      <body className="font-sans antialiased bg-background text-foreground min-h-screen">
        <TooltipProvider>
          <Navbar />
          <main className="mx-auto max-w-6xl px-4 sm:px-6 py-8">{children}</main>
        </TooltipProvider>
      </body>
    </html>
  )
}
