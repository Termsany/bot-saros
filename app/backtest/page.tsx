"use client"
import { useEffect, useMemo, useState } from "react"
import { Area, AreaChart, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis } from "recharts"
import { STRATEGIES, BACKTEST_DAYS, BOT_PAGE, backtestSpanDays, pfTone, sharpeTone, TREND_ID } from "@/lib/strategies"
import { getMyTier } from "@/lib/supabase"
import { PAIRS } from "@/lib/pairs"
import { AppShell } from "@/components/AppShell"
import { Kpi } from "@/components/Kpi"
import { RaqmMark } from "@/components/Logo"
import { apiBacktest, apiUserTier, chartUrl } from "@/lib/api"
import { runBacktestClient } from "@/lib/backtest-client"
import { Check, Play, TriangleAlert } from "lucide-react"

type BTrade = { entry_ts:string; exit_ts:string; side:string; entry:number; exit:number; qty:number; pnl:number; reason:string }
type BacktestData = {
  symbol: string
  timeframe: string
  stats: { total:number; wins:number; losses:number; win_rate:number; pnl:number; avg_win:number; avg_loss:number; profit_factor:number; max_dd:number }
  trades: BTrade[]
  prices?: { t:number; c:number }[]
}

const PROFIT = "#22D3A0", LOSS = "#FF5470", CORONA = "#F5B841", LINE = "#232838", FAINT = "#5D6378", INK = "#F2F3F7"
const TIMEFRAMES = ["15m","1h","4h","1d"]
const REASONS: Record<string,string> = { SL: "وقف خسارة", TP: "هدف", reverse: "إشارة عكسية", close: "نهاية المدة" }

function fmt(n: number|null|undefined, d?: number){
  if(n===null || n===undefined || !isFinite(n)) return "—"
  const digits = d ?? (Math.abs(n) >= 1 ? 2 : 5)
  return n.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })
}
const signed = (v: number) => `${v>=0?"+":""}${fmt(v, 2)}`
function toISODate(d: Date){ return d.toISOString().slice(0,10) }
const daysBack = (to: string, n: number) => { const d = new Date(Date.parse(to)); d.setUTCDate(d.getUTCDate() - (n - 1)); return toISODate(d) }
const shortTs = (s: string) => String(s).slice(5,16).replace("T"," ")

function Field({ label, children }: { label: string, children: React.ReactNode }){
  return <label className="block"><span className="mb-1.5 block text-xs font-semibold text-muted">{label}</span>{children}</label>
}
const inputCls = "w-full rounded-lg border border-line bg-surface2 px-3 py-2 text-sm outline-none transition focus:border-corona/50"

