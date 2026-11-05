import type { Metadata } from "next"
import { headers } from "next/headers"
import { LANDING } from "@/lib/i18n/landing"

/** The browser-tab title of a page built in both languages, in the visitor's language (middleware.ts → x-raqm-locale).
 *  The pages themselves are client components, so a tiny server layout.tsx next to each one exports this. */
export function localeTitle(t: { en: string; ar: string }){
  return async function generateMetadata(): Promise<Metadata>{
    const en = (await headers()).get("x-raqm-locale") === "en"
    return en ? { title: `${t.en} — RAQM`, description: LANDING.en.metaDesc } : { title: `${t.ar} — رقم RAQM` }
  }
}
