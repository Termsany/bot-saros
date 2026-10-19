"use client"
import { useEffect, useState } from "react"
import { Logo } from "@/components/Logo"
import { ShieldCheck, Eye, EyeOff, Trash2, Check, AlertTriangle, Key } from "lucide-react"

const EXCHANGES = [
  { id:"binance", name:"Binance", color:"#F3BA2F", desc:"Futures USDT-M" },
  { id:"bybit", name:"Bybit", color:"#F7A600", desc:"Futures USDT" },
  { id:"okx", name:"OKX", color:"#101214", desc:"Futures USDT" },
  { id:"mexc", name:"MEXC", color:"#00D395", desc:"Futures USDT" },
] as const

export default function KeysPage(){
  const [status, setStatus] = useState<Record<string,any>>({})
  const [forms, setForms] = useState<Record<string,{apiKey:string,secret:string,passphrase:string, show:boolean}>>({})
  const [saving, setSaving] = useState<string|null>(null)
  const [msg, setMsg] = useState<{type:string, text:string}|null>(null)
  const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

  async function loadStatus(){
    try{
      const r = await fetch(`${API}/api/keys/status`)
      if(r.ok) setStatus(await r.json())
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
        method:"POST", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({ exchange: ex, apiKey: f.apiKey.trim(), secret: f.secret.trim(), passphrase: f.passphrase.trim() })
      })
      const j = await r.json()
      if(j.ok){
        setMsg({type:"success", text:`${ex} تم الحفظ ✓ — مشفر`})
        setForm(ex, { apiKey:"", secret:"", passphrase:"" })
        loadStatus()
      } else setMsg({type:"error", text: j.error||"فشل"})
    }catch(e:any){ setMsg({type:"error", text: String(e.message||e)}) }
    setSaving(null)
  }

  async function remove(ex: string){
    if(!confirm(`حذف مفاتيح ${ex}؟`)) return
    await fetch(`${API}/api/keys/delete`, { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({exchange: ex}) })
    setMsg({type:"success", text:`${ex} تم الحذف`})
    loadStatus()
  }

  async function togglePaper(ex: string, paper: boolean){
    await fetch(`${API}/api/keys/paper`, { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({exchange: ex, paper}) })
    loadStatus()
  }

  return (
    <div className="min-h-screen bg-[#070B12] text-[#E8EEF8]">
      <header className="flex h-16 items-center justify-between border-b border-[#1c2632] bg-[#0a1018]/90 backdrop-blur px-5 lg:px-8 sticky top-0 z-30">
        <Logo />
        <div className="flex items-center gap-2">
          <a href="/dashboard" className="px-4 py-2 rounded bg-[#00D395] text-[#062016] text-xs font-bold">المنصة</a>
          <a href="/" className="text-xs text-[#778597] hover:text-white">الرئيسية</a>
        </div>
      </header>

      <div className="mx-auto max-w-[1100px] px-5 lg:px-8 py-8">
        <div className="flex items-center gap-3">
          <div className="h-9 w-9 grid place-items-center rounded-xl bg-[#00D395]/10 border border-[#00D395]/20"><Key size={16} className="text-[#00D395]"/></div>
          <div>
            <h1 className="text-lg font-black">مفاتيح المنصات — 4 منصات حقيقية</h1>
            <p className="font-mono text-xs text-[#647386]">Binance · Bybit · OKX · MEXC — كل منصة Toggle وحدها Paper → LIVE</p>
          </div>
        </div>

        <div className="mt-4 rounded-xl border border-[#FFB800]/20 bg-[#FFB800]/[0.06] p-3 flex gap-3">
          <AlertTriangle size={16} className="text-[#FFB800] shrink-0 mt-0.5"/>
          <div className="text-xs leading-relaxed">
            <b className="text-[#FFB800]">تحذير:</b> فعّل <b>Futures فقط</b> + بدون <b>Withdrawal</b> أبداً + ضيف <b>IP Whitelist</b>. البوت <b>Paper افتراضياً</b> — اقلب لـ LIVE يدوياً بعد الاختبار.
          </div>
        </div>

        {msg && (
          <div className={`mt-4 rounded-xl border p-3 text-xs ${msg.type==="success" ? "border-[#00D395]/30 bg-[#00D395]/[0.06] text-[#00D395]" : "border-[#FF3B5C]/30 bg-[#FF3B5C]/[0.06] text-[#FF3B5C]"}`}>
            {msg.text}
          </div>
        )}

        <div className="grid md:grid-cols-2 gap-4 mt-6">
          {EXCHANGES.map(ex=>{
            const st = status[ex.id] || { configured: false, paper: true }
            const form = getForm(ex.id)
            return (
              <div key={ex.id} className={`rounded-xl border p-4 ${st.configured ? (st.paper ? "border-[#FFB800]/30 bg-[#0c131c]" : "border-[#00D395]/30 bg-[#0c131c]") : "border-[#1c2632] bg-[#0c131c]"}`}>
                <div className="flex justify-between items-start">
                  <div className="flex items-center gap-2">
                    <div className="h-8 w-8 rounded-lg grid place-items-center text-xs font-black" style={{background: ex.color+"18", border:`1px solid ${ex.color}30`, color: ex.id==="okx" ? "#fff" : ex.color}}>{ex.name[0]}</div>
                    <div><div className="text-sm font-bold">{ex.name}</div><div className="font-mono text-[11px] text-[#647386]">{ex.desc}</div></div>
                  </div>
                  <div className="flex items-center gap-1.5">
                    {st.configured ? (
                      <>
                        <span className={`h-2 w-2 rounded-full ${st.paper?"bg-[#FFB800]":"bg-[#00D395] animate-pulse"}`}/>
                        <span className={`text-[11px] font-bold font-mono ${st.paper?"text-[#FFB800]":"text-[#00D395]"}`}>{st.paper ? "Paper" : "LIVE"}</span>
                      </>
                    ) : <span className="text-[11px] text-[#5f6e81] font-mono">غير مربوط</span>}
                  </div>
                </div>

                {st.configured && (
                  <div className="mt-3 flex gap-2">
                    <button onClick={()=>togglePaper(ex.id, !st.paper)} className={`flex-1 py-2 rounded-lg text-xs font-bold ${st.paper ? "bg-[#00D395] text-[#062016] hover:bg-[#00b87a]" : "bg-[#FFB800] text-[#1a1300] hover:bg-[#e6a800]"}`}>
                      {st.paper ? "فعّل LIVE" : "ارجع Paper"}
                    </button>
                    <button onClick={()=>remove(ex.id)} className="px-3 py-2 rounded-lg border border-[#1c2632] bg-[#0a1018] text-xs hover:bg-[#1c2632]"><Trash2 size={12}/></button>
                  </div>
                )}

                <div className="mt-4 space-y-2">
                  <input value={form.apiKey} onChange={e=>setForm(ex.id, {apiKey: e.target.value})}
                    placeholder="API Key" className="w-full bg-[#0a1018] border border-[#1d2936] rounded-lg px-3 py-2.5 text-xs font-mono focus:border-[#00D395]/40 outline-none" />
                  <div className="relative">
                    <input value={form.secret} onChange={e=>setForm(ex.id, {secret: e.target.value})}
                      type={form.show ? "text" : "password"} placeholder="Secret"
                      className="w-full bg-[#0a1018] border border-[#1d2936] rounded-lg px-3 py-2.5 pr-9 text-xs font-mono focus:border-[#00D395]/40 outline-none" />
                    <button onClick={()=>setForm(ex.id, {show: !form.show})} className="absolute right-2 top-1/2 -translate-y-1/2 text-[#647386] hover:text-white">
                      {form.show ? <EyeOff size={14}/> : <Eye size={14}/>}
                    </button>
                  </div>
                  {ex.id==="okx" && (
                    <input value={form.passphrase} onChange={e=>setForm(ex.id, {passphrase: e.target.value})}
                      type={form.show ? "text" : "password"} placeholder="Passphrase (OKX فقط)"
                      className="w-full bg-[#0a1018] border border-[#1d2936] rounded-lg px-3 py-2.5 text-xs font-mono focus:border-[#00D395]/40 outline-none" />
                  )}
                  <button onClick={()=>save(ex.id)} disabled={saving===ex.id}
                    className={`w-full py-2.5 rounded-lg text-xs font-bold flex items-center justify-center gap-2 ${saving===ex.id ? "bg-[#1c2632] text-[#647386]" : "bg-[#1c2632] hover:bg-[#1d2936] border border-[#1c2632] text-white"}`}>
                    {saving===ex.id ? "جاري الحفظ..." : <><ShieldCheck size={12}/> حفظ مشفر</>}
                  </button>
                </div>
                <div className="mt-2 font-mono text-[10px] text-[#5f6e81]">مشفر بـ Fernet — لا يظهر أبداً في الشات أو الـ Logs</div>
              </div>
            )
          })}
        </div>

        <div className="mt-6 rounded-xl border border-[#1c2632] bg-[#0c131c] p-4">
          <h3 className="text-xs font-bold flex items-center gap-2"><ShieldCheck size={12} className="text-[#00D395]"/> الأمان</h3>
          <ul className="mt-2 space-y-1 font-mono text-xs text-[#8A9AB0]">
            <li>• المفاتيح مشفرة بـ <b className="text-white">Fernet (AES-128)</b> ومحفوظة في <code className="bg-[#0a1018] px-1 rounded">vault.json</code> بـ <code>600</code></li>
            <li>• لا تُرسل أبداً للفرونت — <code>GET /api/keys/status</code> يرجع <b className="text-white">true/false</b> فقط</li>
            <li>• لا تكتب مفاتيحك في الشات العام — استخدم هذه الصفحة فقط</li>
            <li>• ابدأ بـ <b className="text-[#00D395]">Paper</b> لكل المنصات، وقلّب واحدة واحدة لـ LIVE بعد الاختبار</li>
          </ul>
        </div>
      </div>

      <footer className="mx-auto max-w-[1100px] px-5 lg:px-8 border-t border-[#1c2632] mt-6 py-6 flex justify-between font-mono text-[11px] text-[#5f6e81]">
        <span>Bot Saros © 2026 — Multi-Exchange Vault</span>
        <span>ENGINE <b className="text-[#00D395]">● OPERATIONAL</b></span>
      </footer>
    </div>
  )
}
