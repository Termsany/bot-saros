"use client"
import { useState } from "react"
import { Check } from "lucide-react"
import { TIERS } from "@/lib/strategies"
import { authHeaders } from "@/lib/supabase"

/** `prices` = the plans' current monthly prices from the backend (the admin can change them); TIERS has the defaults. */
export function Pricing({ prices }: { prices?: Record<string, number> }){
  const [loading, setLoading] = useState<string|null>(null)
  const [err, setErr] = useState("")

  async function checkout(tier: string){
    if(tier==="free"){ location.href="/dashboard"; return }
    setLoading(tier); setErr("")
    // checkout is tied to the signed-in account (guest checkout couldn't be matched to a user)
    const headers = await authHeaders({ "Content-Type":"application/json" })
    if(!headers.Authorization){ location.href = "/auth"; return }
    const res = await fetch("/api/stripe/checkout", {
      method:"POST", headers,
      body: JSON.stringify({ tier })
    })
    const j = await res.json()
    if(res.status===401){ location.href = j.login || "/auth"; return }
    if(j.url) location.href = j.url
    else { setErr(j.error || "خطأ في الدفع"); setLoading(null) }
  }

  return (
    <>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {TIERS.map(t=>(
          <div key={t.id} className={`relative flex flex-col rounded-2xl border p-6 ${t.popular ? "border-corona/70 bg-corona/[0.06]" : "border-line bg-surface"}`}>
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <i className="h-2.5 w-2.5 rounded-full" style={{background: t.color}}/>
                <span className="text-[17px] font-bold">{t.name}</span>
              </div>
              {t.popular && <span className="rounded-full border border-corona/40 bg-corona/10 px-2.5 py-0.5 text-[12px] font-semibold text-corona">الأكثر طلباً</span>}
            </div>
            <div className="mt-4 flex items-baseline gap-1" dir="ltr" style={{justifyContent:"flex-end"}}>
              <span className="font-mono text-[36px] font-bold leading-none">{prices?.[t.id] != null ? `${prices[t.id]}$` : t.price}</span>
              <span className="text-sm text-muted">{t.per}</span>
            </div>
            <ul className="mt-6 flex-1 space-y-2.5 text-sm">
              {t.features.map(f=> <li key={f} className="flex items-start gap-2 text-muted"><Check size={16} className="mt-0.5 shrink-0 text-corona"/>{f}</li>)}
            </ul>
            <button onClick={()=>checkout(t.id)} disabled={loading===t.id}
              className={`mt-6 w-full rounded-xl py-2.5 text-sm font-bold transition disabled:opacity-50 ${t.popular ? "bg-corona text-void hover:bg-corona-soft" : "border border-line bg-surface2 hover:bg-line"}`}>
              {loading===t.id ? "جاري التحويل للدفع..." : t.cta}
            </button>
          </div>
        ))}
      </div>
      {err && <div className="mt-4 rounded-xl border border-loss/30 bg-loss/10 px-4 py-3 text-sm text-loss">{err}</div>}
    </>
  )
}
