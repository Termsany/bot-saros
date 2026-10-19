"use client"
import { useState } from "react"
import { Logo } from "@/components/Logo"

export default function LLMLab(){
  const [prompt, setPrompt] = useState("RSI divergence + volume spike for BTC 4h — lenient thresholds")
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<any>(null)
  const [error, setError] = useState("")

  async function generate(){
    setLoading(true); setError(""); setResult(null)
    try{
      const r = await fetch(`${process.env.NEXT_PUBLIC_API_URL||"http://localhost:8000"}/api/llm/generate?prompt=${encodeURIComponent(prompt)}`, { method:"POST" })
      const j = await r.json()
      if(!j.ok) setError(j.error || "failed")
      else setResult(j)
    }catch(e:any){ setError(String(e.message||e)) }
    setLoading(false)
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
      <div className="mx-auto max-w-[900px] p-5 lg:p-8 space-y-5">
        <div className="rounded border border-[#00D395]/20 bg-[#00D395]/[0.06] p-3 flex justify-between items-center">
          <div><div className="text-xs font-bold text-[#00D395]">الوضع التلقائي مفعّل</div><div className="font-mono text-[11px] text-[#8A9AB0]">كل فكرة WR ≥60% تضاف للـ Elite تلقائياً بدون تدخل</div></div>
          <a href="/api/llm/promoted" target="_blank" className="text-xs px-3 py-1.5 rounded border border-[#1c2632] bg-[#0a1018]">المُرقّاة</a>
        </div>
        <div>
          <h1 className="text-xl font-black">مختبر الاستراتيجيات</h1>
          <p className="font-mono text-xs text-[#647386] mt-1">اكتب وصف و الـ LLM يولد الكود + باك تست فوري عبر <b className="text-[#00D395]">Claude Sonnet 5</b> (CodeCraft)</p>
        </div>

        <div className="rounded border border-[#1c2632] bg-[#0c131c] p-5">
          <label className="font-mono text-[11px] tracking-[0.14em] text-[#68778a]">وصف الاستراتيجية</label>
          <textarea value={prompt} onChange={e=>setPrompt(e.target.value)} rows={3}
            className="w-full mt-2 bg-[#0a1018] border border-[#1d2936] rounded-xl px-3 py-3 text-sm focus:border-[#00D395]/40 outline-none"
            placeholder="مثال: اخترع استراتيجية تمزج Bollinger Squeeze + حجم للـ 15m" />
          <button onClick={generate} disabled={loading || !prompt.trim()}
            className={`w-full mt-3 py-3 rounded-xl text-sm font-black ${loading?"bg-[#1c2632] text-[#647386]":"bg-[#00D395] text-[#062016] hover:bg-[#00b87a]"}`}>
            {loading ? "جاري التحليل..." : "حوّل الفكرة لاستراتيجية"}
          </button>
        </div>

        {loading && (
          <div className="rounded border border-[#1c2632] bg-[#0c131c] p-8 text-center">
            <div className="w-10 h-10 mx-auto rounded-full border-2 border-[#1c2632] border-t-[#00D395] animate-spin"/>
            <div className="text-sm font-bold mt-3">الـ LLM يكتب الكود...</div>
            <div className="font-mono text-xs text-[#647386] mt-1">قد يستغرق 10-20 ثانية</div>
          </div>
        )}

        {error && <div className="rounded border border-[#FF3B5C]/30 bg-[#FF3B5C]/[0.06] p-4 text-xs text-[#FF3B5C] whitespace-pre-wrap">{error}</div>}

        {result && (
          <div className="rounded border border-[#1c2632] bg-[#0c131c] p-5 space-y-4">
            <div className="flex justify-between">
              <h3 className="text-sm font-bold">النتيجة — {result.name}</h3>
              <span className={`px-3 py-1 rounded-full text-xs font-black border ${result.backtest?.stats?.pnl >=0 ? "bg-[#00D395]/10 text-[#00D395] border-[#00D395]/30":"bg-[#FF3B5C]/10 text-[#FF3B5C] border-[#FF3B5C]/30"}`}>
                {result.backtest?.stats ? `${result.backtest.stats.pnl>=0?"مكسب":"خسارة"} ${result.backtest.stats.pnl.toFixed(2)} USDT` : "لا يوجد باك تست"}
              </span>
            </div>
            {result.backtest?.stats && (
              <div className="grid grid-cols-3 gap-2 text-center">
                <div className="rounded border border-[#1c2632] bg-[#0a1018] p-3"><div className="font-mono text-[10px] text-[#68778a]">الصفقات</div><div className="font-mono text-lg font-black">{result.backtest.stats.total}</div><div className="font-mono text-[11px] text-[#68778a]">{result.backtest.stats.wins}W / {result.backtest.stats.losses}L</div></div>
                <div className="rounded border border-[#1c2632] bg-[#0a1018] p-3"><div className="font-mono text-[10px] text-[#68778a]">Win Rate</div><div className={`font-mono text-lg font-black ${result.backtest.stats.win_rate>=45?"text-[#00D395]":"text-[#FFB800]"}`}>{result.backtest.stats.win_rate.toFixed(1)}%</div><div className="font-mono text-[11px] text-[#68778a]">PF {result.backtest.stats.profit_factor?.toFixed(2)}</div></div>
                <div className="rounded border border-[#1c2632] bg-[#0a1018] p-3"><div className="font-mono text-[10px] text-[#68778a]">PnL</div><div className={`font-mono text-lg font-black ${result.backtest.stats.pnl>=0?"text-[#00D395]":"text-[#FF3B5C]"}`}>{result.backtest.stats.pnl>=0?"+":""}{result.backtest.stats.pnl.toFixed(2)}</div><div className="font-mono text-[11px] text-[#68778a]">MaxDD {result.backtest.stats.max_dd?.toFixed(2)}</div></div>
              </div>
            )}
            <details className="rounded border border-[#1c2632] bg-[#0a1018] p-3"><summary className="text-xs font-bold cursor-pointer">عرض الكود</summary><pre className="mt-2 text-xs font-mono overflow-auto max-h-[320px] whitespace-pre-wrap">{result.code}</pre></details>

          </div>
        )}
      </div>
      <footer className="mx-auto max-w-[900px] px-5 lg:px-8 border-t border-[#1c2632] mt-6 py-6 flex justify-between font-mono text-[11px] text-[#5f6e81]">
        <span>LLM Lab — Bot Saros</span><span>CodeCraft · Claude Sonnet 5</span>
      </footer>
    </div>
  )
}