export default function BacktestPage(){
  const [symbol, setSymbol] = useState("BTC/USDT")
  const [timeframe, setTimeframe] = useState("1d")
  const [from, setFrom] = useState(()=> daysBack(toISODate(new Date()), 31))
  const [to, setTo] = useState(()=> toISODate(new Date()))
  const [amount, setAmount] = useState(20)
  const [leverage, setLeverage] = useState(2)
  // only the daily trend runs on one coin; the other three bots trade a whole portfolio (see the home page table)
  const [selected, setSelected] = useState<string[]>([TREND_ID])
  const trend = selected.includes(TREND_ID)   // daily candles only
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<BacktestData|null>(null)
  const [ran, setRan] = useState<{from:string,to:string,strategies:string[]}|null>(null)
  const [stdout, setStdout] = useState("")
  const [error, setError] = useState("")
  const [chartKey, setChartKey] = useState(0)
  // server chart name comes from the backend (unique per run); browser backtests have no server chart
  const [chartFile, setChartFile] = useState("")
  const [tier, setTier] = useState("free")
  // plan's max range — the server enforces it too; here it just keeps the UI honest
  const [maxDays, setMaxDays] = useState<number|null>(BACKTEST_DAYS.free)
  useEffect(()=>{
    // backend first (knows admins); Supabase profile if the backend is asleep/unreachable
    apiUserTier().then(t=> t ?? getMyTier()).catch(()=>"free").then(t=>{
      const days = t in BACKTEST_DAYS ? BACKTEST_DAYS[t] : BACKTEST_DAYS.free
      setTier(t in BACKTEST_DAYS ? t : "free")
      setMaxDays(days)
      // default range is a month — shrink it to fit the plan
      if(days !== null) setFrom(f=> backtestSpanDays(f, to) <= days ? f : daysBack(to, days))
    })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const span = from && to ? backtestSpanDays(from, to) : 0
  const overLimit = maxDays !== null && span > maxDays

  function toggle(id:string){
    if(!STRATEGIES.find(x=> x.id===id)?.perCoin) return
    setSelected([id]); setTimeframe("1d"); setLeverage(2)    // tested at x2; the stop sits before liquidation
  }
  async function run(){
    if(from > to){ setError("التاريخ معكوس — «من» لازم يكون قبل «إلى»"); return }
    if(overLimit){ setError(`المدة ${span} يوم — باقتك تسمح بـ ${maxDays} يوم كحد أقصى. رقّي باقتك لباك تست أطول`); return }
    setLoading(true); setError(""); setResult(null); setChartFile(""); setStdout("")
    try{
      // Try browser-direct first (Bybit/OKX — no Render, no ban)
      const client = await runBacktestClient({ symbol, timeframe: trend ? "1d" : timeframe, from, to, strategies: selected, amount, leverage })
      if(client.ok && client.data){
        setResult(client.data as unknown as BacktestData)
        setRan({ from, to, strategies: selected })
        return
      }
      if("final" in client && client.final){ setError(client.error || "فشل"); return }
      // Fallback: backend (Render), which also renders a chart image
      const j = await apiBacktest({ symbol, timeframe: trend ? "1d" : timeframe, from, to, strategies: selected, amount, leverage })
      setStdout((j.stdout||"") + (j.stderr ? "\n"+j.stderr : "") + (client.error ? "\nClient: "+client.error : ""))
      if(j.data){ setResult(j.data as BacktestData); setRan({ from, to, strategies: selected }); if(typeof j.chart === "string") setChartFile(j.chart) }
      else if(client.error) setError(client.error)
      else if(!j.ok) setError(j.error || (typeof j.detail === "string" ? j.detail : "") || j.stdout || "فشل")
      setChartKey(k=>k+1)
    }catch(e:any){ setError(String(e?.message||e)) }
    finally{ setLoading(false) }
  }

  const ranStrategies = STRATEGIES.filter(s=> (ran?.strategies || []).includes(s.id))
  const equity = useMemo(()=>{
    let cum = 0
    return [{ i: 0, v: 0 }, ...(result?.trades || []).map((t,i)=> ({ i: i+1, v: (cum += t.pnl) }))]
  }, [result])
  const marks = useMemo(()=>{
    const tr = result?.trades || []
    return {
      longIn: tr.filter(t=> t.side==="long").map(t=> ({ t: Date.parse(t.entry_ts), c: t.entry })),
      shortIn: tr.filter(t=> t.side!=="long").map(t=> ({ t: Date.parse(t.entry_ts), c: t.entry })),
      win: tr.filter(t=> t.pnl>=0).map(t=> ({ t: Date.parse(t.exit_ts), c: t.exit })),
      lose: tr.filter(t=> t.pnl<0).map(t=> ({ t: Date.parse(t.exit_ts), c: t.exit })),
    }
  }, [result])
  const s = result?.stats
  const roi = s ? s.pnl / amount * 100 : 0

  return (
    <AppShell active="/backtest" tier={tier}>
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-[26px] font-bold">Backtest</h1>
          <p className="text-[13px] text-muted">اختبر أي استراتيجية على بيانات السوق الحقيقية قبل ما تخاطر بفلوسك</p>
        </div>
        <div className="flex flex-wrap items-center gap-2" dir="ltr">
          <span className="flex items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1.5 font-mono text-[11px] font-bold text-profit"><i className="h-1.5 w-1.5 rounded-full bg-profit"/> BYBIT · OKX · BINANCE</span>
          <span className="rounded-full border border-line bg-surface px-3 py-1.5 font-mono text-[11px] font-bold text-corona">{maxDays===null ? "∞ DAYS" : `MAX ${maxDays} DAYS`}</span>
        </div>
      </header>

      <div className="grid items-start gap-4 lg:grid-cols-[380px_minmax(0,1fr)]">
        {/* settings — right column in RTL */}
        <section className="space-y-5 rounded-2xl border border-line bg-surface p-5 lg:sticky lg:top-8">
          <div className="space-y-3">
            <h2 className="text-sm font-bold">السوق</h2>
            <Field label="العملة">
              <select value={symbol} onChange={e=>setSymbol(e.target.value)} className={`${inputCls} font-display font-bold`} dir="ltr">
                {PAIRS.map(p=> <option key={p} value={p}>{p}</option>)}
              </select>
            </Field>
            <div>
              <span className="mb-1.5 block text-xs font-semibold text-muted">الفريم</span>
              <div className="grid grid-cols-4 gap-0.5 rounded-[10px] bg-surface2 p-[3px]" dir="ltr">
                {TIMEFRAMES.map(tf=>(
                  <button key={tf} onClick={()=>setTimeframe(tf)} disabled={trend && tf!=="1d"} className={`rounded-lg py-1.5 font-mono text-xs font-bold transition disabled:opacity-30 ${(trend ? tf==="1d" : timeframe===tf) ? "bg-corona text-void" : "text-muted hover:text-ink"}`}>{tf}</button>
                ))}
              </div>
            </div>
          </div>

          <div className="space-y-3 border-t border-line pt-5">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-bold">المدة</h2>
              <span className={`font-mono text-[11px] font-bold ${overLimit ? "text-loss" : "text-muted"}`}>{span} يوم{maxDays!==null && ` / ${maxDays}`}</span>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Field label="من"><input type="date" value={from} max={to} onChange={e=>setFrom(e.target.value)} className={inputCls}/></Field>
              <Field label="إلى"><input type="date" value={to} min={from} onChange={e=>setTo(e.target.value)} className={inputCls}/></Field>
            </div>
            <div className="flex gap-1.5">
              {[7, 30, 90].map(n=>{
                const locked = maxDays!==null && n > maxDays
                return (
                  <button key={n} disabled={locked} onClick={()=>setFrom(daysBack(to, n))} title={locked ? "محتاج باقة أعلى" : undefined}
                    className={`flex-1 rounded-lg border py-1.5 text-xs font-semibold transition ${span===n ? "border-corona/50 bg-corona/10 text-corona" : "border-line text-muted hover:text-ink"} disabled:cursor-not-allowed disabled:opacity-40`}>
                    آخر {n} يوم
                  </button>
                )
              })}
            </div>
            {overLimit && <p className="text-xs text-loss">المدة أطول من حد باقتك — <a href="/#pricing" className="underline">رقّي باقتك</a> أو قصّر المدة</p>}
          </div>

          <div className="space-y-3 border-t border-line pt-5">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-bold">مبلغ الصفقة</h2>
              <span className="font-mono text-lg font-bold text-corona" dir="ltr">${amount}</span>
            </div>
            <input type="range" min={10} max={200} step={10} value={amount} onChange={e=>setAmount(parseInt(e.target.value))} className="w-full accent-corona" aria-label="مبلغ الصفقة"/>
            <p className="text-xs text-faint">هامش <b className="font-mono text-ink">${amount}</b> × رافعة x{leverage} = حجم صفقة <b className="font-mono text-corona">${amount*leverage}</b>{trend && " (أقصى حجم — بيصغر لما السوق يهيج)"} · فلوس وهمية 100%</p>
          </div>

          <div className="space-y-2 border-t border-line pt-5">
            <h2 className="text-sm font-bold">الرافعة</h2>
            <div className="grid grid-cols-4 gap-0.5 rounded-[10px] bg-surface2 p-[3px]" dir="ltr">
              {[1, 2, 3, 5].map(x=>(
                <button key={x} onClick={()=>setLeverage(x)} aria-pressed={leverage===x} className={`rounded-lg py-1.5 font-mono text-xs font-bold transition ${leverage===x ? "bg-corona text-void" : "text-muted hover:text-ink"}`}>x{x}</button>
              ))}
            </div>
            <p className="text-xs text-faint">{trend
              ? <>الترند اليومي اتختبر على x2. الصفقة بتفضل مفتوحة أسابيع، والوقف بيتحط قبل التصفية: نزول {(80/leverage).toFixed(0)}% يقفلها.</>
              : <>كل الأرقام المنشورة على x5. رافعة أعلى = ربح وخسارة أكبر بنفس النسبة.</>}</p>
          </div>

          <div className="space-y-3 border-t border-line pt-5">
            <h2 className="text-sm font-bold">الاستراتيجية</h2>
            <div className="space-y-1.5">
              {STRATEGIES.map(st=>{
                const on = selected.includes(st.id)
                return (
                  <button key={st.id} onClick={()=>toggle(st.id)} aria-pressed={on} disabled={!st.perCoin}
                    className={`flex w-full items-center justify-between gap-3 rounded-xl px-3 py-2 text-right transition disabled:cursor-default ${on ? "bg-surface2 ring-1 ring-corona/30" : "border border-line"} ${st.perCoin && !on ? "hover:bg-surface2/60" : ""}`}>
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5 truncate text-sm font-bold">{st.nameAr}{st.risk === "high" && <span className="rounded-full bg-loss/10 px-1.5 text-[10px] text-loss">HIGH RISK</span>}</div>
                      <div className="font-mono text-[11px] text-muted"><span className={`font-bold ${pfTone(st.pf)}`}>PF {st.pf.toFixed(2)}</span><span className="mx-1.5 text-faint">·</span>WR {st.winRate}%<span className="mx-1.5 text-faint">·</span>Sharpe <span className={sharpeTone(st.sharpeOut)}>{st.sharpeOut.toFixed(2)}</span></div>
                      {!st.perCoin && <div className="mt-0.5 text-[11px] text-faint">بتشتغل على محفظة عملات كاملة — مش على عملة واحدة. <a href={BOT_PAGE} target="_blank" rel="noopener" onClick={e=> e.stopPropagation()} className="text-corona hover:underline">شوفها شغالة</a></div>}
                    </div>
                    {st.perCoin && <span className={`grid h-5 w-5 shrink-0 place-items-center rounded-full border ${on ? "border-corona bg-corona text-void" : "border-faint"}`}>{on && <Check size={13} strokeWidth={3}/>}</span>}
                  </button>
                )
              })}
            </div>
          </div>

          <button onClick={run} disabled={loading || selected.length===0 || overLimit}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-corona py-3 text-sm font-bold text-void transition hover:bg-corona-soft disabled:cursor-not-allowed disabled:bg-line disabled:text-faint">
            <Play size={15} fill="currentColor"/>{loading ? "جاري التحليل..." : "شغّل الـ Backtest"}
          </button>
        </section>

        {/* results — left column */}
        <section className="min-w-0 space-y-4">
          {error && !loading && (
            <div className="flex gap-3 rounded-2xl border border-loss/30 bg-loss/[0.06] p-4 text-sm text-loss"><TriangleAlert size={18} className="shrink-0"/><span className="whitespace-pre-wrap">{error}</span></div>
          )}

          {loading && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">{[0,1,2,3].map(i=> <div key={i} className="h-[120px] animate-pulse rounded-2xl border border-line bg-surface"/>)}</div>
              <div className="grid h-[360px] place-items-center rounded-2xl border border-line bg-surface text-center">
                <div>
                  <div className="mx-auto h-10 w-10 animate-spin rounded-full border-2 border-line border-t-corona"/>
                  <div className="mt-3 text-sm font-bold">جاري جلب الشموع وتشغيل الاختبار...</div>
                  <div className="mt-1 font-mono text-xs text-faint" dir="ltr">{symbol} · {timeframe} · {from} → {to}</div>
                </div>
              </div>
            </div>
          )}

          {!result && !loading && (
            <div className="grid min-h-[480px] place-items-center rounded-2xl border border-dashed border-line bg-surface/50 p-8 text-center">
              <div className="max-w-sm">
                <RaqmMark size={64} className="mx-auto opacity-80"/>
                <h2 className="mt-4 text-lg font-bold">جاهز للاختبار</h2>
                <p className="mt-2 text-sm leading-6 text-muted">اختار العملة والمدة والاستراتيجية من اليمين، واضغط «شغّل». النتيجة هتظهر هنا: الأرقام، وشارت السعر بنقط الدخول والخروج، ومنحنى الأرباح، وكل صفقة.</p>
              </div>
            </div>
          )}

          {result && s && !loading && (
            <>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="font-display text-lg font-bold" dir="ltr" style={{textAlign:"right"}}>{result.symbol} · {result.timeframe}</h2>
                  <p className="font-mono text-xs text-muted" dir="ltr" style={{textAlign:"right"}}>{ran?.from} → {ran?.to} · {ranStrategies.map(x=> x.name).join(" + ")}</p>
                </div>
                <span className={`rounded-full px-4 py-1.5 text-sm font-bold ${s.pnl>=0 ? "bg-profit/10 text-profit" : "bg-loss/10 text-loss"}`}>
                  {s.pnl>=0 ? "مكسب" : "خسارة"} <span className="font-mono" dir="ltr">{signed(s.pnl)} USDT</span>
                </span>
              </div>

              <div className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
                <Kpi label="المحصلة" value={signed(s.pnl)} chip={`${roi>=0?"+":""}${roi.toFixed(1)}%`} tone={s.pnl>=0?"profit":"loss"} sub={`USDT · هامش $${amount}`} spark={equity.map(e=> e.v)}/>
                <Kpi label="نسبة الفوز" value={s.total ? `${s.win_rate.toFixed(1)}%` : "—"} chip={`${s.wins}W · ${s.losses}L`} tone={!s.total ? "neutral" : s.win_rate>=50?"profit":"loss"} sub={`${s.total} صفقة`}/>
                <Kpi label="Profit Factor" value={!s.profit_factor ? "—" : s.profit_factor >= 99 ? "∞" : fmt(s.profit_factor, 2)} chip={s.profit_factor ? (s.profit_factor>=1.5?"ممتاز":s.profit_factor>=1?"جيد":"ضعيف") : undefined} tone={!s.profit_factor ? "neutral" : s.profit_factor>=1?"profit":"loss"} sub={`متوسط ربح ${fmt(s.avg_win,2)} · خسارة ${fmt(s.avg_loss,2)}`}/>
                <Kpi label="أقصى تراجع" value={s.max_dd ? `-${fmt(s.max_dd, 2)}` : "0.00"} tone={s.max_dd > amount*0.2 ? "loss" : "neutral"} sub="Max Drawdown · USDT"/>
              </div>

              {result.prices && result.prices.length > 1 && (
                <div className="rounded-2xl border border-line bg-surface p-5">
                  <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                    <h3 className="text-base font-bold">السعر والصفقات</h3>
                    <div className="flex flex-wrap gap-3 text-[11px] text-muted">
                      <span className="flex items-center gap-1"><i className="h-2 w-2 rounded-full bg-profit"/> دخول LONG</span>
                      <span className="flex items-center gap-1"><i className="h-2 w-2 rounded-full bg-loss"/> دخول SHORT</span>
                      <span className="flex items-center gap-1"><i className="h-2 w-2 rounded-full border border-ink"/> خروج</span>
                    </div>
                  </div>
                  <div className="h-[300px]" dir="ltr">
                    <ResponsiveContainer width="100%" height="100%">
                      <ComposedChart data={result.prices} margin={{top:8, right:8, left:0, bottom:0}}>
                        <CartesianGrid stroke={LINE} vertical={false}/>
                        <XAxis dataKey="t" type="number" domain={["dataMin","dataMax"]} tickFormatter={(v)=> new Date(v).toLocaleDateString("en-GB",{day:"2-digit",month:"short"})} tick={{fill:FAINT,fontSize:10}} axisLine={false} tickLine={false} minTickGap={50}/>
                        <YAxis dataKey="c" domain={["auto","auto"]} orientation="right" tickFormatter={(v)=>fmt(v)} tick={{fill:FAINT,fontSize:10}} axisLine={false} tickLine={false} width={64}/>
                        <Tooltip cursor={{stroke:LINE}} contentStyle={{background:"#161A25", border:`1px solid ${LINE}`, borderRadius:8, fontSize:11}} labelFormatter={(v)=> new Date(v as number).toLocaleString()} formatter={(v:any)=> [fmt(v), "السعر"]}/>
                        <Line dataKey="c" stroke={INK} strokeOpacity={0.55} strokeWidth={1.4} dot={false} isAnimationActive={false}/>
                        {/* an empty Scatter falls back to the chart data and marks every candle — render only non-empty sets */}
                        {marks.longIn.length > 0 && <Scatter data={marks.longIn} dataKey="c" fill={PROFIT} shape="triangle" isAnimationActive={false}/>}
                        {marks.shortIn.length > 0 && <Scatter data={marks.shortIn} dataKey="c" fill={LOSS} shape="diamond" isAnimationActive={false}/>}
                        {marks.win.length > 0 && <Scatter data={marks.win} dataKey="c" fill="#07080D" stroke={PROFIT} isAnimationActive={false}/>}
                        {marks.lose.length > 0 && <Scatter data={marks.lose} dataKey="c" fill="#07080D" stroke={LOSS} isAnimationActive={false}/>}
                      </ComposedChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              )}

              <div className="rounded-2xl border border-line bg-surface p-5">
                <div className="mb-3 flex items-center justify-between">
                  <h3 className="text-base font-bold">منحنى الأرباح</h3>
                  <span className="font-mono text-[11px] text-muted">بعد كل صفقة · USDT</span>
                </div>
                <div className="h-[200px]" dir="ltr">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={equity} margin={{top:8, right:8, left:0, bottom:0}}>
                      <defs>
                        <linearGradient id="eq" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor={s.pnl>=0 ? CORONA : LOSS} stopOpacity={0.35}/>
                          <stop offset="100%" stopColor={s.pnl>=0 ? CORONA : LOSS} stopOpacity={0}/>
                        </linearGradient>
                      </defs>
                      <CartesianGrid stroke={LINE} vertical={false}/>
                      <XAxis dataKey="i" tick={{fill:FAINT,fontSize:10}} axisLine={false} tickLine={false} allowDecimals={false}/>
                      <YAxis orientation="right" tickFormatter={(v)=>fmt(v,0)} tick={{fill:FAINT,fontSize:10}} axisLine={false} tickLine={false} width={48}/>
                      <Tooltip contentStyle={{background:"#161A25", border:`1px solid ${LINE}`, borderRadius:8, fontSize:11}} labelFormatter={(v)=> `بعد صفقة ${v}`} formatter={(v:any)=> [signed(v), "الرصيد"]}/>
                      <ReferenceLine y={0} stroke={FAINT} strokeDasharray="3 3"/>
                      <Area dataKey="v" type="monotone" stroke={s.pnl>=0 ? CORONA : LOSS} strokeWidth={2} fill="url(#eq)" isAnimationActive={false}/>
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </div>

              {chartFile && (
                <div className="rounded-2xl border border-line bg-surface p-5">
                  <h3 className="mb-3 text-base font-bold">شارت السيرفر</h3>
                  <img key={chartKey} src={`${chartUrl(chartFile)}&k=${chartKey}`} alt="شارت الباك تست" className="w-full rounded-xl border border-line"/>
                </div>
              )}

              <div className="grid gap-3 md:grid-cols-2">
                {ranStrategies.map(st=>(
                  <div key={st.id} className="rounded-2xl border border-line bg-surface p-4">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-bold">{st.nameAr} <span className="font-display font-medium text-muted">· {st.name}</span></span>
                      <span className="font-mono text-[11px] text-muted"><span className={`font-bold ${pfTone(st.pf)}`}>PF {st.pf.toFixed(2)}</span> · WR {st.winRate}% · {st.trades} صفقة في الاختبار الكامل</span>
                    </div>
                    <p className="mt-2 text-xs leading-6 text-muted">{st.method}</p>
                  </div>
                ))}
              </div>

              <div className="overflow-hidden rounded-2xl border border-line bg-surface">
                <div className="flex items-center justify-between px-5 py-4">
                  <h3 className="text-base font-bold">الصفقات</h3>
                  <span className="font-mono text-[11px] text-muted">{result.trades.length} صفقة</span>
                </div>
                <div className="max-h-[420px] overflow-auto">
                  <table className="w-full min-w-[640px] text-[13px]">
                    <thead className="sticky top-0 bg-surface2 text-[11px] text-muted">
                      <tr>{["الاتجاه","الدخول","الخروج","السبب","النتيجة"].map(h=> <th key={h} className="px-5 py-2.5 text-right font-semibold">{h}</th>)}</tr>
                    </thead>
                    <tbody>
                      {result.trades.length===0 ? (
                        <tr><td colSpan={5} className="px-5 py-10 text-center text-sm text-faint">الاستراتيجية ما دخلتش أي صفقة في المدة دي — جرّب مدة أطول أو فريم أصغر</td></tr>
                      ) : [...result.trades].reverse().map((t,i)=>(
                        <tr key={i} className="border-t border-line">
                          <td className="px-5 py-3"><span className={`rounded-md px-1.5 py-0.5 font-mono text-[10px] font-bold ${t.side==="long" ? "bg-profit/10 text-profit" : "bg-loss/10 text-loss"}`}>{t.side==="long" ? "LONG" : "SHORT"}</span></td>
                          <td className="px-5 py-3 font-mono tabular" dir="ltr" style={{textAlign:"right"}}>{fmt(t.entry)} <span className="text-[11px] text-faint">{shortTs(t.entry_ts)}</span></td>
                          <td className="px-5 py-3 font-mono tabular" dir="ltr" style={{textAlign:"right"}}>{fmt(t.exit)} <span className="text-[11px] text-faint">{shortTs(t.exit_ts)}</span></td>
                          <td className="px-5 py-3 text-muted">{REASONS[t.reason] || t.reason}</td>
                          <td className={`px-5 py-3 font-mono font-bold tabular ${t.pnl>=0 ? "text-profit" : "text-loss"}`} dir="ltr" style={{textAlign:"right"}}>{signed(t.pnl)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          )}

          {stdout && !loading && (
            <details className="rounded-2xl border border-line bg-surface p-4 text-xs text-muted">
              <summary className="cursor-pointer font-semibold">تفاصيل تقنية من السيرفر</summary>
              <pre className="mt-3 max-h-[240px] overflow-auto whitespace-pre-wrap font-mono text-[11px]" dir="ltr">{stdout.slice(-4000)}</pre>
            </details>
          )}
        </section>
      </div>
    </AppShell>
  )
}
