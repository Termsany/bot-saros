"use client"
import { useState } from "react"
import { AppShell } from "@/components/AppShell"
import { Card, CardHeader, PageHeader, Pill, btn } from "@/components/ui"
import { authHeaders } from "@/lib/supabase"

const EXAMPLES = ["مومنتم + فلتر تذبذب: لونج أقوى 5 عملات لو التذبذب أقل من متوسطه", "شورت بعد الـ pump: عملة طلعت 30% في يوم بفوليوم 3 أضعاف", "Mean reversion على BTC فريم ساعة"]

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
  const st = result?.backtest?.stats

  return (
    <AppShell active="/llm-lab">
      <PageHeader title="مختبر AI" subtitle="اكتب فكرة · الذكاء الاصطناعي يكتب الاستراتيجية ويجربها فورًا"
        status={<Pill tone="signal">Paper فقط · مفيش أوامر حقيقية</Pill>}/>

      <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="min-w-0 space-y-5">
          <Card>
            <CardHeader title="فكرة الاستراتيجية"/>
            <textarea value={prompt} onChange={e=>setPrompt(e.target.value)} rows={4} aria-label="وصف الاستراتيجية"
              className="w-full rounded-xl border border-corona/50 bg-void px-4 py-3.5 text-[15px] leading-7 outline-none focus:border-corona"
              placeholder="مثال: اخترع استراتيجية تمزج Bollinger Squeeze + حجم للـ 15m"/>
            <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-[12px] text-faint">أمثلة:</span>
                {EXAMPLES.map(x => (
                  <button key={x} onClick={()=>setPrompt(x)} className="rounded-full bg-surface2 px-3 py-1 text-[12px] text-muted transition hover:text-ink">{x.split(":")[0]}</button>
                ))}
              </div>
              <button onClick={generate} disabled={loading || !prompt.trim()} className={btn.primary}>
                {loading ? "الـ AI بيكتب الكود…" : "حوّل الفكرة لاستراتيجية"}
              </button>
            </div>
          </Card>

          {loading && (
            <Card className="py-10 text-center">
              <div className="mx-auto h-10 w-10 animate-spin rounded-full border-2 border-line border-t-corona"/>
              <div className="mt-3 text-sm font-bold">الـ AI بيكتب الكود ويجربه…</div>
              <div className="mt-1 text-xs text-faint">ممكن ياخد من 10 لـ 20 ثانية</div>
            </Card>
          )}

          {error && <div className="whitespace-pre-wrap rounded-2xl border border-loss/30 bg-loss/[0.06] p-4 text-sm text-loss">{error}</div>}

          {result && (
            <Card>
              <CardHeader title={`النتيجة — ${result.name}`}
                action={st ? <Pill tone={st.pnl >= 0 ? "profit" : "loss"}>{st.pnl >= 0 ? "مكسب" : "خسارة"} <span className="font-mono" dir="ltr">{st.pnl.toFixed(2)} USDT</span></Pill> : <Pill>مفيش باك تست</Pill>}/>
              {st && (
                <div className="grid grid-cols-3 gap-3 text-center">
                  {[["الصفقات", String(st.total), `${st.wins} كسبانة / ${st.losses} خسرانة`, ""],
                    ["نسبة الكسب", `${st.win_rate.toFixed(1)}%`, `PF ${st.profit_factor?.toFixed(2)}`, st.win_rate >= 45 ? "text-profit" : "text-corona"],
                    ["الصافي", `${st.pnl >= 0 ? "+" : ""}${st.pnl.toFixed(2)}`, `أسوأ تراجع ${st.max_dd?.toFixed(2)}`, st.pnl >= 0 ? "text-profit" : "text-loss"]].map(([l, v, h, c]) => (
                    <div key={l} className="rounded-xl bg-surface2 p-3">
                      <div className="text-[12px] text-muted">{l}</div>
                      <div className={`font-mono text-xl font-bold tabular ${c}`} dir="ltr">{v}</div>
                      <div className="text-[11px] text-faint">{h}</div>
                    </div>
                  ))}
                </div>
              )}
              <details className="mt-4 rounded-xl border border-line bg-void p-3"><summary className="cursor-pointer text-xs font-bold">عرض الكود</summary><pre className="mt-2 max-h-[320px] overflow-auto whitespace-pre-wrap font-mono text-xs" dir="ltr">{result.code}</pre></details>
            </Card>
          )}
        </div>

        <Card>
          <CardHeader title="شروط القبول" sub="الاستراتيجية بتتضاف للـ Elite لوحدها لو عدّت الشرط ده"/>
          <div className="space-y-3">
            {[["نسبة الكسب 60% أو أكتر", "على الباك تست اللي بيتعمل للفكرة"], ["Profit factor ‏1.2 أو أكتر", "الكسب على الأقل 1.2 ضعف الخسارة"]].map(([l, h]) => (
              <div key={l} className="flex gap-2.5">
                <span className="mt-0.5 grid h-[22px] w-[22px] shrink-0 place-items-center rounded-md bg-corona/15 text-[11px] text-corona">◆</span>
                <div><div className="text-[14px] font-semibold">{l}</div><div className="text-[12px] text-muted">{h}</div></div>
              </div>
            ))}
          </div>
          <p className="mt-4 rounded-xl bg-surface2 p-3 text-[12px] leading-6 text-muted">جاي في تحديث الباك إند: 300 صفقة على الأقل، نتيجة على فترة ما اتختارتش عليها، حد لأسوأ تراجع، والربح مش من صفقات قليلة.</p>
          <a href="/api/llm/promoted" target="_blank" className={`${btn.secondary} mt-4 w-full`}>الاستراتيجيات اللي اتضافت</a>
        </Card>
      </div>
    </AppShell>
  )
}
