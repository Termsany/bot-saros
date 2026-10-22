"use client"
import { useEffect, useMemo, useState } from "react"
import { authHeaders } from "@/lib/supabase"
import { Logo } from "@/components/Logo"

const labels: Record<string,string> = { starter:"Starter", pro:"Pro", elite:"Elite" }
type Network = { id:string; name:string; address:string; note:string }
type Config = { binancePay:{id:string;nickname:string}; networks:Network[]; prices:Record<string,number>; nowpayments:boolean }

export default function PayPage(){
  const [tier,setTier]=useState("pro"), [cfg,setCfg]=useState<Config|null>(null)
  const [method,setMethod]=useState("binance_pay"), [network,setNetwork]=useState("")
  const [reference,setReference]=useState(""), [note,setNote]=useState(""), [intent,setIntent]=useState<any>(null)
  const [message,setMessage]=useState(""), [busy,setBusy]=useState(false), [history,setHistory]=useState<any[]>([])
  useEffect(()=>{
    const requested = new URLSearchParams(location.search).get("tier") || "pro"
    if(labels[requested]) setTier(requested)
    fetch("/api/payments/config").then(r=>r.json()).then((c:Config)=>{ setCfg(c); if(!c.binancePay.id && c.networks[0]){ setMethod("onchain"); setNetwork(c.networks[0].id) } })
    loadHistory()
  },[])
  async function loadHistory(){
    const h=await authHeaders(); if(!h.Authorization) return
    const r=await fetch("/api/payments/manual",{headers:h}); if(r.ok) setHistory((await r.json()).payments||[])
  }
  const selected=useMemo(()=>cfg?.networks.find(n=>n.id===network),[cfg,network])
  async function copy(v:string){ await navigator.clipboard.writeText(v); setMessage("تم النسخ") }
  async function payNowpayments(){
    setBusy(true); setMessage("")
    const headers=await authHeaders({"Content-Type":"application/json"})
    if(!headers.Authorization){ location.href="/auth"; return }
    const r=await fetch("/api/payments/nowpayments/checkout",{method:"POST",headers,body:JSON.stringify({tier})})
    const j=await r.json().catch(()=>({}))
    if(r.ok && j.invoice_url) location.href=j.invoice_url
    else { setMessage(j.error||"تعذر إنشاء الفاتورة"); setBusy(false) }
  }
  async function createIntent(){
    setBusy(true); setMessage("")
    const headers=await authHeaders({"Content-Type":"application/json"})
    if(!headers.Authorization){ location.href="/auth"; return }
    const r=await fetch("/api/payments/manual",{method:"POST",headers,body:JSON.stringify({tier,method,network})})
    const j=await r.json().catch(()=>({}))
    if(r.ok) setIntent(j.payment); else if(j.payment) setIntent(j.payment)
    setMessage(r.ok?"تم حجز مبلغ الدفع الخاص بحسابك. حوّل المبلغ الظاهر بالضبط.":(j.error||"تعذر إنشاء الطلب")); setBusy(false)
  }
  async function submit(){
    if(!intent) return
    setBusy(true); setMessage("")
    const headers=await authHeaders({"Content-Type":"application/json"})
    if(!headers.Authorization){ location.href="/auth"; return }
    const r=await fetch("/api/payments/manual",{method:"PATCH",headers,body:JSON.stringify({id:intent.id,reference,note})})
    const j=await r.json().catch(()=>({}))
    if(r.ok){ setMessage("تم إرسال المرجع للمراجعة. هتشوف الحالة هنا بعد الاعتماد."); setReference(""); setNote(""); setIntent(null); await loadHistory() }
    else setMessage(j.error||"تعذر إرسال المرجع")
    setBusy(false)
  }
  const amount=intent?.amount_usdt ?? cfg?.prices?.[tier]
  const payReady=method==="binance_pay" ? !!cfg?.binancePay.id : !!selected
  return <main className="min-h-screen bg-void text-ink" dir="rtl">
    <header className="border-b border-line bg-surface/90 px-5 py-3"><div className="mx-auto flex max-w-4xl items-center justify-between"><Logo size="sm"/><a href="/" className="text-sm text-muted">الرئيسية</a></div></header>
    <div className="mx-auto max-w-4xl space-y-5 px-5 py-8">
      <div><h1 className="text-2xl font-black">دفع الاشتراك بـ USDT</h1><p className="mt-1 text-sm text-muted">الباقة: <b>{labels[tier]}</b> · {intent?"المبلغ الدقيق":"السعر الأساسي"}: <b className="font-mono text-corona">{amount ?? "—"} USDT</b> لمدة 30 يوم</p></div>
      {cfg?.nowpayments&&<div className="rounded-2xl border border-emerald-500/30 bg-emerald-500/10 p-4 text-sm leading-7"><b>دفع أوتوماتيك ✨</b> — ادفع بأي عملة مشفرة (BTC/ETH/USDT...) عبر NOWPayments والتفعيل يتم تلقائياً بعد تأكيد الشبكة. <button onClick={payNowpayments} disabled={busy} className="mt-2 w-full rounded-xl bg-emerald-500 py-2.5 font-bold text-white disabled:opacity-40">{busy?"جاري إنشاء الفاتورة...":"ادفع أوتوماتيك بأي عملة — تفعيل فوري"}</button></div>}
      <div className="rounded-2xl border border-corona/30 bg-corona/5 p-4 text-sm leading-7">أو أنشئ طلب <b>يدوي</b> — حوّل <b>المبلغ المميز الظاهر بالضبط</b> على الشبكة المختارة. المراجعة يدوية و<b>لا يتم تفعيل الباقة قبل المراجعة</b>.</div>
      <section className="rounded-2xl border border-line bg-surface p-5">
        <h2 className="font-bold">1) اختار طريقة التحويل</h2>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <button onClick={()=>{setMethod("binance_pay");setIntent(null)}} disabled={!cfg?.binancePay.id} className={`rounded-xl border p-4 text-right ${method==="binance_pay"?"border-corona bg-corona/10":"border-line"} disabled:opacity-40`}><b>Binance Pay</b><div className="text-xs text-muted">تحويل داخلي يدوي ومراجعة Order ID</div></button>
          <button onClick={()=>{setMethod("onchain");setIntent(null);if(!network&&cfg?.networks[0])setNetwork(cfg.networks[0].id)}} disabled={!cfg?.networks.length} className={`rounded-xl border p-4 text-right ${method==="onchain"?"border-corona bg-corona/10":"border-line"} disabled:opacity-40`}><b>تحويل USDT على شبكة</b><div className="text-xs text-muted">Plasma أو شبكة أخرى مفعّلة برسوم منخفضة</div></button>
        </div>
        {!payReady&&cfg&&<p className="mt-3 text-sm text-loss">طريقة الدفع دي لسه محتاجة بيانات الاستلام من الإدارة.</p>}
        {!intent&&<button onClick={createIntent} disabled={busy||!payReady} className="mt-4 w-full rounded-xl border border-corona bg-corona/10 py-3 font-bold text-corona disabled:opacity-40">{busy?"جاري الإنشاء...":"إنشاء طلب الدفع وعرض بيانات التحويل"}</button>}
        {intent&&method==="binance_pay"&&cfg?.binancePay.id&&<div className="mt-4 rounded-xl bg-surface2 p-4"><div className="text-xs text-muted">Binance Pay ID</div><div className="mt-1 flex items-center gap-2" dir="ltr"><code className="break-all font-mono text-lg">{cfg.binancePay.id}</code><button onClick={()=>copy(cfg.binancePay.id)} className="rounded border border-line px-2 py-1 text-xs">نسخ</button></div>{cfg.binancePay.nickname&&<div className="mt-1 text-xs text-muted">الاسم: {cfg.binancePay.nickname}</div>}</div>}
        {method==="onchain"&&<div className="mt-4 space-y-3"><select value={network} onChange={e=>{setNetwork(e.target.value);setIntent(null)}} className="w-full rounded-xl border border-line bg-surface2 px-3 py-2"> <option value="">اختر الشبكة</option>{cfg?.networks.map(n=><option key={n.id} value={n.id}>{n.name}</option>)}</select>{selected&&intent&&<div className="rounded-xl bg-surface2 p-4"><div className="text-xs text-muted">عنوان الاستلام — {selected.name}</div><div className="mt-1 flex items-center gap-2" dir="ltr"><code className="min-w-0 flex-1 break-all font-mono text-sm">{selected.address}</code><button onClick={()=>copy(selected.address)} className="rounded border border-line px-2 py-1 text-xs">نسخ</button></div><p className="mt-2 text-xs text-loss">{selected.note} — اختيار شبكة غلط ممكن يضيّع التحويل.</p></div>}</div>}
      </section>
      <section className="rounded-2xl border border-line bg-surface p-5"><h2 className="font-bold">2) ابعت المرجع للمراجعة</h2><label className="mt-3 block text-xs text-muted">{method==="binance_pay"?"Binance Pay Order ID / Reference":"Transaction Hash (TxID)"}</label><input value={reference} onChange={e=>setReference(e.target.value)} dir="ltr" placeholder="اكتب المرجع كامل" className="mt-1 w-full rounded-xl border border-line bg-surface2 px-3 py-2 font-mono"/><label className="mt-3 block text-xs text-muted">ملاحظة اختيارية</label><input value={note} onChange={e=>setNote(e.target.value)} placeholder="اسم حساب Binance أو أي توضيح" className="mt-1 w-full rounded-xl border border-line bg-surface2 px-3 py-2"/><button onClick={submit} disabled={busy||!intent||reference.trim().length<6} className="mt-4 w-full rounded-xl bg-corona py-3 font-bold text-void disabled:opacity-40">{busy?"جاري الإرسال...":"أرسلت التحويل — راجع الدفع"}</button>{message&&<p className="mt-3 text-sm text-corona">{message}</p>}</section>
      {!!history.length&&<section className="rounded-2xl border border-line bg-surface p-5"><h2 className="font-bold">طلباتك</h2><div className="mt-3 space-y-2">{history.map(p=><div key={p.id} className="flex flex-wrap justify-between gap-2 rounded-xl bg-surface2 p-3 text-sm"><span>{labels[p.tier]} · {p.amount_usdt} USDT · {p.network}</span><b className={p.status==="approved"?"text-profit":p.status==="rejected"?"text-loss":"text-corona"}>{p.status==="approved"?"تم التفعيل":p.status==="rejected"?"مرفوض":"تحت المراجعة"}</b></div>)}</div></section>}
    </div>
  </main>
}
