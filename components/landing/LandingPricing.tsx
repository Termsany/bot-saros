"use client"
import { useState } from "react"
import { Check } from "lucide-react"
import { TIERS } from "@/lib/strategies"
import { authHeaders } from "@/lib/supabase"
import { LANDING, type Locale } from "@/lib/i18n/landing"

/** The plans, in the page's language. `prices` = the current monthly prices from the API (the admin can change them);
 *  TIERS has the defaults. Checkout needs a signed-in account (a guest checkout couldn't be matched to a user). */
export function LandingPricing({ locale, prices }: { locale: Locale; prices?: Record<string, number> }){
  const t = LANDING[locale].pricing
  const [loading, setLoading] = useState<string | null>(null)
  const [err, setErr] = useState("")

  async function checkout(tier: string){
    if(tier === "free"){ location.href = "/dashboard"; return }
    setLoading(tier); setErr("")
    const headers = await authHeaders({ "Content-Type": "application/json" })
    if(!headers.Authorization){ location.href = "/auth"; return }
    const res = await fetch("/api/stripe/checkout", { method: "POST", headers, body: JSON.stringify({ tier }) })
    const j = await res.json().catch(() => ({}))
    if(res.status === 401){ location.href = j.login || "/auth"; return }
    if(j.url) location.href = j.url
    else { setErr(j.error || t.error); setLoading(null) }
  }

  return (
    <>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {TIERS.map(tier => {
          const price = prices?.[tier.id] != null ? `$${prices[tier.id]}` : tier.price.replace(/^(\d+)\$$/, "$$$1")
          return (
            <div key={tier.id} className={`relative flex flex-col rounded-[20px] border p-6 transition duration-300 hover:-translate-y-1 ${tier.popular ? "border-corona/70 bg-corona/[0.05] shadow-[0_18px_50px_-24px_rgb(var(--c-corona)/.55)]" : "border-line bg-surface hover:border-line2"}`}>
              <div className="flex items-center justify-between gap-2">
                <span className="text-[18px] font-semibold">{tier.name}</span>
                {tier.popular && <span className="rounded-full border border-corona/40 bg-corona/10 px-2.5 py-0.5 text-[11px] font-semibold text-corona">{t.popular}</span>}
              </div>
              <div className="mt-4 flex items-baseline gap-1.5" dir="ltr" style={{ justifyContent: locale === "ar" ? "flex-end" : "flex-start" }}>
                <span className="font-mono text-[38px] font-bold leading-none tabular">{price}</span>
                <span className="text-[13px] text-faint">{t.per}</span>
              </div>
              <ul className="mt-6 flex-1 space-y-2.5 text-[14px]">
                {(t.features[tier.id] || []).map(f => <li key={f} className="flex items-start gap-2 text-muted"><Check size={16} className="mt-0.5 shrink-0 text-profit"/>{f}</li>)}
              </ul>
              <button onClick={() => checkout(tier.id)} disabled={loading === tier.id}
                className={`mt-6 w-full rounded-xl py-2.5 text-[14px] font-semibold transition disabled:opacity-50 ${tier.popular ? "bg-corona text-on-corona hover:bg-corona-soft" : "border border-line bg-surface2 hover:border-line2 hover:bg-surface"}`}>
                {loading === tier.id ? t.redirect : t.cta[tier.id]}
              </button>
            </div>
          )
        })}
      </div>
      <p className="mt-5 text-center text-[13px] leading-6 text-muted">{t.note[0]}<b className="text-ink">{t.note[1]}</b>{t.note[2]}<a href="/terms" className="text-corona underline">{t.terms}</a>.</p>
      {err && <div className="mt-4 rounded-xl border border-loss/30 bg-loss/10 px-4 py-3 text-sm text-loss">{err}</div>}
    </>
  )
}
