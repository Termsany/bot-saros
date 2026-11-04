"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { Bar, BarChart, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { AppShell } from "@/components/AppShell"
import { Kpi } from "@/components/Kpi"
import { Card, CardHeader, Dot, PageHeader, Pill } from "@/components/ui"
import { RefreshCw } from "lucide-react"
import { StrategyCards } from "@/components/StrategyCards"
import { LiveBots } from "@/components/LiveBots"
import { MyAccount } from "@/components/MyAccount"
import { RealMoney } from "@/components/RealMoney"
import { PAIRS, NAMES } from "@/lib/pairs"
import { LIVE_BOTS, STRATEGIES, strategyName } from "@/lib/strategies"
import { useLocale, useT } from "@/lib/i18n/locale"
import { useThemeColors } from "@/lib/theme-colors"
import { apiIsAdmin, apiKlines } from "@/lib/api"
import { useLiveBots } from "@/lib/live-bots"
import { getMyTier, getUser } from "@/lib/supabase"

const REFRESH_S = 30

// The dashboard's words (Figma "RAQM — Global Redesign 2026", 04 · Dashboard). The chart's colours follow the theme.
const T = {
  ar: {
    activating: "⏳ جاري تفعيل باقتك...", activated: (t: string) => `✅ تم تفعيل باقة ${t}`, timeout: "⚠️ الدفع تم بس الباقة لسه ما اتفعلتش — حدّث الصفحة بعد دقيقة، ولو فضلت كده كلّمنا",
    title: "لوحة التحكم", running: (r: number, n: number) => `${r} من ${n} بوتات شغالة دلوقتي على السيرفر`, loadingBots: "بيحمّل البوتات…", chart: (s: string, tf: string) => `الشارت: ${s} على فريم ${tf}`,
    connected: (t: string) => `متصل · آخر تحديث ${t}`, connecting: "بيتصل…",
    paper: "بوتات التجربة", paperPill: "PAPER · فلوس وهمية", paperSub: "بيشتغلوا على السيرفر بفلوس وهمية — منفصلين عن البوت الحقيقي",
    k: { real: "الربح المحقق", realSub: (n: number) => `USDT · الـ ${n} بوتات (Paper)`, open: "ربح الصفقات المفتوحة", openSub: "USDT · بسعر آخر دورة", total: "الإجمالي", win: (p: string) => `${p}% فوز`, totalSub: "محقق + مفتوح", legs: "الصفقات المفتوحة", legsChip: (r: number, n: number) => `${r}/${n} شغالة`, legsSub: (n: number) => `على الـ ${n} بوتات` },
    coin: "العملة", refresh: "تحديث", loadingCandles: "جاري تحميل الشموع...", noMarket: "بيانات السوق مش متاحة دلوقتي — جرّب تحديث", botTrades: (n: number, s: string) => `● ${n} صفقة للبوتات على ${s}`,
    botsTitle: "البوتات (Paper)", nRunning: (n: number) => `${n} شغالة`, notReporting: "مش بيكتب حالته", nOpen: (n: number) => `${n} مفتوحة`, noOpen: "مفيش صفقات مفتوحة", totalShort: "الإجمالي",
    nextPaper: "التبديل الأسبوعي الجاي (مومنتم Paper)", details: "تفاصيل كل بوت ←",
    closedTitle: "آخر الصفقات المقفولة", closedSub: "من كل البوتات · Paper", allTrades: "كل الصفقات ←", noClosed: "مفيش صفقات مقفولة لسه", loading: "بيحمّل…",
    head: ["العملة", "البوت", "الاتجاه", "الدخول", "الخروج", "الربح", "السبب", "الوقت"], long: "لونج", short: "شورت", pair: "زوج",
    strat: "الاستراتيجيات", stratSub: "الأرقام من اختبار على كل عملات Binance من 2019 (والمشطوبة كمان)، هامش $20 × 2، شامل الرسوم والـ funding. نتايج سابقة، مش ضمان.", nBots: (n: number) => `${n} بوتات`,
    when: (iso: string) => new Date(iso).toLocaleString("ar-EG", { weekday: "long", day: "numeric", month: "long", hour: "2-digit", minute: "2-digit", timeZone: "Africa/Cairo", numberingSystem: "latn" }) + " بتوقيت مصر",
  },
  en: {
    activating: "⏳ Activating your plan...", activated: (t: string) => `✅ Your ${t} plan is active`, timeout: "⚠️ The payment went through but the plan isn't active yet — refresh in a minute, and contact us if it stays like this",
    title: "Dashboard", running: (r: number, n: number) => `${r} of ${n} bots running on the server now`, loadingBots: "Loading the bots…", chart: (s: string, tf: string) => `Chart: ${s} on ${tf}`,
    connected: (t: string) => `Connected · updated ${t}`, connecting: "Connecting…",
    paper: "Paper bots", paperPill: "PAPER · play money", paperSub: "They run on the server with play money — apart from the real-money bot",
    k: { real: "Realized", realSub: (n: number) => `USDT · all ${n} bots (paper)`, open: "Open P&L", openSub: "USDT · at the last cycle's price", total: "Total", win: (p: string) => `${p}% won`, totalSub: "realized + open", legs: "Open trades", legsChip: (r: number, n: number) => `${r}/${n} running`, legsSub: (n: number) => `across the ${n} bots` },
    coin: "Coin", refresh: "Refresh", loadingCandles: "Loading candles...", noMarket: "Market data isn't available right now — try refreshing", botTrades: (n: number, s: string) => `● ${n} bot trades on ${s}`,
    botsTitle: "Bots (paper)", nRunning: (n: number) => `${n} running`, notReporting: "Not reporting", nOpen: (n: number) => `${n} open`, noOpen: "No open trades", totalShort: "Total",
    nextPaper: "Next weekly rebalance (Momentum, paper)", details: "Every bot in detail →",
    closedTitle: "Latest closed trades", closedSub: "All bots · paper", allTrades: "All trades →", noClosed: "No closed trades yet", loading: "Loading…",
    head: ["Coin", "Bot", "Side", "Entry", "Exit", "P&L", "Reason", "Time"], long: "Long", short: "Short", pair: "Pair",
    strat: "Strategies", stratSub: "Numbers from a backtest on every Binance coin since 2019 (delisted ones too), $20 × 2 margin, fees and funding included. Past results, no promise.", nBots: (n: number) => `${n} bots`,
    when: (iso: string) => new Date(iso).toLocaleString("en-GB", { weekday: "long", day: "numeric", month: "long", hour: "2-digit", minute: "2-digit", timeZone: "UTC" }) + " UTC",
  },
}

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
  const { x, y, width, height, payload: c, up: PROFIT, down: LOSS } = p
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
  const t = useT(T)
  const locale = useLocale(), en = locale === "en"
  const C = useThemeColors()
  const align = { textAlign: en ? "left" : "right" } as const
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
  const [admin, setAdmin] = useState(false)
  useEffect(()=>{ apiIsAdmin().then(setAdmin) }, [])

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
  const symbolTrades = bots.flatMap(b=> b.positions.filter(p=> p.label===base && p.side!=="pair" && p.entry).map(p=> ({ ...p, bot: strategyName(b.strategy, locale) })))
  const nextIn = lastUpdated && now ? Math.max(0, REFRESH_S - Math.floor((now.getTime() - lastUpdated.getTime())/1000)) : null
  const closedTotal = total.wins + total.losses
  // closed trades from every bot's public history (same files as the live bots list), newest first
  const closedTrades = useMemo(() => bots.flatMap(b => ((b.raw?.history || []) as any[]).map(h => ({
    bot: strategyName(b.strategy, locale), label: h.pair || String(h.symbol || "").replace("/USDT", "").split(":")[0],
    side: h.pair ? "pair" : h.side, entry: h.pair ? null : h.entry, exit: h.pair ? null : h.exit,
    pnl: Number(h.pnl) || 0, reason: h.reason || "", time: h.time as string | undefined,
  }))).sort((a, b) => Date.parse(b.time || "0") - Date.parse(a.time || "0")).slice(0, 8), [bots, locale])
  const momentumRaw = bots.find(b => b.strategy.live === "momentum")?.raw
  const nextRebalance = momentumRaw?.next_rebalance ? t.when(momentumRaw.next_rebalance) : ""

  return (
    <AppShell active="/dashboard" tier={tier} engine={{ running: total.running > 0 }} nextIn={nextIn} themed>
        {activating && (
          <div className={`rounded-xl px-4 py-2.5 text-center text-sm ${activating==="timeout" ? "bg-loss/10 text-loss" : "bg-profit/10 text-profit"}`}>
            {activating==="waiting" && t.activating}
            {activating==="done" && t.activated(tier)}
            {activating==="timeout" && t.timeout}
          </div>
        )}

        <PageHeader title={t.title}
          subtitle={`${loaded ? t.running(total.running, LIVE_BOTS.length) : t.loadingBots} · ${t.chart(en ? symbol : NAMES[symbol]||symbol, tf)}`}
          status={<>
            <Pill tone="loss">LIVE + PAPER</Pill>
            <Pill tone={candles.length ? "profit" : "neutral"}><Dot tone={candles.length ? "profit" : "neutral"} pulse={!!candles.length}/>{lastUpdated ? t.connected(lastUpdated.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })) : t.connecting}</Pill>
            <span className="grid h-9 w-9 place-items-center rounded-full border border-umbra/60 bg-umbra/20 text-sm font-bold">{initial || "?"}</span>
          </>}/>

        {/* the real-money bots first; everything below is the paper bots */}
        <RealMoney/>

        <div className="flex flex-wrap items-baseline gap-2 pt-1">
          <h2 className="text-[17px] font-bold">{t.paper}</h2>
          <Pill tone="signal">{t.paperPill}</Pill>
          <span className="text-[12px] text-faint">{t.paperSub}</span>
        </div>

        {/* KPIs — the paper bots together */}
        <section className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
          <Kpi label={t.k.real} value={signed(total.realized)} chip={`${total.wins}W · ${total.losses}L`} tone={total.realized>=0?"profit":"loss"} sub={t.k.realSub(LIVE_BOTS.length)}/>
          <Kpi label={t.k.open} value={signed(total.unrealized)} tone={total.unrealized>=0?"profit":"loss"} sub={t.k.openSub}/>
          <Kpi label={t.k.total} value={signed(total.realized + total.unrealized)} chip={closedTotal ? t.k.win((total.wins/closedTotal*100).toFixed(0)) : undefined} tone={total.realized + total.unrealized>=0?"profit":"loss"} sub={t.k.totalSub}/>
          <Kpi label={t.k.legs} value={`${total.open}`} chip={t.k.legsChip(total.running, LIVE_BOTS.length)} tone="neutral" sub={t.k.legsSub(LIVE_BOTS.length)}/>
        </section>

        {/* chart (right in RTL) + bots (left) */}
        <section className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_372px]">
          <Card className="sm:p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex min-w-0 flex-wrap items-center gap-2 sm:gap-3">
                <select value={symbol} onChange={e=>setSymbol(e.target.value)} aria-label={t.coin} className="rounded-lg border border-line bg-surface2 px-2.5 py-1.5 text-[17px] font-bold outline-none focus:border-corona/50" dir="ltr">
                  {PAIRS.map(p=><option key={p} value={p}>{p}</option>)}
                </select>
                <span className="font-mono text-[22px] font-bold tabular" dir="ltr">{current ? fmt(current.close) : "—"}</span>
                {current && <Pill tone={change>=0 ? "profit" : "loss"}><span className="font-mono" dir="ltr">{change>=0?"+":"−"}{Math.abs(change).toFixed(2)}%</span></Pill>}
              </div>
              <div className="flex items-center gap-2" dir="ltr">
                <div className="flex gap-0.5 rounded-[10px] bg-surface2 p-[3px]">
                  {["15m","1h","4h","1d"].map(item=>(
                    <button key={item} onClick={()=>setTf(item)} className={`rounded-lg px-3 py-1 font-mono text-[11px] font-bold transition ${tf===item?"bg-corona text-on-corona":"text-muted hover:text-ink"}`}>{item}</button>
                  ))}
                </div>
                <button onClick={loadKlines} className="rounded-lg p-2 text-muted hover:bg-surface2 hover:text-ink" aria-label={t.refresh}><RefreshCw size={15} className={loading?"animate-spin":""}/></button>
              </div>
            </div>
            <div className="mt-4 h-[340px] w-full" dir="ltr">
              {loading && !candles.length ? <div className="flex h-full items-center justify-center font-mono text-xs text-faint">{t.loadingCandles}</div>
              : !candles.length ? <div className="flex h-full items-center justify-center text-sm text-loss">{t.noMarket}</div>
              : (
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={chartData} margin={{top:8, right:8, left:0, bottom:0}} barCategoryGap="18%">
                    <CartesianGrid stroke={C.line} vertical={false}/>
                    <XAxis dataKey="time" tickFormatter={(v)=> new Date(v).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"})} tick={{fill:C.faint,fontSize:10}} axisLine={false} tickLine={false} minTickGap={60}/>
                    <YAxis domain={["auto","auto"]} orientation="right" tickFormatter={(v)=>fmt(v)} tick={{fill:C.faint,fontSize:10}} axisLine={false} tickLine={false} width={64}/>
                    <Tooltip content={<CandleTooltip/> as any} cursor={{fill:C.ink, fillOpacity:0.04}}/>
                    <Bar dataKey="wick" shape={<CandleShape up={C.profit} down={C.loss}/>} isAnimationActive={false}/>
                    <Line dataKey="ema" stroke={C.corona} strokeWidth={1.6} dot={false} isAnimationActive={false}/>
                    {current && <ReferenceLine y={current.close} stroke={C.ink} strokeOpacity={0.35} strokeDasharray="2 3"/>}
                    {symbolTrades.map(tr=>
                      <ReferenceLine key={`${tr.bot}${tr.side}`} y={tr.entry} stroke={tr.side==="long" ? C.profit : C.loss} strokeDasharray="4 4" label={{ value: `${tr.bot} · ${tr.side.toUpperCase()}`, fill: tr.side==="long" ? C.profit : C.loss, fontSize: 10, position: "insideTopLeft" }}/>
                    )}
                  </ComposedChart>
                </ResponsiveContainer>
              )}
            </div>
            {candles.length > 0 && (
              <div className="h-[56px] w-full" dir="ltr">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData} margin={{top:4, right:72, left:0, bottom:0}} barCategoryGap="18%">
                    <Bar dataKey="volume" isAnimationActive={false} shape={(p:any)=> <rect x={p.x} y={p.y} width={p.width} height={p.height} fill={p.payload.up ? C.profit : C.loss} fillOpacity={0.28}/>}/>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
            <div className="mt-3 flex flex-wrap items-center justify-end gap-4 text-[11px]">
              <span className="font-mono text-faint" dir="ltr">CANDLES {candles.length} · {tf.toUpperCase()}</span>
              <span className="font-mono font-bold text-corona" dir="ltr">— EMA 10</span>
              {symbolTrades.length > 0 && <span className="font-semibold text-corona">{t.botTrades(symbolTrades.length, symbol)}</span>}
            </div>
          </Card>

          <Card className="flex flex-col">
            <CardHeader title={t.botsTitle} action={<Pill tone={total.running ? "profit" : "neutral"}>{t.nRunning(total.running)}</Pill>}/>
            <div className="flex-1 space-y-1.5">
              {!loaded && <div className="rounded-xl bg-surface2/50 px-3 py-6 text-center text-xs text-faint">{t.loadingBots}</div>}
              {[...bots].sort((a, b) => Number(b.fresh && b.ok) - Number(a.fresh && a.ok) || b.open - a.open).map(b => {
                const pnl = b.realized + b.unrealized, live = b.ok && b.fresh
                return (
                  <a key={b.strategy.id} href="#live-bots" className="flex items-center justify-between gap-3 rounded-xl bg-surface2/55 px-3 py-2.5 transition hover:bg-surface2">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2"><Dot tone={live ? "profit" : "neutral"}/><span className="truncate text-[15px] font-semibold">{strategyName(b.strategy, locale)}</span></div>
                      <div className="mt-0.5 text-[12px] text-muted">{!live ? t.notReporting : b.open ? t.nOpen(b.open) : t.noOpen}</div>
                    </div>
                    <div className="shrink-0 text-end">
                      <div className={`font-mono text-[15px] font-medium tabular ${pnl > 0 ? "text-profit" : pnl < 0 ? "text-loss" : "text-muted"}`} dir="ltr">{signed(pnl)}</div>
                      <div className="text-[11px] text-faint">{t.totalShort}</div>
                    </div>
                  </a>
                )
              })}
            </div>
            {nextRebalance && (
              <div className="mt-3 rounded-xl border border-corona/35 bg-corona/[0.08] px-3.5 py-3">
                <div className="text-[12px] font-semibold text-corona">{t.nextPaper}</div>
                <div className="text-[14px] font-semibold">{nextRebalance}</div>
              </div>
            )}
            <a href="#live-bots" className="mt-3 text-center text-[13px] font-semibold text-corona">{t.details}</a>
          </Card>
        </section>

        <Card>
          <CardHeader title={t.closedTitle} sub={t.closedSub} action={<a href="#live-bots" className="text-[13px] font-semibold text-corona">{t.allTrades}</a>}/>
          {closedTrades.length === 0 ? <div className="rounded-xl bg-surface2/50 px-3 py-6 text-center text-xs text-faint">{loaded ? t.noClosed : t.loading}</div> : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] text-[13px]">
                <thead className="text-[12px] text-faint">
                  <tr>{t.head.map(h => <th key={h} className="px-3 py-2 text-start font-semibold">{h}</th>)}</tr>
                </thead>
                <tbody>
                  {closedTrades.map((tr, i) => (
                    <tr key={i} className="border-t border-line">
                      <td className="px-3 py-2.5 font-semibold" dir="ltr" style={align}>{tr.label}</td>
                      <td className="px-3 py-2.5 text-muted">{tr.bot}</td>
                      <td className="px-3 py-2.5"><Pill tone={tr.side === "long" ? "profit" : tr.side === "short" ? "loss" : "umbra"}>{tr.side === "long" ? t.long : tr.side === "short" ? t.short : t.pair}</Pill></td>
                      <td className="px-3 py-2.5 font-mono tabular" dir="ltr" style={align}>{tr.entry != null ? fmt(tr.entry) : "—"}</td>
                      <td className="px-3 py-2.5 font-mono tabular" dir="ltr" style={align}>{tr.exit != null ? fmt(tr.exit) : "—"}</td>
                      <td className={`px-3 py-2.5 font-mono font-bold tabular ${tr.pnl >= 0 ? "text-profit" : "text-loss"}`} dir="ltr" style={align}>{signed(tr.pnl)}</td>
                      <td className="px-3 py-2.5 text-muted">{tr.reason}</td>
                      <td className="px-3 py-2.5 font-mono text-[12px] text-faint" dir="ltr" style={align}>{tr.time ? new Date(tr.time).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "UTC" }) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <Card id="strategies" className="scroll-mt-6">
          <CardHeader title={t.strat} sub={t.stratSub}
            action={<span className="font-mono text-[12px] text-muted">{t.nBots(STRATEGIES.length)}</span>}/>
          <StrategyCards tier={tier}/>
        </Card>

        {tierReady && <MyAccount tier={tier} bots={bots}/>}

        <LiveBots bots={bots} loaded={loaded} admin={admin}/>

    </AppShell>
  )
}
