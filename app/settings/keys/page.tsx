"use client"
import { useEffect, useState } from "react"
import { AppShell } from "@/components/AppShell"
import { Card, PageHeader, Pill, btn, field } from "@/components/ui"
import { ShieldCheck, Eye, EyeOff, Trash2 } from "lucide-react"
import { authHeaders } from "@/lib/supabase"

const EXCHANGES = [
  { id:"binance", name:"Binance", color:"#F3BA2F", desc:"Futures USDT-M" },
  { id:"bybit", name:"Bybit", color:"#F7A600", desc:"Futures USDT" },
  { id:"okx", name:"OKX", color:"#101214", desc:"Futures USDT" },
  { id:"mexc", name:"MEXC", color:"#22D3A0", desc:"Futures USDT" },
] as const

export default function KeysPage(){
  const [status, setStatus] = useState<Record<string,any>>({})
  const [forms, setForms] = useState<Record<string,{apiKey:string,secret:string,passphrase:string, show:boolean}>>({})
  const [saving, setSaving] = useState<string|null>(null)
  const [msg, setMsg] = useState<{type:string, text:string}|null>(null)
  const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

  async function loadStatus(){
    try{
      const r = await fetch(`${API}/api/keys/status`, { headers: await authHeaders() })
      if(r.ok) setStatus(await r.json())
      else setMsg({type:"error", text: (await r.json().catch(()=>({}))).detail || "للأدمن فقط — سجّل دخول بحساب الأدمن"})
    }catch{}
  }
  useEffect(()=>{ loadStatus() }, [])

  function getForm(ex: string){
    if(!forms[ex]) return { apiKey:"", secret:"", passphrase:"", show:false }
    return forms[ex]
  }
  function setForm(ex: string, patch: Partial<{apiKey:string,secret:string,passphrase:string,show:boolean}>){
    setForms(f=> ({ ...f, [ex]: { ...getForm(ex), ...patch }}))
  }

  async function save(ex: string){
    const f = getForm(ex)
    if(!f.apiKey || !f.secret){ setMsg({type:"error", text:"ضع API Key و Secret"}); return }
    setSaving(ex); setMsg(null)
    try{
      const r = await fetch(`${API}/api/keys/save`, {
        method:"POST", headers: await authHeaders({"Content-Type":"application/json"}),
        body: JSON.stringify({ exchange: ex, apiKey: f.apiKey.trim(), secret: f.secret.trim(), passphrase: f.passphrase.trim() })
      })
      const j = await r.json()
      if(j.ok){
        setMsg({type:"success", text:`${ex} تم الحفظ ✓ — مشفر (وضع Paper — فعّل LIVE يدوياً)`})
        setForm(ex, { apiKey:"", secret:"", passphrase:"" })
        loadStatus()
      } else setMsg({type:"error", text: j.error||j.detail||"فشل"})
    }catch(e:any){ setMsg({type:"error", text: String(e.message||e)}) }
    setSaving(null)
  }

  async function remove(ex: string){
    if(!confirm(`حذف مفاتيح ${ex}؟`)) return
    await fetch(`${API}/api/keys/delete`, { method:"POST", headers: await authHeaders({"Content-Type":"application/json"}), body: JSON.stringify({exchange: ex}) })
    setMsg({type:"success", text:`${ex} تم الحذف`})
    loadStatus()
  }

  async function togglePaper(ex: string, paper: boolean){
    if(!paper && !confirm(`تفعيل التداول الحقيقي على ${ex}؟ البوت هيفتح صفقات بفلوس حقيقية.`)) return
    const r = await fetch(`${API}/api/keys/paper`, { method:"POST", headers: await authHeaders({"Content-Type":"application/json"}), body: JSON.stringify({exchange: ex, paper}) })
    if(!r.ok) setMsg({type:"error", text: (await r.json().catch(()=>({}))).detail || "فشل"})
    loadStatus()
  }

  const connected = EXCHANGES.filter(ex => status[ex.id]?.configured).length
  return (
    <AppShell active="/settings/keys">
      <PageHeader title="مفاتيح المنصات" subtitle="متشفرة على السيرفر · محدش يقدر يشوفها بعد ما تتحفظ، ولا انت"
        status={<Pill tone={connected ? "profit" : "neutral"}>{connected} من {EXCHANGES.length} متصلة</Pill>}/>

      {msg && (
        <div className={`rounded-xl border p-3 text-sm ${msg.type==="success" ? "border-profit/30 bg-profit/[0.06] text-profit" : "border-loss/30 bg-loss/[0.06] text-loss"}`}>{msg.text}</div>
      )}

      <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="grid gap-5 md:grid-cols-2">
          {EXCHANGES.map(ex=>{
            const st = status[ex.id] || { configured: false, paper: true }
            const form = getForm(ex.id)
            return (
              <Card key={ex.id} className={st.configured ? (st.paper ? "border-corona/40" : "border-profit/50") : ""}>
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-center gap-2.5">
                    <div className="grid h-[34px] w-[34px] place-items-center rounded-[10px] bg-surface2 text-sm font-bold text-corona">{ex.name[0]}</div>
                    <div><div className="text-[17px] font-bold">{ex.name}</div><div className="text-[12px] text-muted">{ex.desc}</div></div>
                  </div>
                  {st.configured
                    ? <Pill tone={st.paper ? "corona" : "profit"}>● {st.paper ? "متصل · Paper" : "متصل · LIVE"}</Pill>
                    : <Pill>مش متصل</Pill>}
                </div>

                {st.configured && (
                  <div className="mt-4 flex gap-2">
                    <button onClick={()=>togglePaper(ex.id, !st.paper)} className={`${st.paper ? btn.secondary : btn.primary} flex-1`}>
                      {st.paper ? "فعّل LIVE" : "ارجع Paper"}
                    </button>
                    <button onClick={()=>remove(ex.id)} aria-label={`امسح مفاتيح ${ex.name}`} className={btn.ghost}><Trash2 size={15}/></button>
                  </div>
                )}

                <div className="mt-4 space-y-2.5">
                  <input value={form.apiKey} onChange={e=>setForm(ex.id, {apiKey: e.target.value})} placeholder="API key" aria-label={`${ex.name} API key`} className={`${field} font-mono`} dir="ltr"/>
                  <div className="relative">
                    <input value={form.secret} onChange={e=>setForm(ex.id, {secret: e.target.value})} type={form.show ? "text" : "password"} placeholder="Secret" aria-label={`${ex.name} secret`} className={`${field} pr-10 font-mono`} dir="ltr"/>
                    <button onClick={()=>setForm(ex.id, {show: !form.show})} aria-label={form.show ? "اخفي" : "اظهر"} className="absolute right-3 top-1/2 -translate-y-1/2 text-faint hover:text-ink">
                      {form.show ? <EyeOff size={15}/> : <Eye size={15}/>}
                    </button>
                  </div>
                  {ex.id==="okx" && (
                    <input value={form.passphrase} onChange={e=>setForm(ex.id, {passphrase: e.target.value})} type={form.show ? "text" : "password"} placeholder="Passphrase (OKX بس)" aria-label="OKX passphrase" className={`${field} font-mono`} dir="ltr"/>
                  )}
                  <button onClick={()=>save(ex.id)} disabled={saving===ex.id} className={`${btn.secondary} w-full`}>
                    {saving===ex.id ? "بيحفظ…" : <><ShieldCheck size={15}/> احفظ متشفّر</>}
                  </button>
                </div>
              </Card>
            )
          })}
        </div>

        <Card>
          <h2 className="mb-4 text-[17px] font-bold">قبل ما تعمل المفتاح</h2>
          <div className="space-y-4">
            {[["اقفل صلاحية السحب", "البوت مش محتاجها، ومن غيرها محدش يقدر ياخد فلوسك"], ["فعّل Futures بس", "ده كل اللي البوت بيستخدمه"],
              ["اربط المفتاح بـ IP السيرفر", "لو المفتاح اتسرق ما يشتغلش من أي مكان تاني"], ["ابدأ بـ Paper", "وقلّب منصة واحدة لـ LIVE بعد ما تختبر"]].map(([l, h]) => (
              <div key={l} className="flex gap-2.5">
                <span className="mt-0.5 grid h-[22px] w-[22px] shrink-0 place-items-center rounded-full bg-profit/15 text-[11px] text-profit">✓</span>
                <div><div className="text-[14px] font-semibold">{l}</div><div className="text-[12px] leading-5 text-muted">{h}</div></div>
              </div>
            ))}
          </div>
          <p className="mt-5 rounded-xl bg-surface2 p-3 text-[12px] leading-6 text-muted">المفاتيح متشفرة بـ Fernet على السيرفر، ومش بتتبعت للمتصفح تاني: الصفحة دي بتعرف بس إذا كان فيه مفتاح ولا لأ.</p>
        </Card>
      </div>
    </AppShell>
  )
}
