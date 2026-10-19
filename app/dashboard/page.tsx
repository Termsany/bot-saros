"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { BRAND } from "@/lib/brand"
import { Bar, BarChart, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { Logo } from "@/components/Logo"
import { Bell, CandlestickChart, House, KeyRound, Layers, LayoutDashboard, RefreshCw, Sparkles } from "lucide-react"
import { StrategyPicker } from "@/components/StrategyPicker"
import { PaperWallet } from "@/components/PaperWallet"
import { PAIRS, NAMES } from "@/lib/pairs"
import { STRATEGIES, TIERS } from "@/lib/strategies"
import { apiTrades, apiKlines, apiBotStatus } from "@/lib/api"
import { getMyTier, getUser } from "@/lib/supabase"

const PROFIT = "#22D3A0"
const LOSS = "#FF5470"
const CORONA = "#F5B841"
const LINE = "#232838"
const FAINT = "#5D6378"
const REFRESH_S = 30

type Candle = { time: number; open: number; high: number; low: number; close: number; volume: number }
type Trade = { id:number; symbol:string; side:string; entry:number; exit:number|null; qty:number; pnl:number|null; status:string; sl:number; tp:number; at:string }

function fmt(v: number|null|undefined, digits?: number){
  if(v===null || v===undefined || !isFinite(v)) return "—"
  const d = digits ?? (Math.abs(v) >= 1000 ? 2 : Math.abs(v) >= 1 ? 2 : 5)
  return v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d })
}
const signed = (v: number) => `${v>=0?"+":""}${fmt(v, 2)}`

function CandleTooltip({ active, payload }: any){
  if(!active || !payload?.[0]) return null
  const c = payload[0].payload
  return (
    <div className="rounded-lg border border-line bg-surface2 px-3 py-2 text-[11px] shadow-xl" dir="ltr">
      <div className="mb-1 font-mono text-muted">{new Date(c.time).toLocaleString()}</div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 font-mono tabular"><span>O {fmt(c.open)}</span><span>H {fmt(c.high)}</span><span>L {fmt(c.low)}</span><span>C {fmt(c.close)}</span></div>
    </div>
  )
}

// One bar per candle spanning [low, high]; the body is drawn inside it from open/close.
function CandleShape(p: any){
  const { x, y, width, height, payload: c } = p
  if(!c || !isFinite(y)) return null
  const k = height / ((c.high - c.low) || 1)
  const top = y + (c.high - Math.max(c.open, c.close)) * k
  const bh = Math.max(1, Math.abs(c.open - c.close) * k)
  const color = c.close >= c.open ? PROFIT : LOSS
  const cx = x + width / 2
  return (
    <g>
      <line x1={cx} x2={cx} y1={y} y2={y + height} stroke={color} strokeWidth={1}/>
      <rect x={x + width * 0.12} y={top} width={width * 0.76} height={bh} rx={1} fill={color}/>
    </g>
  )
}

function Sparkline({ values, color }: { values: number[], color: string }){
  const w = 110, h = 30
  const vals = values.length >= 2 ? values : [0, 0]
  const mn = Math.min(...vals), mx = Math.max(...vals)
  const pts = vals.map((v, i) => `${(i / (vals.length - 1) * w).toFixed(1)},${(h - 3 - (v - mn) / ((mx - mn) || 1) * (h - 6)).toFixed(1)}`)
  return <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} className="shrink-0"><polyline points={pts.join(" ")} fill="none" stroke={color} strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round"/></svg>
}

