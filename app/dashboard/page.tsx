"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { Bar, BarChart, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { AppShell } from "@/components/AppShell"
import { Kpi } from "@/components/Kpi"
import { Bell, RefreshCw } from "lucide-react"
import { StrategyCards } from "@/components/StrategyCards"
import { LiveBots } from "@/components/LiveBots"
import { PAIRS, NAMES } from "@/lib/pairs"
import { STRATEGIES } from "@/lib/strategies"
import { apiKlines } from "@/lib/api"
import { useLiveBots } from "@/lib/live-bots"
import { getMyTier, getUser } from "@/lib/supabase"

const PROFIT = "#22D3A0"
const LOSS = "#FF5470"
const CORONA = "#F5B841"
const LINE = "#232838"
const FAINT = "#5D6378"
const REFRESH_S = 30

type Candle = { time: number; open: number; high: number; low: number; close: number; volume: number }

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
  const [symbol, setSymbol] = useState("BTC/USDT")
  const [tf, setTf] = useState("1d")
  const { bots, total, loaded } = useLiveBots()

  const [candles, setCandles] = useState<Candle[]>([])
  const [loading, setLoading] = useState(true)
  const [lastUpdated, setLastUpdated] = useState<Date|null>(null)
  // clock only exists in the browser — rendering Date() on the server breaks hydration
  const [now, setNow] = useState<Date|null>(null)
  useEffect(()=>{ setNow(new Date()); const t=setInterval(()=>setNow(new Date()), 1000); return ()=>clearInterval(t) }, [])


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

  useEffect(()=>{ loadKlines(); const t=setInterval(loadKlines, REFRESH_S*1000); return ()=>clearInterval(t) }, [loadKlines])

  const current = candles[candles.length-1]
  const previous = candles[candles.length-2]
  const change = current && previous ? ((current.close - previous.close)/previous.close)*100 : 0
  const chartData = useMemo(()=>{
    let ema = candles[0]?.close ?? 0
    return candles.map(c=> { ema = ema + (c.close - ema) * (2 / 11); return { ...c, wick: [c.low, c.high], ema, up: c.close >= c.open } })
  }, [candles])

  // the bots' open positions on the coin shown in the chart (pairs have no single entry price)
  const base = symbol.split("/")[0]
  const symbolTrades = bots.flatMap(b=> b.positions.filter(p=> p.label===base && p.side!=="pair" && p.entry).map(p=> ({ ...p, bot: b.strategy.nameAr })))
  const nextIn = lastUpdated && now ? Math.max(0, REFRESH_S - Math.floor((now.getTime() - lastUpdated.getTime())/1000)) : null
  const closedTotal = total.wins + total.losses

  return (
    <AppShell active="/dashboard" tier={tier} engine={{ running: total.running > 0 }} nextIn={nextIn}>
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
            <p className="text-[13px] text-muted">{loaded ? `${total.running} من ${STRATEGIES.length} بوتات شغالة دلوقتي على السيرفر` : "بيحمّل البوتات…"} · الشارت: {NAMES[symbol]||symbol} على فريم {tf}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2 sm:gap-2.5" dir="ltr">
            <span className="flex items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1.5 font-mono text-[11px] font-bold text-profit"><i className="h-1.5 w-1.5 animate-pulse rounded-full bg-profit"/> LIVE · BINANCE</span>
            <span className="hidden rounded-full border border-line bg-surface px-3 py-1.5 font-mono text-[11px] font-bold text-muted tabular sm:inline">UTC {now ? now.toISOString().slice(11,19) : "--:--:--"}</span>
            <span className="rounded-full border border-line bg-surface px-3 py-1.5 font-mono text-[11px] font-bold text-corona">PAPER</span>
            <span className="grid h-9 w-9 place-items-center rounded-[10px] border border-line bg-surface text-muted"><Bell size={17} strokeWidth={1.8}/></span>
            <span className="grid h-9 w-9 place-items-center rounded-full border border-umbra/60 bg-umbra/20 text-sm font-bold">{initial || "؟"}</span>
          </div>
        </header>

        {/* KPIs — the four bots together */}
        <section className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
          <Kpi label="الربح المحقق" value={signed(total.realized)} chip={`${total.wins}W · ${total.losses}L`} tone={total.realized>=0?"profit":"loss"} sub="USDT · الـ 4 بوتات (Paper)"/>
          <Kpi label="ربح الصفقات المفتوحة" value={signed(total.unrealized)} tone={total.unrealized>=0?"profit":"loss"} sub="USDT · بسعر آخر دورة"/>
          <Kpi label="الإجمالي" value={signed(total.realized + total.unrealized)} chip={closedTotal ? `${(total.wins/closedTotal*100).toFixed(0)}% فوز` : undefined} tone={total.realized + total.unrealized>=0?"profit":"loss"} sub="محقق + مفتوح"/>
          <Kpi label="الصفقات المفتوحة" value={`${total.open}`} chip={`${total.running}/${STRATEGIES.length} شغالة`} tone="neutral" sub="على الـ 4 بوتات"/>
        </section>

        {/* chart (right) + strategies (left) */}
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
                    {symbolTrades.map(t=>
                      <ReferenceLine key={`${t.bot}${t.side}`} y={t.entry} stroke={t.side==="long" ? PROFIT : LOSS} strokeDasharray="4 4" label={{ value: `${t.bot} · ${t.side.toUpperCase()}`, fill: t.side==="long" ? PROFIT : LOSS, fontSize: 10, position: "insideTopLeft" }}/>
                    )}
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
              {symbolTrades.length > 0 && <span className="font-semibold text-corona">● {symbolTrades.length} صفقة للبوتات على {symbol}</span>}
            </div>
          </div>

          <div id="strategies" className="scroll-mt-6 rounded-2xl border border-line bg-surface p-5">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-base font-bold">الاستراتيجيات</h2>
              <span className="font-mono text-[11px] text-muted">{STRATEGIES.length} بوتات</span>
            </div>
            <StrategyCards tier={tier}/>
            <p className="mt-3 text-[11px] leading-5 text-faint">الأرقام من اختبار على كل عملات Binance من 2019 (والمشطوبة كمان)، هامش $20 × 2، شامل الرسوم والـ funding. نتايج سابقة، مش ضمان.</p>
          </div>
        </section>

        <LiveBots bots={bots} loaded={loaded}/>

    </AppShell>
  )
}
