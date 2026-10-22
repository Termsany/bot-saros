"use client"
import { useEffect, useState } from "react"
import { authHeaders } from "@/lib/supabase"

const labels:Record<string,string>={starter:"Starter",pro:"Pro",elite:"Elite"}
export function ManualPaymentsAdmin(){
  const [rows,setRows]=useState<any[]>([]), [msg,setMsg]=useState("")
  async function load(){
    const r=await fetch("/api/admin/payments?status=pending",{headers:await authHeaders()})
    if(r.ok)setRows((await r.json()).payments||[]); else setMsg("غير مصرح أو تعذر تحميل المدفوعات")
  }
  useEffect(()=>{load()},[])
  async function review(id:number,action:"approve"|"reject"){
    const note=prompt(action==="approve"?"ملاحظة الاعتماد (اختياري)":"سبب الرفض")||""
    const r=await fetch("/api/admin/payments",{method:"PATCH",headers:await authHeaders({"Content-Type":"application/json"}),body:JSON.stringify({id,action,note})})
    const j=await r.json().catch(()=>({}))
    if(r.ok) setMsg(action==="approve" ? (j.status==="approved" ? "تم التفعيل 30 يوم" : j.error||"تمت المعالجة") : j.status==="rejected" ? "تم الرفض" : j.error||"تمت المعالجة"); else setMsg(j.error||"فشل الإجراء"); await load()
  }
  return <section className="mt-6 rounded-2xl border border-line bg-surface p-4">
    <div className="flex items-center justify-between"><div><h2 className="text-sm font-black">مدفوعات USDT اليدوية</h2><p className="text-xs text-muted">راجع التحويل داخل Binance أو مستكشف الشبكة قبل الاعتماد.</p></div><button onClick={load} className="rounded border border-line px-3 py-1 text-xs">تحديث</button></div>
    {msg&&<p className="mt-2 text-xs text-corona">{msg}</p>}
    <div className="mt-3 overflow-x-auto"><table className="w-full min-w-[760px] text-xs"><thead className="text-muted"><tr><th className="p-2 text-right">المستخدم</th><th>الباقة</th><th>المبلغ</th><th>الطريقة/الشبكة</th><th>Reference</th><th>التاريخ</th><th>الإجراء</th></tr></thead><tbody>{rows.map(p=><tr key={p.id} className="border-t border-line"><td className="p-2">{p.email||p.user_id}</td><td>{labels[p.tier]}</td><td className="font-mono">{p.amount_usdt} USDT</td><td>{p.method} / {p.network}</td><td className="max-w-[220px] break-all font-mono" dir="ltr">{p.reference}</td><td>{new Date(p.created_at).toLocaleString("ar-EG")}</td><td><div className="flex gap-1"><button onClick={()=>review(p.id,"approve")} className="rounded bg-profit px-2 py-1 font-bold text-void">اعتماد</button><button onClick={()=>review(p.id,"reject")} className="rounded bg-loss px-2 py-1 font-bold text-white">رفض</button></div></td></tr>)}</tbody></table>{!rows.length&&<p className="p-4 text-center text-muted">مفيش طلبات تحت المراجعة</p>}</div>
  </section>
}
