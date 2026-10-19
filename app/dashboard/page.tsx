"use client"
import { useState } from "react"
import { StrategyPicker } from "@/components/StrategyPicker"
import { LiveTicker } from "@/components/LiveTicker"
import { PAIRS, NAMES } from "@/lib/pairs"

export default function Dashboard(){
  const [tier, setTier] = useState("elite")
  const [selected, setSelected] = useState<string[]>(["rsi_macd","ichimoku","smc","ai"])
  const [symbol, setSymbol] = useState("BTC/USDT")
  const [tf, setTf] = useState("1h")

  function toggle(id:string){
    setSelected(s=> s.includes(id) ? s.filter(x=>x!==id) : [...s, id])
  }

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 backdrop-blur bg-[#070B12]/80 border-b border-[#1E2A3A]">
        <div className="max-w-[1400px] mx-auto px-3 py-2 flex justify-between items-center gap-2 flex-wrap">
          <div className="flex items-center gap-2">
            <a href="/" className="w-7 h-7 rounded-lg bg-[#00D395] grid place-items-center font-black text-[#062016] text-xs">S</a>
            <span className="font-black text-sm">Bot Saros</span>
            <span className="text-[10px] px-1.5 py-0.5 rounded-full border border-[#1E2A3A]">FUTURES x5 Paper</span>
            <LiveTicker/>
          </div>
          <div className="flex items-center gap-1.5">
            <select value={tier} onChange={e=>setTier(e.target.value)} className="bg-[#0E141D] border border-[#1E2A3A] rounded-lg px-2 py-1 text-xs">
              <option value="free">Free</option><option value="starter">Starter</option><option value="pro">Pro</option><option value="elite">Elite</option>
            </select>
            <select value={symbol} onChange={e=>setSymbol(e.target.value)} className="bg-[#0E141D] border border-[#1E2A3A] rounded-lg px-2 py-1 text-xs">
              {PAIRS.map(p=><option key={p} value={p}>{NAMES[p]||p}</option>)}
            </select>
            <select value={tf} onChange={e=>setTf(e.target.value)} className="bg-[#0E141D] border border-[#1E2A3A] rounded-lg px-2 py-1 text-xs">
              <option value="15m">15m</option><option value="1h">1h</option><option value="4h">4h</option>
            </select>
            <a href="/backtest" className="px-2.5 py-1 rounded-lg bg-[#1E2A3A] text-xs">Backtest</a>
          </div>
        </div>
      </header>

      <div className="max-w-[1400px] mx-auto p-3 grid lg:grid-cols-[360px_1fr] gap-3">
        <div className="space-y-3">
          <div className="rounded-2xl border border-[#1E2A3A] bg-[#111827] p-3">
            <div className="text-xs font-bold mb-2">اختر الاستراتيجيات ({selected.length}) — باقة {tier}</div>
            <StrategyPicker selected={selected} onToggle={toggle} tier={tier}/>
            <button className="w-full mt-3 py-2 rounded-xl bg-[#00D395] text-[#062016] text-sm font-bold">شغّل البوت بهذه الاستراتيجيات</button>
            <div className="text-[11px] text-[#8A9AB0] mt-2">الأمر: <code className="bg-[#0E141D] px-1 py-0.5 rounded">--strategies {selected.join(",")}</code></div>
          </div>
          <div className="rounded-2xl border border-[#1E2A3A] bg-[#111827] p-3">
            <div className="text-xs font-bold">الصفقات المفتوحة</div>
            <div className="text-xs text-[#8A9AB0] text-center py-6">شغّل البوت: <code>python bot.py --strategies {selected.join(",")} --paper</code></div>
          </div>
        </div>

        <div className="space-y-3">
          <div className="rounded-2xl border border-[#1E2A3A] bg-[#111827] p-3">
            <div className="flex justify-between items-center">
              <span className="text-xs font-bold">الشارت — {NAMES[symbol]||symbol} {tf}</span>
              <span className="text-[11px] px-2 py-1 rounded-full bg-[#2a2506] text-[#FFB800]">WAIT</span>
            </div>
            <div className="h-[360px] grid place-items-center bg-[#0A0F1A] rounded-xl mt-2 border border-[#1E2A3A]">
              <span className="text-xs text-[#8A9AB0]">افتح index.html الأصلي للشارت الحي — أو شغّل البوت + localhost:8765</span>
            </div>
            <div className="grid grid-cols-4 gap-2 mt-2">
              {["السعر","السكور","RSI","الاتجاه"].map(k=>(
                <div key={k} className="rounded-xl bg-[#0E141D] border border-[#1E2A3A] p-2 text-center">
                  <div className="text-[10px] text-[#8A9AB0]">{k}</div><div className="text-sm font-bold">—</div>
                </div>
              ))}
            </div>
          </div>
          <div className="rounded-2xl border border-[#1E2A3A] bg-[#111827] p-3">
            <div className="text-xs font-bold">الـ 7 + 8 استراتيجية — كل سكور -1 إلى +1</div>
            <div className="text-[11px] text-[#8A9AB0] mt-2">اختر من اليسار وشوف التفصيل هنا بعد التشغيل</div>
          </div>
        </div>
      </div>
    </div>
  )
}