function Kpi({ label, value, chip, tone, sub, spark }: { label: string, value: string, chip?: string, tone: "profit"|"loss"|"neutral", sub: string, spark?: number[] }){
  const chipCls = tone==="profit" ? "bg-profit/10 text-profit" : tone==="loss" ? "bg-loss/10 text-loss" : "bg-line text-muted"
  return (
    <div className="min-w-0 rounded-2xl border border-line bg-surface p-4 sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-[13px] font-semibold text-muted">{label}</span>
        {chip && <span className={`rounded-full px-2 py-0.5 font-mono text-[11px] font-bold tabular ${chipCls}`}>{chip}</span>}
      </div>
      <div className={`mt-2 truncate font-mono text-xl font-bold leading-tight tabular sm:text-[26px] ${tone==="loss" ? "text-loss" : "text-ink"}`} dir="ltr" style={{textAlign:"right"}}>{value}</div>
      <div className="mt-2 flex items-center justify-between gap-2">
        <span className="text-[11px] text-faint">{sub}</span>
        {spark && spark.length >= 2 && <Sparkline values={spark} color={tone==="loss" ? LOSS : CORONA}/>}
      </div>
    </div>
  )
}

const NAV = [
  { href: "/dashboard", label: "لوحة التحكم", icon: LayoutDashboard, active: true },
  { href: "/backtest", label: "Backtest", icon: CandlestickChart },
  { href: "#strategies", label: "الاستراتيجيات", icon: Layers },
  { href: "/llm-lab", label: "مختبر AI", icon: Sparkles },
  { href: "/settings/keys", label: "مفاتيح المنصات", icon: KeyRound },
  { href: "/", label: "الرئيسية", icon: House },
]
const PLAN_COPY: Record<string, string> = {
  free: "استراتيجيتان · Backtest 7 أيام",
  starter: "6 استراتيجيات · Backtest 30 يوم",
  pro: "7 استراتيجيات · Backtest 90 يوم · Futures",
  elite: "15 استراتيجية · Backtest بلا حدود · ذكاء اصطناعي",
}

