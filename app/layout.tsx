import "./globals.css"
import { Cairo, JetBrains_Mono } from "next/font/google"
import { BRAND } from "@/lib/brand"

// The tokens in tailwind.config.js / globals.css name these variables; without next/font they were never defined and
// every page fell back to the system font
const cairo = Cairo({ subsets: ["arabic", "latin"], weight: ["400", "500", "600", "700", "800", "900"], variable: "--font-cairo", display: "swap" })
const mono = JetBrains_Mono({ subsets: ["latin"], weight: ["500", "700"], variable: "--font-mono", display: "swap" })

export const metadata = { title: `${BRAND.nameCaps} ${BRAND.nameAr} — AI Crypto Trading`, description: `${BRAND.nameAr} — ${BRAND.taglineAr}: 4 بوتات تداول مختبرة، لونج وشورت، مباشر` }

export default function RootLayout({children}:{children:React.ReactNode}){
  return <html lang="ar" dir="rtl" className={`${cairo.variable} ${mono.variable}`}><body className="bg-void text-ink antialiased font-sans">{children}</body></html>
}
