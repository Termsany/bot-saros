import "./globals.css"
import { BRAND } from "@/lib/brand"

export const metadata = { title: `${BRAND.nameCaps} ${BRAND.nameAr} — AI Crypto Trading`, description: `${BRAND.nameAr} — ${BRAND.taglineAr}: 4 بوتات تداول مختبرة، لونج وشورت، مباشر` }

export default function RootLayout({children}:{children:React.ReactNode}){
  return <html lang="ar" dir="rtl"><body className="bg-void text-ink antialiased font-sans">{children}</body></html>
}
