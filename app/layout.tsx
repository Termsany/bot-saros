import "./globals.css"
import { BRAND } from "@/lib/brand"
import { Cairo, JetBrains_Mono } from "next/font/google"

const cairo = Cairo({
  subsets: ["arabic", "latin"],
  weight: ["400","600","700","800","900"],
  variable: "--font-cairo",
  display: "swap",
})

const jetbrains = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400","600","700"],
  variable: "--font-mono",
  display: "swap",
})

export const metadata = { title: `${BRAND.nameCaps} ${BRAND.nameAr} — AI Crypto Trading`, description: `${BRAND.nameAr} — ${BRAND.taglineAr}: 15 استراتيجية LONG/SHORT` }

export default function RootLayout({children}:{children:React.ReactNode}){
  return <html lang="ar" dir="rtl" className={`${cairo.variable} ${jetbrains.variable}`}><body className="bg-[#070B12] text-[#E6EEF8] antialiased font-[var(--font-cairo)]">{children}</body></html>
}
