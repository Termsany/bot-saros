"use client"
import { useEffect, useState } from "react"
import { STRATEGIES, BACKTEST_DAYS, backtestSpanDays } from "@/lib/strategies"
import { getMyTier } from "@/lib/supabase"
import { PAIRS, NAMES } from "@/lib/pairs"
import { Logo } from "@/components/Logo"
import { apiBacktest, apiUserTier, chartUrl } from "@/lib/api"
import { runBacktestClient } from "@/lib/backtest-client"
import { Activity, Wifi, TrendingUp, Layers, Clock3, Zap, BarChart3 } from "lucide-react"

type BacktestData = {
  symbol: string
  timeframe: string
  stats: { total:number; wins:number; losses:number; win_rate:number; pnl:number; avg_win:number; avg_loss:number; profit_factor:number; max_dd:number }
  trades: { entry_ts:string; exit_ts:string; side:string; entry:number; exit:number; qty:number; pnl:number; reason:string }[]
}

const TIMEFRAMES = [
  { value:"15m", label:"15m" },
  { value:"1h", label:"1h" },
  { value:"4h", label:"4h" },
  { value:"1d", label:"1d" },
]
function fmt(n:number){ if(n>=1000) return n.toFixed(2); if(n>=1) return n.toFixed(2); if(n>=0.01) return n.toFixed(4); return n.toExponential(2) }
function toISODate(d: Date){ return d.toISOString().slice(0,10) }

