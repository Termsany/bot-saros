import { Landing } from "@/components/landing/Landing"
import { LANDING } from "@/lib/i18n/landing"
import { planPrices } from "@/lib/plan-prices"

export const metadata = {
  title: LANDING.en.metaTitle, description: LANDING.en.metaDesc,
  alternates: { canonical: "/", languages: { en: "/", ar: "/ar" } },
  openGraph: { title: LANDING.en.metaTitle, description: LANDING.en.metaDesc, locale: "en_US" },
}

/** The landing page in English, for the world (Arabic: /ar). */
export default async function Page(){
  return <Landing locale="en" prices={await planPrices()}/>
}
