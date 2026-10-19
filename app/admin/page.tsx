"use client"
import { useState } from "react"
import { STRATEGIES, TIERS } from "@/lib/strategies"

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
    <div className="min-h-screen bg-[#070B12] text-[#E6EEF8] p-4" dir="rtl">
      <div className="max-w-[1200px] mx-auto">
        <div className="flex justify-between items-center">
          <h1 className="text-lg font-black">لوحة تحكم الأدمن — Bot Saros</h1>
          <a href="/" className="text-xs px-3 py-1.5 rounded-xl border border-[#1E2A3A]">الرئيسية</a>
        </div>
        <p className="text-xs text-[#8A9AB0] mt-1">عدّل التسعير والاستراتيجيات بدون كود — التغييرات هنا للمعاينة، احفظها في lib/strategies.ts للنشر</p>

        <div className="mt-6">
          <h2 className="text-sm font-black">الباقات — التسعير</h2>
          <div className="grid md:grid-cols-4 gap-3 mt-3">
            {tiers.map((t,i)=>(
              <div key={t.id} className="rounded-2xl border border-[#1E2A3A] bg-[#111827] p-3">
                <input value={t.name} onChange={e=>updateTier(i,"name",e.target.value)} className="w-full bg-[#0E141D] border border-[#1E2A3A] rounded-lg px-2 py-1 text-sm font-bold" />
                <div className="grid grid-cols-2 gap-2 mt-2">
                  <input value={t.price} onChange={e=>updateTier(i,"price",e.target.value)} placeholder="29$" className="bg-[#0E141D] border border-[#1E2A3A] rounded-lg px-2 py-1 text-xs" />
                  <input value={t.count} onChange={e=>updateTier(i,"count",parseInt(e.target.value)||0)} type="number" className="bg-[#0E141D] border border-[#1E2A3A] rounded-lg px-2 py-1 text-xs" />
                </div>
                <div className="text-[11px] text-[#8A9AB0] mt-1">{t.count} استراتيجية</div>
                <div className="text-[11px] mt-2 space-y-1">
                  {t.features.map((f,fi)=>(
                    <input key={fi} value={f} onChange={e=>{
                      const nf=[...t.features]; nf[fi]=e.target.value; updateTier(i,"features",nf)
                    }} className="w-full bg-[#0E141D] border border-[#1E2A3A] rounded-lg px-2 py-1 text-[11px]" />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="mt-6">
          <h2 className="text-sm font-black">الـ 15 استراتيجية — WR و PF</h2>
          <div className="overflow-auto rounded-xl border border-[#1E2A3A] mt-3">
            <table className="w-full text-xs">
              <thead className="bg-[#0E141D] text-[#8A9AB0]"><tr><th className="p-2 text-right">الاسم</th><th className="p-2">التاير</th><th className="p-2">WR%</th><th className="p-2">PF</th><th className="p-2">الأيقونة</th></tr></thead>
              <tbody>
                {strategies.map((s,i)=>(
                  <tr key={s.id} className="border-t border-[#1E2A3A]">
                    <td className="p-1"><input value={s.nameAr} onChange={e=>updateStrat(i,"nameAr",e.target.value)} className="w-full bg-[#0E141D] border border-[#1E2A3A] rounded px-1 py-1 text-xs" /></td>
                    <td className="p-1">
                      <select value={s.tier} onChange={e=>updateStrat(i,"tier",e.target.value)} className="bg-[#0E141D] border border-[#1E2A3A] rounded px-1 py-1 text-xs">
                        <option value="free">free</option><option value="starter">starter</option><option value="pro">pro</option><option value="elite">elite</option>
                      </select>
                    </td>
                    <td className="p-1"><input type="number" value={s.winRate} onChange={e=>updateStrat(i,"winRate",parseFloat(e.target.value)||0)} className="w-16 bg-[#0E141D] border border-[#1E2A3A] rounded px-1 py-1 text-xs" /></td>
                    <td className="p-1"><input type="number" step="0.1" value={s.pf} onChange={e=>updateStrat(i,"pf",parseFloat(e.target.value)||0)} className="w-16 bg-[#0E141D] border border-[#1E2A3A] rounded px-1 py-1 text-xs" /></td>
                    <td className="p-1"><input value={s.icon} onChange={e=>updateStrat(i,"icon",e.target.value)} className="w-10 bg-[#0E141D] border border-[#1E2A3A] rounded px-1 py-1 text-xs text-center" /></td>
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
            }} className="px-4 py-2 rounded-xl bg-[#00D395] text-[#062016] text-xs font-bold">نسخ الكود</button>
            {saved && <span className="text-xs text-[#00D395] py-2">{saved}</span>}
          </div>
          <div className="text-[11px] text-[#8A9AB0] mt-2">ملاحظة: التعديل هنا للمعاينة فقط. للنشر انسخ الكود والصقه في <code>lib/strategies.ts</code> ثم <code>npm run build</code></div>
        </div>

        <div className="mt-6 rounded-2xl border border-[#1E2A3A] bg-[#111827] p-3">
          <h3 className="text-xs font-bold">المُحسّن الأسبوعي</h3>
          <div className="text-[11px] text-[#8A9AB0] mt-1">شغّل <code className="bg-[#0E141D] px-1 py-0.5 rounded">python auto_optimizer.py --symbol BTC/USDT --timeframe 4h --limit 200</code> كل جمعة لتحديث <code>ai_weights.json</code></div>
          <div className="text-[11px] text-[#8A9AB0] mt-1">المقارنة الكاملة: <code className="bg-[#0E141D] px-1 py-0.5 rounded">python backtest.py --compare --timeframe 4h --limit 300</code></div>
        </div>
      </div>
    </div>
  )
}
