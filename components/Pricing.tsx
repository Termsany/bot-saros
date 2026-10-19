"use client"
import { useState } from "react"
import { TIERS, STRATEGIES } from "@/lib/strategies"
import { supabase } from "@/lib/supabase"

export function Pricing(){
  const [loading, setLoading] = useState<string|null>(null)
  const [err, setErr] = useState("")

  async function checkout(tier: string){
    if(tier==="free"){ location.href="/dashboard"; return }
    setLoading(tier); setErr("")
    let email: string | undefined
    try{ const { data } = await supabase.auth.getUser(); email = data.user?.email || undefined }catch{}
    if(!email){
      // allow guest checkout — Stripe will collect email
    }
    const res = await fetch("/api/stripe/checkout", {
      method:"POST", headers:{ "Content-Type":"application/json" },
      body: JSON.stringify({ tier, email })
    })
    const j = await res.json()
    if(j.url) location.href = j.url
    else { setErr(j.error || "خطأ في الدفع"); setLoading(null) }
  }

  return (
    <>
      <div className="grid md:grid-cols-4 gap-4">
        {TIERS.map(t=>(
          <div key={t.id} className={`rounded-2xl border p-5 flex flex-col ${t.popular ? "border-[#00D395] bg-[#0A1A1A] relative" : "border-[#1E2A3A] bg-[#111827]"}`}>
            {t.popular && <span className="absolute -top-3 left-1/2 -translate-x-1/2 text-[10px] px-2 py-1 rounded-full bg-[#00D395] text-[#062016] font-bold">الأكثر طلبا</span>}
            <div className="text-sm font-bold" style={{color:t.color}}>{t.name}</div>
            <div className="mt-1"><span className="text-2xl font-black">{t.price}</span><span className="text-xs text-[#8A9AB0]">{t.per}</span></div>
            <div className="text-xs text-[#8A9AB0] mt-1">{t.count} استراتيجية</div>
            <ul className="mt-3 space-y-1 text-xs flex-1">
              {t.features.map(f=><li key={f} className="flex gap-1.5"><span className="text-[#00D395]">✓</span>{f}</li>)}
            </ul>
            <button onClick={()=>checkout(t.id)} disabled={loading===t.id} className={`mt-4 w-full py-2 rounded-xl text-sm font-bold disabled:opacity-50 ${t.popular ? "bg-[#00D395] text-[#062016]" : "bg-[#1E2A3A] text-white border border-[#2a3a56]"}`}>
              {loading===t.id ? "جاري..." : t.cta}
            </button>
          </div>
        ))}
      </div>
      {err && <div className="mt-3 text-xs text-[#FF6B6B] bg-[#1A0F0F] border border-[#3a1a1a] rounded-xl px-3 py-2">{err}</div>}
    </>
  )
}