export default function Dashboard(){
  // tier comes from the user's profile row — not editable from the UI
  const [tier, setTier] = useState("free")
  const [tierReady, setTierReady] = useState(false)
  const [initial, setInitial] = useState("")
  // after Stripe checkout the webhook lands a few seconds after the redirect — poll until the tier updates
  const [activating, setActivating] = useState<"" | "waiting" | "done" | "timeout">("")
  useEffect(()=>{
    let stop = false
    const fromCheckout = new URLSearchParams(window.location.search).get("checkout")==="success"
    if(fromCheckout){ setActivating("waiting"); window.history.replaceState(null, "", "/dashboard") }
    ;(async()=>{
      for(let i=0; i < (fromCheckout ? 30 : 1); i++){
        if(stop) return
        const t = await getMyTier().catch(()=>"free")
        setTier(t); setTierReady(true)
        if(t!=="free"){ if(fromCheckout) setActivating("done"); return }
        if(fromCheckout) await new Promise(r=>setTimeout(r, 2000))
      }
      if(fromCheckout && !stop) setActivating("timeout")
    })()
    getUser().then(u=> setInitial((u?.email || "").slice(0,1).toUpperCase())).catch(()=>{})
    return ()=>{ stop = true }
  }, [])
  const [selected, setSelected] = useState<string[]>(["ict"])
  const [symbol, setSymbol] = useState("BTC/USDT")
  const [tf, setTf] = useState("4h")
  const toggle = (id:string)=> setSelected(s=> s.includes(id) ? s.filter(x=>x!==id) : [...s, id])
  // keep only strategies the plan unlocks (default "ict" is Elite-only); wait for the real tier first
  useEffect(()=>{
    if(!tierReady) return
    const allowed = STRATEGIES.slice(0, TIERS.find(t=> t.id===tier)?.count ?? 2).map(s=> s.id)
    setSelected(s=> { const keep = s.filter(id=> allowed.includes(id)); return keep.length ? keep : [allowed[0]] })
  }, [tier, tierReady])

  const [candles, setCandles] = useState<Candle[]>([])
  const [loading, setLoading] = useState(true)
  const [lastUpdated, setLastUpdated] = useState<Date|null>(null)
  // clock only exists in the browser — rendering Date() on the server breaks hydration
  const [now, setNow] = useState<Date|null>(null)
  useEffect(()=>{ setNow(new Date()); const t=setInterval(()=>setNow(new Date()), 1000); return ()=>clearInterval(t) }, [])

  const [trades, setTrades] = useState<Trade[]>([])
  const [tab, setTab] = useState<"open"|"closed">("open")
  const [engine, setEngine] = useState<{running:boolean}>({ running: false })

  const loadKlines = useCallback(async()=>{
    setLoading(true)
    try{
      const kl = await apiKlines(symbol, tf, 200)
      if(Array.isArray(kl) && kl.length){
        setCandles(kl.map((k:any)=> ({ time: k.time * 1000, open: +k.open, high: +k.high, low: +k.low, close: +k.close, volume: +(k.volume||0) })))
        setLastUpdated(new Date())
      } else {
        const r = await fetch(`https://api.binance.com/api/v3/klines?symbol=${symbol.replace("/","")}&interval=${tf}&limit=200`, { cache: "no-store" })
        if(r.ok){
          const rows = await r.json()
          setCandles(rows.map((row:any)=> ({ time: Number(row[0]), open:Number(row[1]), high:Number(row[2]), low:Number(row[3]), close:Number(row[4]), volume:Number(row[5]) })))
          setLastUpdated(new Date())
        }
      }
    }catch{ setCandles([]) }
    finally{ setLoading(false) }
  }, [symbol, tf])

  const loadTrades = useCallback(async()=>{
    const tr = await apiTrades(50)
    setTrades(Array.isArray(tr) ? tr : [])
    setEngine(await apiBotStatus())
  }, [])

  useEffect(()=>{ loadKlines(); const t=setInterval(loadKlines, REFRESH_S*1000); return ()=>clearInterval(t) }, [loadKlines])
  useEffect(()=>{ loadTrades(); const t=setInterval(loadTrades, REFRESH_S*1000); return ()=>clearInterval(t) }, [loadTrades])

  const current = candles[candles.length-1]
  const previous = candles[candles.length-2]
  const change = current && previous ? ((current.close - previous.close)/previous.close)*100 : 0
  const chartData = useMemo(()=>{
    let ema = candles[0]?.close ?? 0
    return candles.map(c=> { ema = ema + (c.close - ema) * (2 / 11); return { ...c, wick: [c.low, c.high], ema, up: c.close >= c.open } })
  }, [candles])

  const openTrades = trades.filter(t=> t.status==="open" || !t.exit)
  const closedTrades = trades.filter(t=> t.status==="closed" || t.exit)
  const stats = useMemo(()=>{
    const closed = [...closedTrades].sort((a,b)=> a.id-b.id)
    const pnls = closed.map(t=> t.pnl||0)
    const wins = pnls.filter(p=> p>0).length, losses = pnls.filter(p=> p<0).length
    const pnl = pnls.reduce((s,p)=> s+p, 0)
    const sumWin = pnls.filter(p=>p>0).reduce((s,p)=>s+p,0), sumLoss = Math.abs(pnls.filter(p=>p<0).reduce((s,p)=>s+p,0))
    const pf = sumLoss ? sumWin/sumLoss : sumWin ? 99 : 0
    let cum = 0; const equity = pnls.map(p=> cum += p)
    let w = 0; const wrSeries = pnls.map((p,i)=> { if(p>0) w++; return w/(i+1)*100 })
    return { pnl, wins, losses, total: closed.length, pf, equity, wrSeries, winRate: closed.length ? wins/closed.length*100 : 0 }
  }, [closedTrades])
  const symbolTrades = openTrades.filter(t=> t.symbol===symbol)
  const unrealized = (t: Trade)=> current && t.symbol===symbol ? (current.close - t.entry) * t.qty * (t.side==="long" ? 1 : -1) : null

  const nextIn = lastUpdated && now ? Math.max(0, REFRESH_S - Math.floor((now.getTime() - lastUpdated.getTime())/1000)) : null
  const strategyNames = STRATEGIES.filter(s=> selected.includes(s.id)).map(s=> s.name)
  const rows = tab==="open" ? openTrades : [...closedTrades].reverse()

  return (
    <main className="min-h-screen bg-void text-ink lg:flex">
      {/* Sidebar — first child = right side in RTL */}
      <aside className="sticky top-0 hidden h-screen w-[248px] shrink-0 flex-col justify-between border-l border-line bg-surface px-4 py-7 lg:flex">
        <div className="space-y-7">
          <div className="flex justify-end px-2"><Logo size="sm"/></div>
          <nav className="space-y-1">
            {NAV.map(({ href, label, icon: Icon, active })=>(
              <a key={href} href={href} className={`flex items-center justify-between gap-3 rounded-xl px-3 py-2.5 text-sm transition ${active ? "bg-surface2 font-bold text-corona" : "text-muted hover:bg-surface2/60 hover:text-ink"}`}>
                <span>{label}</span><Icon size={18} strokeWidth={1.8}/>
              </a>
            ))}
          </nav>
        </div>
        <div className="space-y-3 rounded-2xl border border-umbra/40 bg-gradient-to-br from-[#1E1846] to-surface p-4">
          <div className="flex items-center justify-between">
            <span className="text-sm font-bold">باقتك</span>
            <span className="rounded-full bg-corona px-2 py-0.5 font-mono text-[10px] font-bold uppercase tracking-wider text-void">{tier}</span>
          </div>
          <p className="text-xs leading-5 text-muted">{PLAN_COPY[tier] || PLAN_COPY.free}</p>
          {tier!=="elite" && <a href="/#pricing" className="block rounded-lg bg-corona py-2 text-center text-xs font-bold text-void transition hover:bg-corona-soft">رقّي باقتك</a>}
          <div className={`flex items-center justify-between rounded-lg px-3 py-2 text-xs ${engine.running ? "bg-profit/10 text-profit" : "bg-line/60 text-muted"}`}>
            <span className="font-semibold">{engine.running ? "● المحرك يعمل" : "○ المحرك متوقف"}</span>
            <span className="font-mono tabular">{nextIn!==null ? `00:${String(nextIn).padStart(2,"0")}` : "--:--"}</span>
          </div>
        </div>
      </aside>

      <div className="min-w-0 flex-1 space-y-5 p-4 lg:p-8">
        {/* mobile header */}
        <div className="flex items-center justify-between lg:hidden">
          <Logo size="sm"/>
          <div className="hidden gap-3 text-xs text-muted min-[360px]:flex"><a href="/backtest">Backtest</a><a href="/">الرئيسية</a></div>
        </div>

        {activating && (
          <div className={`rounded-xl px-4 py-2.5 text-center text-sm ${activating==="timeout" ? "bg-loss/10 text-loss" : "bg-profit/10 text-profit"}`}>
            {activating==="waiting" && "⏳ جاري تفعيل باقتك..."}
            {activating==="done" && `✅ تم تفعيل باقة ${tier}`}
            {activating==="timeout" && "⚠️ الدفع تم بس الباقة لسه ما اتفعلتش — حدّث الصفحة بعد دقيقة، ولو فضلت كده كلّمنا"}
          </div>
        )}

        {/* top bar */}
        <header className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-[26px] font-bold">لوحة التحكم</h1>
            <p className="text-[13px] text-muted">المحرك بيراقب {NAMES[symbol]||symbol} على فريم {tf} بـ {selected.length} استراتيجية</p>
          </div>
          <div className="flex flex-wrap items-center gap-2 sm:gap-2.5" dir="ltr">
            <span className="flex items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1.5 font-mono text-[11px] font-bold text-profit"><i className="h-1.5 w-1.5 animate-pulse rounded-full bg-profit"/> LIVE · BINANCE</span>
            <span className="hidden rounded-full border border-line bg-surface px-3 py-1.5 font-mono text-[11px] font-bold text-muted tabular sm:inline">UTC {now ? now.toISOString().slice(11,19) : "--:--:--"}</span>
            <span className="rounded-full border border-line bg-surface px-3 py-1.5 font-mono text-[11px] font-bold text-corona">PAPER</span>
            <span className="grid h-9 w-9 place-items-center rounded-[10px] border border-line bg-surface text-muted"><Bell size={17} strokeWidth={1.8}/></span>
            <span className="grid h-9 w-9 place-items-center rounded-full border border-umbra/60 bg-umbra/20 text-sm font-bold">{initial || "؟"}</span>
          </div>
        </header>

        {/* KPIs */}
        <section className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
          <Kpi label="إجمالي الربح" value={`${signed(stats.pnl)}`} chip={`${stats.wins}W · ${stats.losses}L`} tone={stats.pnl>=0?"profit":"loss"} sub="USDT · الصفقات المقفولة" spark={stats.equity}/>
          <Kpi label="نسبة الفوز" value={stats.total ? `${stats.winRate.toFixed(1)}%` : "—"} chip={stats.total ? (stats.winRate>=50?"قوية":"تحت 50%") : undefined} tone={!stats.total ? "neutral" : stats.winRate>=50?"profit":"loss"} sub={`${stats.wins} من ${stats.total} صفقة`} spark={stats.wrSeries}/>
          <Kpi label="Profit Factor" value={stats.pf ? fmt(stats.pf, 2) : "—"} chip={stats.pf ? (stats.pf>=1.5?"ممتاز":stats.pf>=1?"جيد":"ضعيف") : undefined} tone={!stats.pf ? "neutral" : stats.pf>=1?"profit":"loss"} sub="الهدف ≥ 1.5" spark={stats.equity}/>
          <Kpi label="الصفقات" value={`${openTrades.length} / ${closedTrades.length}`} chip={openTrades.length ? `${openTrades.length} مفتوحة` : undefined} tone="neutral" sub="مفتوحة / مقفولة"/>
        </section>

        {/* chart (right) + engine & wallet (left) */}
        <section className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
          <div className="min-w-0 rounded-2xl border border-line bg-surface p-4 sm:p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex min-w-0 flex-wrap items-center gap-2 sm:gap-3">
                <select value={symbol} onChange={e=>setSymbol(e.target.value)} aria-label="العملة" className="rounded-lg border border-line bg-surface2 px-2.5 py-1.5 font-display text-base font-bold outline-none focus:border-corona/50" dir="ltr">
                  {PAIRS.map(p=><option key={p} value={p}>{p}</option>)}
                </select>
                <span className="font-mono text-xl font-bold tabular" dir="ltr">{current ? fmt(current.close) : "—"}</span>
                {current && <span className={`rounded-md px-2 py-0.5 font-mono text-[11px] font-bold ${change>=0?"bg-profit/10 text-profit":"bg-loss/10 text-loss"}`} dir="ltr">{change>=0?"▲":"▼"} {Math.abs(change).toFixed(2)}%</span>}
              </div>
              <div className="flex items-center gap-2" dir="ltr">
                <div className="flex gap-0.5 rounded-[10px] bg-surface2 p-[3px]">
                  {["15m","1h","4h","1d"].map(item=>(
                    <button key={item} onClick={()=>setTf(item)} className={`rounded-lg px-3 py-1 font-mono text-[11px] font-bold transition ${tf===item?"bg-corona text-void":"text-muted hover:text-ink"}`}>{item}</button>
                  ))}
                </div>
                <button onClick={loadKlines} className="rounded-lg p-2 text-muted hover:bg-surface2 hover:text-ink" aria-label="تحديث"><RefreshCw size={15} className={loading?"animate-spin":""}/></button>
              </div>
            </div>
            <div className="mt-4 h-[340px] w-full" dir="ltr">
              {loading && !candles.length ? <div className="flex h-full items-center justify-center font-mono text-xs text-faint">جاري تحميل الشموع...</div>
              : !candles.length ? <div className="flex h-full items-center justify-center text-sm text-loss">بيانات السوق مش متاحة دلوقتي — جرّب تحديث</div>
              : (
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={chartData} margin={{top:8, right:8, left:0, bottom:0}} barCategoryGap="18%">
                    <CartesianGrid stroke={LINE} vertical={false}/>
                    <XAxis dataKey="time" tickFormatter={(v)=> new Date(v).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"})} tick={{fill:FAINT,fontSize:10}} axisLine={false} tickLine={false} minTickGap={60}/>
                    <YAxis domain={["auto","auto"]} orientation="right" tickFormatter={(v)=>fmt(v)} tick={{fill:FAINT,fontSize:10}} axisLine={false} tickLine={false} width={64}/>
                    <Tooltip content={<CandleTooltip/> as any} cursor={{fill:"rgba(255,255,255,0.03)"}}/>
                    <Bar dataKey="wick" shape={<CandleShape/>} isAnimationActive={false}/>
                    <Line dataKey="ema" stroke={CORONA} strokeWidth={1.6} dot={false} isAnimationActive={false}/>
                    {current && <ReferenceLine y={current.close} stroke="#F2F3F7" strokeOpacity={0.35} strokeDasharray="2 3"/>}
                    {symbolTrades.map(t=>[
                      <ReferenceLine key={`e${t.id}`} y={t.entry} stroke={CORONA} strokeDasharray="4 4" label={{ value: `دخول ${t.side.toUpperCase()}`, fill: CORONA, fontSize: 10, position: "insideTopLeft" }}/>,
                      <ReferenceLine key={`s${t.id}`} y={t.sl} stroke={LOSS} strokeOpacity={0.6} strokeDasharray="2 4"/>,
                      <ReferenceLine key={`t${t.id}`} y={t.tp} stroke={PROFIT} strokeOpacity={0.6} strokeDasharray="2 4"/>,
                    ])}
                  </ComposedChart>
                </ResponsiveContainer>
              )}
            </div>
            {candles.length > 0 && (
              <div className="h-[56px] w-full" dir="ltr">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData} margin={{top:4, right:72, left:0, bottom:0}} barCategoryGap="18%">
                    <Bar dataKey="volume" isAnimationActive={false} shape={(p:any)=> <rect x={p.x} y={p.y} width={p.width} height={p.height} fill={p.payload.up ? PROFIT : LOSS} fillOpacity={0.28}/>}/>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
            <div className="mt-3 flex flex-wrap items-center justify-end gap-4 text-[11px]">
              <span className="font-mono text-faint" dir="ltr">CANDLES {candles.length} · {tf.toUpperCase()}</span>
              <span className="font-mono font-bold text-corona" dir="ltr">— EMA 10</span>
              {symbolTrades.length > 0 && <span className="font-semibold text-corona">● {symbolTrades.length} صفقة مفتوحة على {symbol}</span>}
            </div>
          </div>

          <div className="space-y-4 rounded-2xl border border-line bg-surface p-5">
            <div className="flex items-center justify-between">
              <h2 className="text-base font-bold">حالة المحرك</h2>
              <span className={`rounded-full border border-line px-3 py-1 text-[11px] font-bold ${engine.running ? "text-profit" : "text-muted"}`}>{engine.running ? "● يعمل" : "○ متوقف"}</span>
            </div>
            <dl className="divide-y divide-line text-[13px]">
              {[
                ["الاستراتيجيات", strategyNames.length ? (strategyNames.length > 2 ? `${strategyNames.slice(0,2).join(" + ")} +${strategyNames.length-2}` : strategyNames.join(" + ")) : "—"],
                ["العملة والفريم", `${symbol} · ${tf}`],
                ["التحديث القادم", nextIn!==null ? `00:${String(nextIn).padStart(2,"0")}` : "--:--"],
                ["الرافعة", "x5"],
                ["الوضع", "PAPER"],
              ].map(([k,v])=>(
                <div key={k} className="flex items-center justify-between py-2.5">
                  <dt className="text-muted">{k}</dt><dd className="font-mono font-bold tabular" dir="ltr">{v}</dd>
                </div>
              ))}
            </dl>
            <PaperWallet/>
          </div>
        </section>

        {/* trades (right) + strategies (left) */}
        <section className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
          <div className="min-w-0 overflow-hidden rounded-2xl border border-line bg-surface">
            <div className="flex items-center justify-between px-5 py-4">
              <h2 className="text-base font-bold">الصفقات</h2>
              <div className="flex gap-0.5 rounded-[10px] bg-surface2 p-[3px]">
                {([["open", `مفتوحة ${openTrades.length}`], ["closed", `مقفولة ${closedTrades.length}`]] as const).map(([id,lbl])=>(
                  <button key={id} onClick={()=>setTab(id)} className={`rounded-lg px-3 py-1 text-xs font-semibold transition ${tab===id?"bg-line text-ink":"text-muted hover:text-ink"}`}>{lbl}</button>
                ))}
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-[13px]">
                <thead>
                  <tr className="bg-surface2/50 text-[11px] text-muted">
                    {["الزوج","الدخول", tab==="open" ? "الحالي" : "الخروج","الوقف","الهدف","الربح/الخسارة"].map(h=> <th key={h} className="px-5 py-2.5 text-right font-semibold">{h}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {rows.length===0 ? (
                    <tr><td colSpan={6} className="px-5 py-10 text-center text-sm text-faint">{tab==="open" ? "لا صفقات مفتوحة دلوقتي — المحرك بيستنى إشارة" : "لسه مفيش صفقات مقفولة"}</td></tr>
                  ) : rows.slice(0, 8).map(t=>{
                    const pnl = tab==="open" ? unrealized(t) : (t.pnl ?? 0)
                    const now$ = tab==="open" ? (t.symbol===symbol && current ? current.close : null) : t.exit
                    return (
                      <tr key={t.id} className="border-t border-line">
                        <td className="px-5 py-3.5">
                          <div className="flex items-center gap-2">
                            <span className="font-display font-medium" dir="ltr">{t.symbol}</span>
                            <span className={`rounded-md px-1.5 py-0.5 font-mono text-[10px] font-bold ${t.side==="long" ? "bg-profit/10 text-profit" : "bg-loss/10 text-loss"}`}>{t.side.toUpperCase()}</span>
                          </div>
                        </td>
                        <td className="px-5 py-3.5 font-mono tabular" dir="ltr" style={{textAlign:"right"}}>{fmt(t.entry)}</td>
                        <td className="px-5 py-3.5 font-mono tabular" dir="ltr" style={{textAlign:"right"}}>{fmt(now$)}</td>
                        <td className="px-5 py-3.5 font-mono text-loss/85 tabular" dir="ltr" style={{textAlign:"right"}}>{fmt(t.sl)}</td>
                        <td className="px-5 py-3.5 font-mono text-profit/85 tabular" dir="ltr" style={{textAlign:"right"}}>{fmt(t.tp)}</td>
                        <td className={`px-5 py-3.5 font-mono font-bold tabular ${pnl===null ? "text-faint" : pnl>=0 ? "text-profit" : "text-loss"}`} dir="ltr" style={{textAlign:"right"}}>{pnl===null ? "—" : signed(pnl)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>

          <div id="strategies" className="rounded-2xl border border-line bg-surface p-5">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-base font-bold">الاستراتيجيات</h2>
              <span className="font-mono text-[11px] text-muted">{selected.length} / {STRATEGIES.length} نشطة</span>
            </div>
            <div className="max-h-[420px] overflow-y-auto pl-1">
              <StrategyPicker selected={selected} onToggle={toggle} tier={tier}/>
            </div>
          </div>
        </section>

        <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4 font-mono text-[10px] text-faint">
          <span>{BRAND.footer}</span>
          <span dir="ltr">{BRAND.domain}</span>
        </footer>
      </div>
    </main>
  )
}
