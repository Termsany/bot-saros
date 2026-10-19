"use client"
import { useState } from "react"
import { STRATEGIES } from "@/lib/strategies"
import { PAIRS, NAMES } from "@/lib/pairs"
import { LiveTicker } from "@/components/LiveTicker"
import { apiBacktest, chartUrl } from "@/lib/api"

type BacktestData = {
  symbol: string
  timeframe: string
  stats: { total:number; wins:number; losses:number; win_rate:number; pnl:number; avg_win:number; avg_loss:number; profit_factor:number; max_dd:number }
  trades: { entry_ts:string; exit_ts:string; side:string; entry:number; exit:number; qty:number; pnl:number; reason:string }[]
}

const TIMEFRAMES = [
  { value:"15m", label:"15 دقيقة" },
  { value:"1h", label:"1 ساعة" },
  { value:"4h", label:"4 ساعات" },
  { value:"1d", label:"يوم" },
]

function fmt(n:number){
  if(n>=1000) return n.toFixed(2)
  if(n>=1) return n.toFixed(2)
  if(n>=0.01) return n.toFixed(4)
  return n.toExponential(2)
}

function toISODate(d: Date){ return d.toISOString().slice(0,10) }

export default function BacktestPage(){
  const [symbol, setSymbol] = useState("BTC/USDT")
  const [timeframe, setTimeframe] = useState("1h")
  const [from, setFrom] = useState(()=>{ const d=new Date(); d.setMonth(d.getMonth()-1); return toISODate(d) })
  const [to, setTo] = useState(()=> toISODate(new Date()))
  const [selected, setSelected] = useState<string[]>(["rsi_macd"])
  const [single, setSingle] = useState(true)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<BacktestData|null>(null)
  const [stdout, setStdout] = useState("")
  const [error, setError] = useState("")
  const [chartKey, setChartKey] = useState(0)

  function toggle(id:string){
    if(single) setSelected([id])
    else setSelected(s=> s.includes(id) ? s.filter(x=>x!==id) : [...s, id])
  }

  async function run(){
    setLoading(true); setError(""); setResult(null)
    try{
      const j = await apiBacktest({ symbol, timeframe, from, to, strategies: selected, amount: 20, leverage: 5 })
      setStdout((j.stdout||"") + (j.stderr ? "\n"+j.stderr : ""))
      if(j.data) setResult(j.data as BacktestData)
      else if(!j.ok) setError(j.error || j.stdout || "فشل")
      setChartKey(k=>k+1)
    }catch(e:any){ setError(String(e?.message||e)) }
    finally{ setLoading(false) }
  }

  const selStrategies = STRATEGIES.filter(s=> selected.includes(s.id))
  const chartFile = result ? `backtest_${result.symbol.replace("/","")}_${result.timeframe}.png` : ""

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 backdrop-blur bg-[#070B12]/80 border-b border-[#1E2A3A]">
        <div className="max-w-[1200px] mx-auto px-3 py-2 flex justify-between items-center">
          <div className="flex items-center gap-2">
            <a href="/" className="w-7 h-7 rounded-lg bg-[#00D395] grid place-items-center font-black text-[#062016] text-xs">S</a>
            <span className="font-black text-sm">Backtest — Bot Saros</span>
          </div>
          <LiveTicker/>
        </div>
      </header>

      <div className="max-w-[1200px] mx-auto p-4">
        <div className="rounded-2xl border border-[#1E2A3A] bg-[#111827] p-4">
          <div className="text-sm font-black">1 — اختر العملة والفريم والمدة</div>
          <div className="text-xs text-[#8A9AB0]">اختر العملة من القائمة، والفريم، وحدد المدة من التقويم — ثم اختر الاستراتيجية</div>
          <div className="grid md:grid-cols-4 gap-3 mt-3">
            <div>
              <label className="text-[11px] text-[#8A9AB0]">العملة</label>
              <select value={symbol} onChange={e=>setSymbol(e.target.value)} className="w-full mt-1 bg-[#0E141D] border border-[#1E2A3A] rounded-xl px-2 py-2 text-xs">
                {PAIRS.map(p=> <option key={p} value={p}>{NAMES[p]||p}</option>)}
              </select>
            </div>
            <div>
              <label className="text-[11px] text-[#8A9AB0]">الفريم</label>
              <select value={timeframe} onChange={e=>setTimeframe(e.target.value)} className="w-full mt-1 bg-[#0E141D] border border-[#1E2A3A] rounded-xl px-2 py-2 text-xs">
                {TIMEFRAMES.map(t=> <option key={t.value} value={t.value}>{t.label} — {t.value}</option>)}
              </select>
            </div>
            <div>
              <label className="text-[11px] text-[#8A9AB0]">من</label>
              <input type="date" value={from} onChange={e=>setFrom(e.target.value)} className="w-full mt-1 bg-[#0E141D] border border-[#1E2A3A] rounded-xl px-2 py-2 text-xs" />
            </div>
            <div>
              <label className="text-[11px] text-[#8A9AB0]">إلى</label>
              <input type="date" value={to} onChange={e=>setTo(e.target.value)} className="w-full mt-1 bg-[#0E141D] border border-[#1E2A3A] rounded-xl px-2 py-2 text-xs" />
            </div>
          </div>
          <div className="text-[11px] text-[#8A9AB0] mt-2">المدى: <b className="text-white">{from}</b> → <b className="text-white">{to}</b> — الفريم <b className="text-[#00D395]">{timeframe}</b> — العملة <b className="text-white">{NAMES[symbol]||symbol}</b></div>
        </div>

        <div className="rounded-2xl border border-[#1E2A3A] bg-[#111827] p-4 mt-4">
          <div className="flex justify-between items-center">
            <div>
              <div className="text-sm font-black">2 — اختر الاستراتيجية</div>
              <div className="text-xs text-[#8A9AB0]">واحدة لوحدها أو مجموعة — كل واحدة ليها نسبة ربح منفصلة</div>
            </div>
            <div className="flex gap-1.5">
              <button onClick={()=>{ setSingle(true); setSelected(s=> s.slice(0,1)) }} className={`px-3 py-1.5 rounded-xl text-xs font-bold ${single?"bg-[#00D395] text-[#062016]":"bg-[#1E2A3A] text-white"}`}>واحدة</button>
              <button onClick={()=>setSingle(false)} className={`px-3 py-1.5 rounded-xl text-xs font-bold ${!single?"bg-[#00D395] text-[#062016]":"bg-[#1E2A3A] text-white"}`}>مجموعة</button>
            </div>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-2 mt-3 max-h-[360px] overflow-auto pr-1">
            {STRATEGIES.map(s=>{
              const active = selected.includes(s.id)
              return (
                <button key={s.id} onClick={()=>toggle(s.id)}
                  className={`text-right p-2.5 rounded-xl border text-xs ${active ? "border-[#00D395] bg-[#0A2E1A]" : "border-[#1E2A3A] bg-[#0E141D] hover:border-[#2a3a56]"}`}>
                  <div className="flex justify-between"><span>{s.icon}</span>{active && <span className="text-[#00D395]">✓</span>}</div>
                  <div className="font-bold mt-1">{s.nameAr}</div>
                  <div className="text-[10px] text-[#8A9AB0]">{s.desc}</div>
                  <div className="text-[10px] mt-1"><span className={s.winRate>=45?"text-[#00D395]":s.winRate>=35?"text-[#FFB800]":"text-[#FF3B5C]"}>WR {s.winRate}%</span> <span className="text-[#8A9AB0]">PF {s.pf}</span></div>
                </button>
              )
            })}
          </div>
          <div className="mt-3 flex gap-2">
            <button onClick={run} disabled={loading || selected.length===0}
              className={`flex-1 py-2.5 rounded-xl text-sm font-black ${loading ? "bg-[#1E2A3A] text-[#8A9AB0]" : "bg-[#00D395] text-[#062016] hover:bg-[#00b87a]"}`}>
              {loading ? "جاري التحليل..." : `شغّل الـ Backtest — ${selected.length} استراتيجية · ${symbol} ${timeframe} ${from} → ${to}`}
            </button>
          </div>
          <div className="text-[11px] text-[#8A9AB0] mt-2 font-mono">python backtest.py --symbol {symbol} --timeframe {timeframe} --from {from} --to {to} --strategies {selected.join(",")} --leverage 5</div>
        </div>

        {loading && (
          <div className="rounded-2xl border border-[#1E2A3A] bg-[#111827] p-6 mt-4 text-center">
            <div className="w-10 h-10 mx-auto rounded-full border-2 border-[#1E2A3A] border-t-[#00D395] animate-spin"/>
            <div className="text-sm font-bold mt-3">جاري جلب الشموع وتشغيل الـ Backtest...</div>
            <div className="text-xs text-[#8A9AB0] mt-1">{symbol} — {timeframe} — {from} → {to} — {selected.join(", ")}</div>
            <div className="text-[11px] text-[#8A9AB0] mt-2">قد يستغرق 10-30 ثانية حسب المدة</div>
          </div>
        )}

        {result && !loading && (
          <div className="rounded-2xl border border-[#1E2A3A] bg-[#111827] p-4 mt-4">
            <div className="flex flex-wrap justify-between gap-2">
              <div>
                <div className="text-sm font-black">التقرير — {result.symbol} {result.timeframe} — {from} → {to}</div>
                <div className="text-xs text-[#8A9AB0] mt-1">
                  {selected.length} استراتيجية: {selStrategies.map(s=> s.nameAr).join(" + ")} — {timeframe} — {from} إلى {to}
                </div>
              </div>
              <span className={`px-3 py-1 rounded-full text-xs font-black border ${result.stats.pnl>=0 ? "bg-[#0A2E1A] text-[#00D395] border-[#00D395]" : "bg-[#2e0a14] text-[#FF3B5C] border-[#FF3B5C]"}`}>
                المحصلة: {result.stats.pnl>=0 ? "مكسب" : "خسارة"} {result.stats.pnl>=0?"+":""}{result.stats.pnl.toFixed(2)} USDT {result.stats.pnl>=0?"🟢":"🔴"}
              </span>
            </div>

            <div className="mt-3">
              <div className="text-xs font-bold mb-2">طريقة الاستراتيجية</div>
              <div className="grid md:grid-cols-2 gap-2">
                {selStrategies.map(s=>(
                  <div key={s.id} className="rounded-xl border border-[#1E2A3A] bg-[#0E141D] p-3">
                    <div className="text-xs font-bold">{s.icon} {s.nameAr} — {s.name}</div>
                    <div className="text-[11px] text-[#8A9AB0] mt-1 leading-relaxed">{s.method}</div>
                    <div className="text-[11px] mt-2"><span className={s.winRate>=45?"text-[#00D395]":s.winRate>=35?"text-[#FFB800]":"text-[#FF3B5C]"}>WR {s.winRate}%</span> <span className="text-[#8A9AB0]">PF {s.pf}</span> <span className="text-[#8A9AB0]">· {s.desc}</span></div>
                  </div>
                ))}
              </div>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mt-4">
              <div className="rounded-xl bg-[#0E141D] border border-[#1E2A3A] p-3 text-center">
                <div className="text-[10px] text-[#8A9AB0]">الصفقات</div><div className="text-lg font-black">{result.stats.total}</div>
                <div className="text-[11px] text-[#8A9AB0]">{result.stats.wins} رابحة · {result.stats.losses} خاسرة</div>
              </div>
              <div className="rounded-xl bg-[#0E141D] border border-[#1E2A3A] p-3 text-center">
                <div className="text-[10px] text-[#8A9AB0]">نسبة الربح</div><div className={`text-lg font-black ${result.stats.win_rate>=45?"text-[#00D395]":result.stats.win_rate>=35?"text-[#FFB800]":"text-[#FF3B5C]"}`}>{result.stats.win_rate.toFixed(1)}%</div>
                <div className="text-[11px] text-[#8A9AB0]">PF {result.stats.profit_factor.toFixed(2)}</div>
              </div>
              <div className="rounded-xl bg-[#0E141D] border border-[#1E2A3A] p-3 text-center">
                <div className="text-[10px] text-[#8A9AB0]">المكسب / الخسارة</div>
                <div className="text-xs font-bold text-[#00D395]">مكسب +{(result.stats.avg_win||0).toFixed(2)}</div>
                <div className="text-xs font-bold text-[#FF3B5C]">خسارة {(result.stats.avg_loss||0).toFixed(2)}</div>
              </div>
              <div className={`rounded-xl border p-3 text-center ${result.stats.pnl>=0 ? "bg-[#0A2E1A] border-[#00D395]" : "bg-[#2e0a14] border-[#FF3B5C]"}`}>
                <div className="text-[10px] text-[#8A9AB0]">المحصلة النهائية</div>
                <div className={`text-lg font-black ${result.stats.pnl>=0?"text-[#00D395]":"text-[#FF3B5C]"}`}>{result.stats.pnl>=0?"+":""}{result.stats.pnl.toFixed(2)} USDT</div>
                <div className="text-[11px]">{result.stats.pnl>=0 ? "مكسب" : "خسارة"} · Max DD {result.stats.max_dd.toFixed(2)}</div>
              </div>
            </div>

            <div className="mt-4">
              <div className="text-xs font-bold mb-2">الشارت — السعر + الصفقات + السكور + Equity</div>
              <img key={chartKey} src={`${chartUrl(chartFile)}&k=${chartKey}`} alt="chart" className="w-full rounded-xl border border-[#1E2A3A]" />
            </div>

            <div className="mt-4">
              <div className="text-xs font-bold mb-2">آخر الصفقات — دخول / خروج / مكسب-خسارة</div>
              <div className="overflow-auto rounded-xl border border-[#1E2A3A]">
                <table className="w-full text-xs">
                  <thead className="bg-[#0E141D] text-[#8A9AB0]"><tr><th className="p-2 text-right">دخول</th><th className="p-2 text-right">خروج</th><th className="p-2">اتجاه</th><th className="p-2">دخول</th><th className="p-2">خروج</th><th className="p-2">النتيجة</th><th className="p-2">السبب</th></tr></thead>
                  <tbody>
                    {result.trades.slice(-12).reverse().map((t,i)=>(
                      <tr key={i} className="border-t border-[#1E2A3A]">
                        <td className="p-2 text-[11px]">{String(t.entry_ts).slice(5,16).replace("T"," ")}</td>
                        <td className="p-2 text-[11px]">{String(t.exit_ts).slice(5,16).replace("T"," ")}</td>
                        <td className="p-2"><span className={`px-1.5 py-0.5 rounded text-[10px] font-bold border ${t.side==="long"?"bg-[#0A2E1A] text-[#00D395] border-[#00D395]":"bg-[#2e0a14] text-[#FF3B5C] border-[#FF3B5C]"}`}>{t.side==="long"?"LONG":"SHORT"}</span></td>
                        <td className="p-2 font-mono">{fmt(t.entry)}</td><td className="p-2 font-mono">{fmt(t.exit)}</td>
                        <td className={`p-2 font-bold ${t.pnl>=0?"text-[#00D395]":"text-[#FF3B5C]"}`}>{t.pnl>=0?"+":""}{t.pnl.toFixed(2)}</td>
                        <td className="p-2 text-[11px]">{t.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}

        {error && !loading && (
          <div className="rounded-xl border border-[#FF3B5C] bg-[#2e0a14] p-3 mt-4 text-xs text-[#FF3B5C] whitespace-pre-wrap">{error}</div>
        )}
        {!result && !loading && stdout && (
          <div className="rounded-xl border border-[#1E2A3A] bg-[#0E141D] p-3 mt-4 text-[11px] font-mono whitespace-pre-wrap">{stdout.slice(-4000)}</div>
        )}
      </div>
    </div>
  )
}
