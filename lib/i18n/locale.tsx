"use client"
// The page's language, for client components: the root layout knows it (middleware.ts → x-raqm-locale) and provides
// it here, so a component renders the same words on the server and in the browser.
import { createContext, useContext } from "react"
import type { Locale } from "./landing"

const Ctx = createContext<Locale>("ar")

export function LocaleProvider({ locale, children }: { locale: Locale; children: React.ReactNode }){
  return <Ctx.Provider value={locale}>{children}</Ctx.Provider>
}

export const useLocale = () => useContext(Ctx)

/** Pick this page's words from a { en, ar } table. */
export function useT<T>(table: Record<Locale, T>): T { return table[useContext(Ctx)] }

/** The cookie the app's pages read for their language (the landing pages set it, the switches change it). */
export const LANG_COOKIE = "raqm-lang"
export function setLanguage(locale: Locale){
  document.cookie = `${LANG_COOKIE}=${locale}; path=/; max-age=31536000; samesite=lax`
  location.reload()
}

/** "from 5 minutes ago" in the page's language. */
export function agoText(iso: string | undefined, locale: Locale){
  if (!iso) return "—"
  const s = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 1000))
  const [n, u] = s < 60 ? [s, 0] : s < 3600 ? [Math.round(s / 60), 1] : s < 86400 ? [Math.round(s / 3600), 2] : [Math.round(s / 86400), 3]
  return locale === "en" ? `${n} ${["s", "min", "h", "d"][u]} ago` : `من ${n} ${["ثانية", "دقيقة", "ساعة", "يوم"][u]}`
}
