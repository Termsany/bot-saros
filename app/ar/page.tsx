import { Landing } from "@/components/landing/Landing"
import { LANDING } from "@/lib/i18n/landing"
import { planPrices } from "@/lib/plan-prices"

export const metadata = {
  title: LANDING.ar.metaTitle, description: LANDING.ar.metaDesc,
  alternates: { canonical: "/ar", languages: { en: "/", ar: "/ar" } },
  openGraph: { title: LANDING.ar.metaTitle, description: LANDING.ar.metaDesc, locale: "ar_EG" },
}

/** The landing page in Arabic, right to left (English: /). */
export default async function Page(){
  return <Landing locale="ar" prices={await planPrices()}/>
}
