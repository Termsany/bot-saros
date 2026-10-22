"use client"
import { useState } from "react"
import { Check } from "lucide-react"
import { TIERS } from "@/lib/strategies"
import { authHeaders } from "@/lib/supabase"

export function Pricing(){
  const [loading, setLoading] = useState<string|null>(null)
  const [err, setErr] = useState("")

  async function checkout(tier: string){
    if(tier==="free"){ location.href="/dashboard"; return }
    setLoading(tier); setErr("")
    const headers = await authHeaders()
    if(!headers.Authorization){ location.href = "/auth"; return }
    location.href = `/pay?tier=${encodeURIComponent(tier)}`
  }

  return (
    <>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {TIERS.map(t=>(
          <div key={t.id} className={`relative flex flex-col rounded-2xl border p-6 ${t.popular ? "border-corona/60 bg-gradient-to-b from-corona/[0.08] to-surface shadow-[0_20px_60px_-30px_rgba(245,184,65,0.5)]" : "border-line bg-surface"}`}>
            {t.popular && <span className="absolute -top-3 left-1/2 -translate-x-1/2 rounded-full bg-corona px-3 py-1 text-[11px] font-bold text-void">الأكثر طلباً</span>}
            <div className="flex items-center gap-2">
              <i className="h-2.5 w-2.5 rounded-full" style={{background: t.color}}/>
              <span className="font-display text-base font-bold">{t.name}</span>
            </div>
            <div className="mt-4 flex items-baseline gap-1" dir="ltr" style={{justifyContent:"flex-end"}}>
              <span className="font-display text-[40px] font-bold leading-none">{t.price}</span>
              <span className="text-sm text-muted">{t.per}</span>
            </div>
            <ul className="mt-6 flex-1 space-y-2.5 text-sm">
              {t.features.map(f=> <li key={f} className="flex items-start gap-2"><Check size={16} className="mt-0.5 shrink-0 text-corona"/>{f}</li>)}
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