export default function BacktestPage(){
  const [symbol, setSymbol] = useState("BTC/USDT")
  const [timeframe, setTimeframe] = useState("1h")
  const [from, setFrom] = useState(()=>{ const d=new Date(); d.setMonth(d.getMonth()-1); return toISODate(d) })
  const [to, setTo] = useState(()=> toISODate(new Date()))
  const [amount, setAmount] = useState(20)
  const [selected, setSelected] = useState<string[]>(["rsi_macd"])
  const [single, setSingle] = useState(true)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<BacktestData|null>(null)
  const [stdout, setStdout] = useState("")
  const [error, setError] = useState("")
  const [chartKey, setChartKey] = useState(0)
  // server chart name comes from the backend (unique per run); browser backtests have no server chart
  const [chartFile, setChartFile] = useState("")
  // plan's max range — the server enforces it too; here it just keeps the UI honest
  const [maxDays, setMaxDays] = useState<number|null>(BACKTEST_DAYS.free)
  useEffect(()=>{
    // backend first (knows admins); Supabase profile if the backend is asleep/unreachable
    apiUserTier().then(t=> t ?? getMyTier()).catch(()=>"free").then(t=>{
      const days = t in BACKTEST_DAYS ? BACKTEST_DAYS[t] : BACKTEST_DAYS.free
      setMaxDays(days)
      // default range is a month — shrink it to fit the plan
      if(days !== null) setFrom(f=>{
        if(backtestSpanDays(f, to) <= days) return f
        const d = new Date(Date.parse(to)); d.setUTCDate(d.getUTCDate() - (days - 1)); return toISODate(d)
      })
    })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function toggle(id:string){ if(single) setSelected([id]); else setSelected(s=> s.includes(id) ? s.filter(x=>x!==id) : [...s, id]) }
  async function run(){
    if(from > to){ setError("التاريخ معكوس — من يجب أن يكون قبل إلى"); return }
    if(maxDays !== null && backtestSpanDays(from, to) > maxDays){
      setError(`المدة ${backtestSpanDays(from, to)} يوم — باقتك تسمح بـ ${maxDays} يوم كحد أقصى. رقّي باقتك لباك تست أطول`)
      return
    }
    setLoading(true); setError(""); setResult(null); setChartFile("")
    try{
      // Try browser-direct first (Bybit/OKX — no Render, no ban)
      const client = await runBacktestClient({ symbol, timeframe, from, to, strategies: selected, amount, leverage: 5 })
      if(client.ok && client.data){
        setResult(client.data as unknown as BacktestData)
        setStdout(`Client backtest — ${client.data.candles} candles from Bybit/OKX`)
        setChartKey(k=>k+1)
        setLoading(false)
        return
      }
      // Fallback: backend (Render) for chart image
      const j = await apiBacktest({ symbol, timeframe, from, to, strategies: selected, amount, leverage: 5 })
      setStdout((j.stdout||"") + (j.stderr ? "\n"+j.stderr : "") + (client.error ? "\nClient: "+client.error : ""))
      if(j.data){ setResult(j.data as BacktestData); if(typeof j.chart === "string") setChartFile(j.chart) }
      else if(client.error) setError(client.error)
      else if(!j.ok) setError(j.error || (typeof j.detail === "string" ? j.detail : "") || j.stdout || "فشل")
      setChartKey(k=>k+1)
    }catch(e:any){ setError(String(e?.message||e)) }
    finally{ setLoading(false) }
  }
  const selStrategies = STRATEGIES.filter(s=> selected.includes(s.id))

  return (
    <div className="min-h-screen bg-[#070B12] text-[#E8EEF5]">
      <header className="flex h-16 items-center justify-between border-b border-[#1c2632] bg-[#0a1018]/90 backdrop-blur px-5 lg:px-8 sticky top-0 z-30">
        <Logo />
        <div className="flex items-center gap-3">
          <span className="hidden md:flex items-center gap-2 text-[11px] text-[#00D395] font-mono"><Wifi size={13}/> BINANCE SPOT <i className="h-1.5 w-1.5 rounded-full bg-[#00D395] animate-pulse"/></span>
          <a href="/dashboard" className="px-4 py-2 rounded bg-[#00D395] text-[#062016] text-xs font-bold hover:bg-[#00b87a]">المنصة</a>
          <a href="/" className="hidden md:block text-[11px] text-[#778597] hover:text-white">الرئيسية</a>
        </div>
      </header>

      <div className="mx-auto max-w-[1600px] p-4 lg:p-6 space-y-5">
        {/* Step 1 */}
        <section className="rounded border border-[#1c2632] bg-[#0c131c] p-5">
          <div className="flex items-center gap-2 mb-1"><span className="h-6 w-6 grid place-items-center rounded bg-[#00D395]/10 text-[#00D395] text-xs font-black">1</span><h2 className="text-xs font-semibold tracking-[0.14em]">اختر العملة والفريم والمدة</h2></div>
          <p className="font-mono text-[11px] text-[#647386]">العملة + الفريم + التقويم — كل شيء هنا قبل اختيار الاستراتيجية</p>
          <div className="grid md:grid-cols-4 gap-3 mt-4">
            <div><label className="font-mono text-[10px] tracking-[0.14em] text-[#68778a]">العملة</label>
              <select value={symbol} onChange={e=>setSymbol(e.target.value)} className="w-full mt-1 bg-[#0a1018] border border-[#1d2936] rounded px-3 py-2.5 text-xs focus:border-[#00D395]/40 outline-none">
                {PAIRS.map(p=> <option key={p} value={p}>{NAMES[p]||p}</option>)}
              </select></div>
            <div><label className="font-mono text-[10px] tracking-[0.14em] text-[#68778a]">الفريم</label>
              <select value={timeframe} onChange={e=>setTimeframe(e.target.value)} className="w-full mt-1 bg-[#0a1018] border border-[#1d2936] rounded px-3 py-2.5 text-xs focus:border-[#00D395]/40 outline-none">
                {TIMEFRAMES.map(t=> <option key={t.value} value={t.value}>{t.label} — {t.value}</option>)}
              </select></div>
            <div><label className="font-mono text-[10px] tracking-[0.14em] text-[#68778a]">من</label>
              <input type="date" value={from} onChange={e=>setFrom(e.target.value)} className="w-full mt-1 bg-[#0a1018] border border-[#1d2936] rounded px-3 py-2.5 text-xs" /></div>
            <div><label className="font-mono text-[10px] tracking-[0.14em] text-[#68778a]">إلى</label>
              <input type="date" value={to} onChange={e=>setTo(e.target.value)} className="w-full mt-1 bg-[#0a1018] border border-[#1d2936] rounded px-3 py-2.5 text-xs" /></div>
          </div>
          <div className="mt-3 flex items-center gap-2 font-mono text-[11px] text-[#5f6e81]"><BarChart3 size={12}/><span>{NAMES[symbol]||symbol}</span><span className="text-[#1c2632]">·</span><span className="text-[#00D395]">{timeframe}</span><span className="text-[#1c2632]">·</span><span>{from} → {to}</span></div>
        </section>

        {/* Step 2 */}
        <section className="rounded border border-[#1c2632] bg-[#0c131c] p-5">
          <div className="flex justify-between items-start gap-4">
            <div className="flex items-center gap-2"><span className="h-6 w-6 grid place-items-center rounded bg-[#00D395]/10 text-[#00D395] text-xs font-black">2</span><div><h2 className="text-xs font-semibold tracking-[0.14em]">اختر الاستراتيجية</h2><p className="font-mono text-[11px] text-[#647386]">واحدة لوحدها أو مجموعة — كل واحدة نسبة ربح منفصلة</p></div></div>
            <div className="flex gap-1.5 shrink-0">
              <button onClick={()=>{ setSingle(true); setSelected(s=> s.slice(0,1)) }} className={`px-3 py-1.5 rounded text-xs font-bold ${single?"bg-[#00D395] text-[#062016]":"bg-[#1d2936] text-[#8A9AB0]"}`}>واحدة</button>
              <button onClick={()=>setSingle(false)} className={`px-3 py-1.5 rounded text-xs font-bold ${!single?"bg-[#00D395] text-[#062016]":"bg-[#1d2936] text-[#8A9AB0]"}`}>مجموعة</button>
            </div>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-2 mt-4 max-h-[380px] overflow-auto pr-1">
            {STRATEGIES.map(s=>{
              const active = selected.includes(s.id)
              return (
                <button key={s.id} onClick={()=>toggle(s.id)}
                  className={`text-right p-3 rounded border text-xs text-left transition ${active ? "border-[#00D395]/40 bg-[#00D395]/[0.06]" : "border-[#1d2936] bg-[#0a1018] hover:border-[#2a3a56]"}`}>
                  <div className="flex justify-between items-start"><span className="text-base">{s.icon}</span>{active && <span className="h-2 w-2 rounded-full bg-[#00D395] mt-1"/>}</div>
                  <div className="font-bold mt-1.5 leading-tight">{s.nameAr}</div>
                  <div className="font-mono text-[10px] text-[#647386] leading-tight">{s.desc}</div>
                  <div className="mt-2 font-mono text-[10px] flex gap-2"><span className={s.winRate>=45?"text-[#00D395]":s.winRate>=35?"text-[#FFB800]":"text-[#FF3B5C]"}>WR {s.winRate}%</span><span className="text-[#5f6e81]">PF {s.pf}</span></div>
                </button>
              )
            })}
          </div>
          {/* Amount — وهمي */}
          <div className="mt-4 rounded border border-[#1c2632] bg-[#0a1018] p-4">
            <div className="flex justify-between items-center">
              <div><div className="text-xs font-bold">المبلغ الوهمي للصفقة</div><div className="font-mono text-[11px] text-[#647386]">اختر كأنك داخل بكام — وهمي 100% بدون فلوس حقيقية</div></div>
              <span className="font-mono text-lg font-black text-[#00D395]">{amount}$</span>
            </div>
            <input type="range" min={10} max={200} step={10} value={amount} onChange={e=>setAmount(parseInt(e.target.value))} className="w-full mt-3 accent-[#00D395]" />
            <div className="flex justify-between font-mono text-[10px] text-[#5f6e81] mt-1"><span>10$</span><span>100$</span><span>200$</span></div>
            <div className="mt-2 font-mono text-[11px] text-[#5f6e81]">هامش وهمي <b className="text-white">{amount}$</b> × رافعة x5 = <b className="text-[#00D395]">{amount*5}$</b> حجم الصفقة</div>
          </div>

          <button onClick={run} disabled={loading || selected.length===0}
            className={`w-full mt-4 py-3 rounded text-sm font-black flex items-center justify-center gap-2 ${loading ? "bg-[#1c2632] text-[#647386]" : "bg-[#00D395] text-[#062016] hover:bg-[#00b87a]"}`}>
            <Zap size={14}/>{loading ? "جاري التحليل..." : `شغّل الـ Backtest — ${selected.length} استراتيجية · ${amount}$ · ${symbol} ${timeframe} ${from} → ${to}`}
          </button>
          <div className="mt-2 font-mono text-[10px] text-[#5f6e81]">python backtest.py --symbol {symbol} --timeframe {timeframe} --from {from} --to {to} --strategies {selected.join(",")} --leverage 5</div>
        </section>

        {loading && (
          <section className="rounded border border-[#1c2632] bg-[#0c131c] p-8 text-center">
            <div className="w-10 h-10 mx-auto rounded-full border-2 border-[#1c2632] border-t-[#00D395] animate-spin"/>
            <div className="text-sm font-bold mt-3">جاري جلب الشموع وتشغيل الـ Backtest...</div>
            <div className="font-mono text-xs text-[#647386] mt-1">{symbol} — {timeframe} — {from} → {to} — {selected.join(", ")}</div>
            <div className="font-mono text-[11px] text-[#5f6e81] mt-2">قد يستغرق 10-30 ثانية</div>
          </section>
        )}

        {result && !loading && (
          <section className="rounded border border-[#1c2632] bg-[#0c131c] p-5">
            <div className="flex flex-wrap justify-between gap-3">
              <div><h3 className="text-sm font-bold">التقرير — {result.symbol} {result.timeframe} — {from} → {to}</h3>
                <p className="font-mono text-xs text-[#647386] mt-1">{selected.length} استراتيجية: {selStrategies.map(s=> s.nameAr).join(" + ")} — {timeframe} — {from} إلى {to}</p></div>
              <span className={`px-4 py-1.5 rounded-full text-xs font-black border ${result.stats.pnl>=0 ? "bg-[#00D395]/10 text-[#00D395] border-[#00D395]/30" : "bg-[#FF3B5C]/10 text-[#FF3B5C] border-[#FF3B5C]/30"}`}>
                المحصلة: {result.stats.pnl>=0 ? "مكسب" : "خسارة"} {result.stats.pnl>=0?"+":""}{result.stats.pnl.toFixed(2)} USDT {result.stats.pnl>=0?"🟢":"🔴"}
              </span>
            </div>

            <div className="mt-4">
              <h4 className="text-xs font-semibold tracking-[0.14em] mb-2">طريقة الاستراتيجية</h4>
              <div className="grid md:grid-cols-2 gap-2">
                {selStrategies.map(s=>(
                  <div key={s.id} className="rounded border border-[#1c2632] bg-[#0a1018] p-3">
                    <div className="text-xs font-bold">{s.icon} {s.nameAr} — {s.name}</div>
                    <div className="font-mono text-[11px] text-[#8A9AB0] mt-1.5 leading-relaxed">{s.method}</div>
                    <div className="font-mono text-[11px] mt-2 flex gap-2"><span className={s.winRate>=45?"text-[#00D395]":s.winRate>=35?"text-[#FFB800]":"text-[#FF3B5C]"}>WR {s.winRate}%</span><span className="text-[#5f6e81]">PF {s.pf}</span></div>
                  </div>
                ))}
              </div>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mt-4">
              <div className="rounded border border-[#1c2632] bg-[#0a1018] p-4 text-center">
                <div className="font-mono text-[10px] tracking-[0.14em] text-[#68778a]">الصفقات</div><div className="text-xl font-black font-mono">{result.stats.total}</div>
                <div className="font-mono text-[11px] text-[#68778a]">{result.stats.wins} رابحة · {result.stats.losses} خاسرة</div>
              </div>
              <div className="rounded border border-[#1c2632] bg-[#0a1018] p-4 text-center">
                <div className="font-mono text-[10px] tracking-[0.14em] text-[#68778a]">نسبة الربح</div><div className={`text-xl font-black font-mono ${result.stats.win_rate>=45?"text-[#00D395]":result.stats.win_rate>=35?"text-[#FFB800]":"text-[#FF3B5C]"}`}>{result.stats.win_rate.toFixed(1)}%</div>
                <div className="font-mono text-[11px] text-[#68778a]">PF {result.stats.profit_factor.toFixed(2)}</div>
              </div>
              <div className="rounded border border-[#1c2632] bg-[#0a1018] p-4 text-center">
                <div className="font-mono text-[10px] tracking-[0.14em] text-[#68778a]">المكسب / الخسارة</div>
                <div className="font-mono text-xs font-bold text-[#00D395]">مكسب +{(result.stats.avg_win||0).toFixed(2)}</div>
                <div className="font-mono text-xs font-bold text-[#FF3B5C]">خسارة {(result.stats.avg_loss||0).toFixed(2)}</div>
              </div>
              <div className={`rounded border p-4 text-center ${result.stats.pnl>=0 ? "bg-[#00D395]/[0.06] border-[#00D395]/30" : "bg-[#FF3B5C]/[0.06] border-[#FF3B5C]/30"}`}>
                <div className="font-mono text-[10px] tracking-[0.14em] text-[#68778a]">المحصلة النهائية</div>
                <div className={`text-xl font-black font-mono ${result.stats.pnl>=0?"text-[#00D395]":"text-[#FF3B5C]"}`}>{result.stats.pnl>=0?"+":""}{result.stats.pnl.toFixed(2)} USDT</div>
                <div className="font-mono text-[11px] text-[#68778a]">{result.stats.pnl>=0 ? "مكسب" : "خسارة"} · Max DD {result.stats.max_dd.toFixed(2)}</div>
              </div>
            </div>

            {chartFile && (
              <div className="mt-5">
                <h4 className="text-xs font-semibold tracking-[0.14em] mb-2 flex items-center gap-2"><TrendingUp size={12} className="text-[#00D395]"/> الشارت — السعر + الصفقات + Equity</h4>
                <img key={chartKey} src={`${chartUrl(chartFile)}&k=${chartKey}`} alt="chart" className="w-full rounded border border-[#1c2632]" />
              </div>
            )}

            <div className="mt-5">
              <h4 className="text-xs font-semibold tracking-[0.14em] mb-2">آخر الصفقات</h4>
              <div className="overflow-auto rounded border border-[#1c2632]">
                <table className="w-full text-xs font-mono">
                  <thead className="bg-[#0a1018] text-[#68778a]"><tr><th className="p-2.5 text-right font-normal tracking-[0.1em]">دخول</th><th className="p-2.5 text-right font-normal tracking-[0.1em]">خروج</th><th className="p-2.5 font-normal">اتجاه</th><th className="p-2.5 font-normal">دخول</th><th className="p-2.5 font-normal">خروج</th><th className="p-2.5 font-normal">النتيجة</th><th className="p-2.5 font-normal">السبب</th></tr></thead>
                  <tbody>
                    {result.trades.slice(-12).reverse().map((t,i)=>(
                      <tr key={i} className="border-t border-[#1c2632]">
                        <td className="p-2.5 text-[11px]">{String(t.entry_ts).slice(5,16).replace("T"," ")}</td>
                        <td className="p-2.5 text-[11px]">{String(t.exit_ts).slice(5,16).replace("T"," ")}</td>
                        <td className="p-2.5"><span className={`px-2 py-0.5 rounded text-[10px] font-bold border ${t.side==="long"?"bg-[#00D395]/10 text-[#00D395] border-[#00D395]/30":"bg-[#FF3B5C]/10 text-[#FF3B5C] border-[#FF3B5C]/30"}`}>{t.side==="long"?"LONG":"SHORT"}</span></td>
                        <td className="p-2.5">{fmt(t.entry)}</td><td className="p-2.5">{fmt(t.exit)}</td>
                        <td className={`p-2.5 font-bold ${t.pnl>=0?"text-[#00D395]":"text-[#FF3B5C]"}`}>{t.pnl>=0?"+":""}{t.pnl.toFixed(2)}</td>
                        <td className="p-2.5 text-[11px] text-[#8A9AB0]">{t.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </section>
        )}

        {error && !loading && (
          <div className="rounded border border-[#FF3B5C]/30 bg-[#FF3B5C]/[0.06] p-4 text-xs text-[#FF3B5C] whitespace-pre-wrap">{error}</div>
        )}
        {!result && !loading && stdout && (
          <div className="rounded border border-[#1c2632] bg-[#0a1018] p-4 font-mono text-[11px] whitespace-pre-wrap text-[#8A9AB0]">{stdout.slice(-4000)}</div>
        )}
      </div>

      <footer className="mx-auto max-w-[1600px] px-5 lg:px-8 border-t border-[#1c2632] mt-6 py-6 flex flex-wrap justify-between gap-3 font-mono text-[11px] text-[#5f6e81]">
        <span>Bot Saros © 2026 — 15 استراتيجية + Backtest + Futures LONG/SHORT</span>
        <span>ENGINE STATUS <b className="text-[#00D395]">● OPERATIONAL</b> · bot-saros.vercel.app</span>
      </footer>
    </div>
  )
}
