import "./globals.css"
// Self-hosted (npm @fontsource, bundled into /_next/static): next/font/google downloaded the fonts from Google at build
// time, and a bad answer from there failed the build (CI, 2026-11-03, twice in an hour). globals.css names them in the
// --font-cairo / --font-geist / --font-mono variables the tailwind.config.js / globals.css tokens use.
import "@fontsource-variable/cairo"
import "@fontsource-variable/geist"
import "@fontsource/jetbrains-mono/500.css"
import "@fontsource/jetbrains-mono/700.css"
import { headers } from "next/headers"
import { BRAND } from "@/lib/brand"
import { LocaleProvider } from "@/lib/i18n/locale"

export const metadata = { title: `${BRAND.nameCaps} ${BRAND.nameAr} — AI Crypto Trading`, description: `${BRAND.nameAr} — ${BRAND.taglineAr}: 4 بوتات تداول مختبرة، لونج وشورت، مباشر` }

export default async function RootLayout({children}:{children:React.ReactNode}){
  // the page's language: middleware.ts says which (the landing pages, and the bilingual pages by the visitor's choice)
  const en = (await headers()).get("x-raqm-locale") === "en"
  return <html lang={en ? "en" : "ar"} dir={en ? "ltr" : "rtl"} suppressHydrationWarning><body className="bg-void text-ink antialiased font-sans"><LocaleProvider locale={en ? "en" : "ar"}>{children}</LocaleProvider></body></html>
}
