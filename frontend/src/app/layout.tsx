import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'GR Report Agent',
  description: 'Upload a GR export and email a plant-wise and Top-10-Buyer GR value report.',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-gray-50 text-gray-900 antialiased">{children}</body>
    </html>
  )
}
