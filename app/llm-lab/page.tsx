"use client"
import { useState } from "react"
import { BRAND } from "@/lib/brand"
import { Logo } from "@/components/Logo"
import { authHeaders } from "@/lib/supabase"

export default function LLMLab(){
  const [prompt, setPrompt] = useState("RSI divergence + volume spike for BTC 4h — lenient thresholds")
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<any>(null)
  const [error, setError] = useState("")

  async function generate(){
    setLoading(true); setError(""); setResult(null)
    try{
      const r = await fetch(`${process.env.NEXT_PUBLIC_API_URL||"http://localhost:8000"}/api/llm/generate?prompt=${encodeURIComponent(prompt)}`, { method:"POST", headers: await authHeaders() })
      const j = await r.json()
      if(!j.ok) setError(j.error || j.detail || "failed")
      else setResult(j)
    }catch(e:any){ setError(String(e.message||e)) }
    setLoading(false)
  }

  return (
    <div className="min-h-screen bg-void text-ink">
      <header className="flex h-16 items-center justify-between border-b border-line bg-surface/90 backdrop-blur px-5 lg:px-8 sticky top-0 z-30">
        <Logo />
        <div className="flex items-center gap-2">
          <a href="/dashboard" className="px-4 py-2 rounded bg-corona text-void text-xs font-bold">المنصة</a>
          <a href="/" className="text-xs text-muted hover:text-white">الرئيسية</a>
        </div>
      </header>
      <div className="mx-auto max-w-[900px] p-5 lg:p-8 space-y-5">
        <div className="rounded border border-corona/20 bg-corona/[0.06] p-3 flex justify-between items-center">
          <div><div className="text-xs font-bold text-corona">الوضع التلقائي مفعّل</div><div className="font-mono text-[11px] text-muted">كل فكرة WR ≥60% تضاف للـ Elite تلقائياً بدون تدخل</div></div>
          <a href="/api/llm/promoted" target="_blank" className="text-xs px-3 py-1.5 rounded border border-line bg-surface">المُرقّاة</a>
        </div>
        <div>
          <h1 className="text-xl font-black">مختبر الاستراتيجيات</h1>
          <p className="font-mono text-xs text-faint mt-1">اكتب وصف و الـ LLM يولد الكود + باك تست فوري عبر <b className="text-corona">Claude Sonnet 5</b> (CodeCraft)</p>
        </div>

        <div className="rounded border border-line bg-surface p-5">
          <label className="font-mono text-[11px] tracking-[0.14em] text-faint">وصف الاستراتيجية</label>
          <textarea value={prompt} onChange={e=>setPrompt(e.target.value)} rows={3}
            className="w-full mt-2 bg-surface border border-line rounded-xl px-3 py-3 text-sm focus:border-corona/40 outline-none"
            placeholder="مثال: اخترع استراتيجية تمزج Bollinger Squeeze + حجم للـ 15m" />
          <button onClick={generate} disabled={loading || !prompt.trim()}
            className={`w-full mt-3 py-3 rounded-xl text-sm font-black ${loading?"bg-line text-faint":"bg-corona text-void hover:bg-corona-deep"}`}>
            {loading ? "جاري التحليل..." : "حوّل الفكرة لاستراتيجية"}
          </button>
        </div>

        {loading && (
          <div className="rounded border border-line bg-surface p-8 text-center">
            <div className="w-10 h-10 mx-auto rounded-full border-2 border-line border-t-corona animate-spin"/>
            <div className="text-sm font-bold mt-3">الـ LLM يكتب الكود...</div>
            <div className="font-mono text-xs text-faint mt-1">قد يستغرق 10-20 ثانية</div>
          </div>
        )}

        {error && <div className="rounded border border-loss/30 bg-loss/[0.06] p-4 text-xs text-loss whitespace-pre-wrap">{error}</div>}

        {result && (
          <div className="rounded border border-line bg-surface p-5 space-y-4">
            <div className="flex justify-between">
              <h3 className="text-sm font-bold">النتيجة — {result.name}</h3>
              <span className={`px-3 py-1 rounded-full text-xs font-black border ${result.backtest?.stats?.pnl >=0 ? "bg-profit/10 text-profit border-profit/30":"bg-loss/10 text-loss border-loss/30"}`}>
                {result.backtest?.stats ? `${result.backtest.stats.pnl>=0?"مكسب":"خسارة"} ${result.backtest.stats.pnl.toFixed(2)} USDT` : "لا يوجد باك تست"}
              </span>
            </div>
            {result.backtest?.stats && (
              <div className="grid grid-cols-3 gap-2 text-center">
                <div className="rounded border border-line bg-surface p-3"><div className="font-mono text-[10px] text-faint">الصفقات</div><div className="font-mono text-lg font-black">{result.backtest.stats.total}</div><div className="font-mono text-[11px] text-faint">{result.backtest.stats.wins}W / {result.backtest.stats.losses}L</div></div>
                <div className="rounded border border-line bg-surface p-3"><div className="font-mono text-[10px] text-faint">Win Rate</div><div className={`font-mono text-lg font-black ${result.backtest.stats.win_rate>=45?"text-profit":"text-corona"}`}>{result.backtest.stats.win_rate.toFixed(1)}%</div><div className="font-mono text-[11px] text-faint">PF {result.backtest.stats.profit_factor?.toFixed(2)}</div></div>
                <div className="rounded border border-line bg-surface p-3"><div className="font-mono text-[10px] text-faint">PnL</div><div className={`font-mono text-lg font-black ${result.backtest.stats.pnl>=0?"text-profit":"text-loss"}`}>{result.backtest.stats.pnl>=0?"+":""}{result.backtest.stats.pnl.toFixed(2)}</div><div className="font-mono text-[11px] text-faint">MaxDD {result.backtest.stats.max_dd?.toFixed(2)}</div></div>
              </div>
            )}
            <details className="rounded border border-line bg-surface p-3"><summary className="text-xs font-bold cursor-pointer">عرض الكود</summary><pre className="mt-2 text-xs font-mono overflow-auto max-h-[320px] whitespace-pre-wrap">{result.code}</pre></details>

          </div>
        )}
      </div>
      <footer className="mx-auto max-w-[900px] px-5 lg:px-8 border-t border-line mt-6 py-6 flex justify-between font-mono text-[11px] text-faint">
        <span>LLM Lab — {BRAND.name}</span><span>CodeCraft · Claude Sonnet 5</span>
      </footer>
    </div>
  )
}
