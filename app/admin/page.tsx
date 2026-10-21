"use client"
import { Logo } from "@/components/Logo"
import { useState } from "react"
import { STRATEGIES, TIERS } from "@/lib/strategies"
import { authHeaders } from "@/lib/supabase"

export default function AdminPage(){
  const [tiers, setTiers] = useState(TIERS)
  const [strategies, setStrategies] = useState(STRATEGIES)
  const [saved, setSaved] = useState("")

  function updateTier(idx:number, field:string, val:any){
    setTiers(t=> t.map((x,i)=> i===idx ? {...x, [field]: val} : x))
  }
  function updateStrat(idx:number, field:string, val:any){
    setStrategies(s=> s.map((x,i)=> i===idx ? {...x, [field]: val} : x))
  }

  return (
    <div className="min-h-screen bg-void text-ink p-4" dir="rtl">
      <div className="max-w-[1200px] mx-auto">
        <div className="flex justify-between items-center">
          <div className="flex items-center gap-3"><Logo size="sm" /><h1 className="text-lg font-black">لوحة تحكم الأدمن</h1></div>
          <div className="flex items-center gap-2">
            <a href="/dashboard" className="text-xs px-3 py-1.5 rounded border border-line hover:bg-surface">المنصة</a>
            <a href="/" className="text-xs px-3 py-1.5 rounded-xl border border-line">الرئيسية</a>
          </div>
        </div>
        <p className="text-xs text-muted mt-1">عدّل التسعير وأسماء البوتات للمعاينة — احفظها في lib/strategies.ts للنشر. أرقام الأداء بتيجي من research/bots_stats.py ومش بتتعدّل بإيدك.</p>

        <div className="mt-6">
          <h2 className="text-sm font-black">الباقات — التسعير</h2>
          <div className="grid md:grid-cols-4 gap-3 mt-3">
            {tiers.map((t,i)=>(
              <div key={t.id} className="rounded-2xl border border-line bg-surface p-3">
                <input value={t.name} onChange={e=>updateTier(i,"name",e.target.value)} className="w-full bg-surface border border-line rounded-lg px-2 py-1 text-sm font-bold" />
                <div className="grid grid-cols-2 gap-2 mt-2">
                  <input value={t.price} onChange={e=>updateTier(i,"price",e.target.value)} placeholder="29$" className="bg-surface border border-line rounded-lg px-2 py-1 text-xs" />
                  <input value={t.count} onChange={e=>updateTier(i,"count",parseInt(e.target.value)||0)} type="number" className="bg-surface border border-line rounded-lg px-2 py-1 text-xs" />
                </div>
                <div className="text-[11px] text-muted mt-1">{t.count} استراتيجية</div>
                <div className="text-[11px] mt-2 space-y-1">
                  {t.features.map((f,fi)=>(
                    <input key={fi} value={f} onChange={e=>{
                      const nf=[...t.features]; nf[fi]=e.target.value; updateTier(i,"features",nf)
                    }} className="w-full bg-surface border border-line rounded-lg px-2 py-1 text-[11px]" />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="mt-6">
          <h2 className="text-sm font-black">الـ 4 بوتات — WR و PF</h2>
          <div className="overflow-auto rounded-xl border border-line mt-3">
            <table className="w-full text-xs">
              <thead className="bg-surface text-muted"><tr><th className="p-2 text-right">الاسم</th><th className="p-2">التاير</th><th className="p-2">WR%</th><th className="p-2">PF</th><th className="p-2">الأيقونة</th></tr></thead>
              <tbody>
                {strategies.map((s,i)=>(
                  <tr key={s.id} className="border-t border-line">
                    <td className="p-1"><input value={s.nameAr} onChange={e=>updateStrat(i,"nameAr",e.target.value)} className="w-full bg-surface border border-line rounded px-1 py-1 text-xs" /></td>
                    <td className="p-1">
                      <select value={s.tier} onChange={e=>updateStrat(i,"tier",e.target.value)} className="bg-surface border border-line rounded px-1 py-1 text-xs">
                        <option value="free">free</option><option value="starter">starter</option><option value="pro">pro</option><option value="elite">elite</option>
                      </select>
                    </td>
                    <td className="p-1"><input type="number" value={s.winRate} onChange={e=>updateStrat(i,"winRate",parseFloat(e.target.value)||0)} className="w-16 bg-surface border border-line rounded px-1 py-1 text-xs" /></td>
                    <td className="p-1"><input type="number" step="0.1" value={s.pf} onChange={e=>updateStrat(i,"pf",parseFloat(e.target.value)||0)} className="w-16 bg-surface border border-line rounded px-1 py-1 text-xs" /></td>
                    <td className="p-1"><input value={s.icon} onChange={e=>updateStrat(i,"icon",e.target.value)} className="w-10 bg-surface border border-line rounded px-1 py-1 text-xs text-center" /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-3 flex gap-2">
            <button onClick={()=>{
              const code = `export const TIERS = ${JSON.stringify(tiers, null, 2)}\nexport const STRATEGIES = ${JSON.stringify(strategies, null, 2)}`
              navigator.clipboard.writeText(code); setSaved("تم النسخ — الصق في lib/strategies.ts")
              setTimeout(()=>setSaved(""), 3000)
            }} className="px-4 py-2 rounded-xl bg-corona text-void text-xs font-bold">نسخ الكود</button>
            {saved && <span className="text-xs text-corona py-2">{saved}</span>}
          </div>
          <div className="text-[11px] text-muted mt-2">ملاحظة: التعديل هنا للمعاينة فقط. للنشر انسخ الكود والصقه في <code>lib/strategies.ts</code> ثم <code>npm run build</code></div>
        </div>

        <div className="mt-6 grid md:grid-cols-2 gap-4">
          <div className="rounded-2xl border border-line bg-surface p-4">
            <h3 className="text-sm font-black">📱 تنبيهات تليجرام</h3>
            <p className="text-xs text-muted mt-1">كل صفقة دخول/خروج توصلك فورا</p>
            <div className="flex gap-2 mt-3">
              <button onClick={async()=>{
                const b=document.getElementById("tg-status") as HTMLElement
                if(b) b.textContent="جاري الاختبار..."
                try{
                  const r=await fetch((process.env.NEXT_PUBLIC_API_URL||"http://localhost:8000")+"/api/telegram/test",{method:"POST", headers: await authHeaders()})
                  const j=await r.json()
                  if(b) b.textContent=j.ok ? "✅ وصلت الرسالة لتليجرام!" : "❌ "+(j.msg||j.detail||"فشل — ضع التوكن في backend/.env")
                }catch(e:any){ const b2=document.getElementById("tg-status"); if(b2) b2.textContent="خطأ: "+String(e.message||e) }
              }} className="px-4 py-2 rounded-xl bg-[#229ED9] text-white text-xs font-bold">اختبر التليجرام</button>
              <button onClick={async()=>{
                const r=await fetch((process.env.NEXT_PUBLIC_API_URL||"http://localhost:8000")+"/api/telegram/status", { headers: await authHeaders() })
                const j=await r.json()
                const b=document.getElementById("tg-status")
                if(b) b.textContent=j.configured ? "✅ مربوط" : "⚠️ غير مربوط — ضع TELEGRAM_BOT_TOKEN و CHAT_ID في backend/.env"
              }} className="px-3 py-2 rounded-xl border border-line text-xs">الحالة</button>
            </div>
            <div id="tg-status" className="mt-2 text-[11px] text-muted">اضغط الحالة للتحقق</div>
            <div className="text-[11px] text-muted mt-2">من <a href="https://t.me/BotFather" target="_blank" className="text-[#229ED9] underline">@BotFather</a> اعمل بوت وخذ التوكن، ثم من <a href="https://t.me/userinfobot" target="_blank" className="text-[#229ED9] underline">@userinfobot</a> خذ الـ Chat ID</div>
          </div>
        </div>
      </div>
    </div>
  )
}
