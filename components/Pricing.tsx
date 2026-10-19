"use client"
import { useState } from "react"
import { TIERS, STRATEGIES } from "@/lib/strategies"
import { authHeaders } from "@/lib/supabase"

export function Pricing(){
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
      <div className="grid md:grid-cols-4 gap-4">
        {TIERS.map(t=>(
          <div key={t.id} className={`rounded-2xl border p-5 flex flex-col ${t.popular ? "border-corona bg-corona/[0.06] relative" : "border-line bg-surface"}`}>
            {t.popular && <span className="absolute -top-3 left-1/2 -translate-x-1/2 text-[10px] px-2 py-1 rounded-full bg-corona text-void font-bold">الأكثر طلبا</span>}
            <div className="text-sm font-bold" style={{color:t.color}}>{t.name}</div>
            <div className="mt-1"><span className="text-2xl font-black">{t.price}</span><span className="text-xs text-muted">{t.per}</span></div>
            <div className="text-xs text-muted mt-1">{t.count} استراتيجية</div>
            <ul className="mt-3 space-y-1 text-xs flex-1">
              {t.features.map(f=><li key={f} className="flex gap-1.5"><span className="text-corona">✓</span>{f}</li>)}
            </ul>
            <button onClick={()=>checkout(t.id)} disabled={loading===t.id} className={`mt-4 w-full py-2 rounded-xl text-sm font-bold disabled:opacity-50 ${t.popular ? "bg-corona text-void" : "bg-line text-white border border-faint/50"}`}>
              {loading===t.id ? "جاري..." : t.cta}
            </button>
          </div>
        ))}
      </div>
      {err && <div className="mt-3 text-xs text-loss bg-loss/10 border border-loss/30 rounded-xl px-3 py-2">{err}</div>}
    </>
  )
}
