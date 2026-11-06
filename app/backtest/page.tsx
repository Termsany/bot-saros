"use client"
import { useEffect, useMemo, useState } from "react"
import { Area, AreaChart, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis } from "recharts"
import { STRATEGIES, TIERS, BACKTEST_DAYS, BOT_PAGE, backtestSpanDays, minCapitalNote, pfTone, sharpeTone, strategyName, unlockTier, TREND_ID } from "@/lib/strategies"
import { useLocale, useT } from "@/lib/i18n/locale"
import { useThemeColors } from "@/lib/theme-colors"
import { getMyTier } from "@/lib/supabase"
import { PAIRS } from "@/lib/pairs"
import { AppShell } from "@/components/AppShell"
import { Kpi } from "@/components/Kpi"
import { Card, CardHeader, PageHeader, Pill } from "@/components/ui"
import { apiBacktest, apiUserTier, apiChartObjectUrl } from "@/lib/api"
import { runBacktestClient } from "@/lib/backtest-client"
import { runPortfolioBacktest, PORTFOLIO_LEVERAGES } from "@/lib/portfolio-backtest"
import { Check, Lock, Play, TriangleAlert } from "lucide-react"

type BTrade = { entry_ts:string; exit_ts:string; side:string; entry:number; exit:number; qty:number; pnl:number; reason:string; symbol?:string }
type BacktestData = {
  portfolio?: boolean
  symbol: string
  timeframe: string
  stats: { total:number; wins:number; losses:number; win_rate:number; pnl:number; avg_win:number; avg_loss:number; profit_factor:number; max_dd:number }
  trades: BTrade[]
  prices?: { t:number; c:number }[]
}

const TIMEFRAMES = ["15m","1h","4h","1d"]

// The page's words (Figma "RAQM — Global Redesign 2026"). The charts' colours follow the theme (lib/theme-colors.ts).
const SIDES_EN: Record<string, string> = { "لونج": "Long", "شورت": "Short", "لونج + شورت": "Long + short" }
const T = {
  ar: {
    reasons: { SL: "وقف خسارة", TP: "هدف", reverse: "إشارة عكسية", close: "نهاية المدة", stop: "وقف حماية",
      "signal off": "الترند وقف", week: "تبديل أسبوعي", time: "خلصت 90 يوم", "delisted/end": "اتشالت / نهاية البيانات", flip: "الترند اتقلب",
      "left the list": "عملة خرجت من القائمة" } as Record<string, string>,
    reversed: "التاريخ معكوس — «من» لازم يكون قبل «إلى»", tooLong: (span: number, max: number) => `المدة ${span} يوم — باقتك تسمح بـ ${max} يوم كحد أقصى. رقّي باقتك لباك تست أطول`, failed: "فشل",
    subtitle: "اختبر أي استراتيجية على بيانات السوق الحقيقية قبل ما تخاطر بفلوسك", unlimited: "بلا حدود", upTo: (n: number) => `لحد ${n} يوم`,
    settings: "إعدادات التشغيل", step1: "الاستراتيجية", oneCoin: "على العملة اللي تختارها", allCoins: "على كل العملات زي البوت", minCap: "أقل رأس مال",
    side: (x: string) => x, method: (st: any) => st.method,
    portfolioNote: <>النتيجة = صفقات البوت في اختباره الكامل (كل عملات Binance من 2019، والعملات بتتختار بالفوليوم وقتها، شامل الرسوم والـ funding) اللي فتحت في المدة دي. صفقاته الحية على </>, botsPage: "صفحة البوتات",
    step2: "السوق والمدة", days: "يوم", coin: "العملة", everyCoin: (n: string) => `كل العملات — زي البوت بالظبط (${n})`, tf: "الفريم", from: "من", to: "إلى",
    needsPlan: "محتاج باقة أعلى", lastN: (n: number) => `آخر ${n} يوم`, overLimit: <>المدة أطول من حد باقتك — </>, upgrade: "رقّي باقتك", orShorten: " أو قصّر المدة",
    step3: "الحجم والرافعة", amountLabel: "مبلغ الصفقة",
    sizeLine: (a: number, l: number, trend: boolean) => <>هامش <b className="font-mono text-ink">${a}</b> × رافعة x{l} = حجم صفقة <b className="font-mono text-corona">${a * l}</b>{trend && " (أقصى حجم — بيصغر لما السوق يهيج)"} · فلوس وهمية 100%</>,
    ratioNote: "ترند النسبة مالوش وقف (الصفقة لونج وشورت مع بعض)، فاتختبر على x2 بس. مبلغ الصفقة بيكبّر ويصغّر النتيجة بنفس النسبة.",
    levNote: (l: number) => `كل رافعة متحسوبة لوحدها: الوقف بيتحط قبل التصفية (نزول ${(80 / l).toFixed(0)}% يقفل الصفقة على x${l})، فالربح مش بيتضاعف بنفس نسبة الرافعة.`,
    trendNote: (l: number) => `الترند اليومي اتختبر على x2. الصفقة بتفضل مفتوحة أسابيع، والوقف بيتحط قبل التصفية: نزول ${(80 / l).toFixed(0)}% يقفلها.`,
    x5Note: "كل الأرقام المنشورة على x5. رافعة أعلى = ربح وخسارة أكبر بنفس النسبة.",
    running: "جاري التحليل...", run: "شغّل الـ Backtest", fetching: "جاري جلب الشموع وتشغيل الاختبار...",
    fullTest: (n: string) => `${n} في الاختبار الكامل`, fullSub: "كل عملات Binance من 2019 · شامل الرسوم والـ funding · اختار المدة واضغط «شغّل» تشوف أي فترة", before: "قبل ما تشغّل",
    k: { trades: "الصفقات", tradesSub: "في الاختبار الكامل", win: "نسبة الفوز", winSub: "من كل الصفقات", pfSub: "الكسب ÷ الخسارة", sharpe: "Sharpe من 2024", sharpeSub: "فترة ما اتختارتش عليها" },
    how: "إزاي بتشتغل", howSub: (sides: string, cap: string) => `${sides} · أقل رأس مال $${cap}`,
    dataUntil: (d: string) => `بيانات الاختبار لحد ${d} — اللي بعدها على صفحة البوتات مباشر`, restored: "آخر تشغيل · محفوظ في المتصفح", csv: "تصدير CSV", gain: "مكسب", loss: "خسارة",
    r: { net: "المحصلة", perTrade: (a: number) => `USDT · $${a} لكل صفقة`, margin: (a: number) => `USDT · هامش $${a}`, win: "نسبة الفوز", nTrades: (n: number) => `${n} صفقة`, pfGrade: (pf: number): string => pf >= 1.5 ? "ممتاز" : pf >= 1 ? "جيد" : "ضعيف", avg: (w: string, l: string) => `متوسط ربح ${w} · خسارة ${l}`, dd: "أقصى تراجع" },
    priceTrades: "السعر والصفقات", longIn: "دخول LONG", shortIn: "دخول SHORT", exit: "خروج", price: "السعر",
    equity: "منحنى الأرباح", equitySub: "بعد كل صفقة · USDT", afterTrade: (v: any) => `بعد صفقة ${v}`, balance: "الرصيد",
    yearly: "الربح لكل سنة", yearlySub: "مجموع ربح الصفقات اللي قفلت في السنة · USDT",
    serverChart: "شارت السيرفر", chartFailed: "الشارت مش متاح", chartAlt: "شارت الباك تست", chartLoading: "بيحمّل الشارت…", inFull: (n: number) => `${n} صفقة في الاختبار الكامل`,
    trades: "الصفقات", nTradesShort: (n: number) => `${n} صفقة`, head: ["الاتجاه", "الدخول", "الخروج", "السبب", "النتيجة"], coinHead: "العملة",
    noTrades: "الاستراتيجية ما دخلتش أي صفقة في المدة دي — جرّب مدة أطول", tech: "تفاصيل تقنية من السيرفر",
  },
  en: {
    reasons: { SL: "Stop loss", TP: "Target", reverse: "Opposite signal", close: "End of range", stop: "Protective stop",
      "signal off": "Trend stopped", week: "Weekly rebalance", time: "90 days ended", "delisted/end": "Delisted / end of data", flip: "Trend flipped",
      "left the list": "Coin left the list" } as Record<string, string>,
    reversed: "The dates are reversed — \"From\" must be before \"To\"", tooLong: (span: number, max: number) => `${span} days — your plan allows up to ${max} days. Upgrade for longer backtests`, failed: "Failed",
    subtitle: "Test any strategy on real market data before you risk your money", unlimited: "Unlimited", upTo: (n: number) => `Up to ${n} days`,
    settings: "Run settings", step1: "Strategy", oneCoin: "on the coin you pick", allCoins: "on every coin, like the bot", minCap: "Min. capital",
    side: (x: string) => SIDES_EN[x] || x,
    method: (st: any) => METHOD_EN[st.id] || st.method,
    portfolioNote: <>The result = the bot's trades in its full backtest (every Binance coin since 2019, coins picked by their volume at the time, fees and funding included) that opened in this range. Its live trades are on the </>, botsPage: "bots page",
    step2: "Market and range", days: "days", coin: "Coin", everyCoin: (n: string) => `Every coin — exactly like the bot (${n})`, tf: "Timeframe", from: "From", to: "To",
    needsPlan: "Needs a higher plan", lastN: (n: number) => `Last ${n} days`, overLimit: <>The range is longer than your plan allows — </>, upgrade: "upgrade your plan", orShorten: " or shorten it",
    step3: "Size and leverage", amountLabel: "Trade amount",
    sizeLine: (a: number, l: number, trend: boolean) => <>Margin <b className="font-mono text-ink">${a}</b> × x{l} leverage = position <b className="font-mono text-corona">${a * l}</b>{trend && " (the most — it shrinks when the market gets wild)"} · 100% play money</>,
    ratioNote: "Ratio Trend has no stop (each trade is long and short together), so it was tested at x2 only. The amount scales the result in proportion.",
    levNote: (l: number) => `Each leverage is computed on its own: the stop sits before liquidation (a ${(80 / l).toFixed(0)}% move closes the trade at x${l}), so profit doesn't grow in proportion to leverage.`,
    trendNote: (l: number) => `Daily Trend was tested at x2. A trade stays open for weeks, and the stop sits before liquidation: a ${(80 / l).toFixed(0)}% drop closes it.`,
    x5Note: "Every published number is at x5. Higher leverage = bigger wins and losses in proportion.",
    running: "Running...", run: "Run the backtest", fetching: "Fetching candles and running the test...",
    fullTest: (n: string) => `${n} in its full backtest`, fullSub: "Every Binance coin since 2019 · fees and funding included · pick a range and press Run to see any period", before: "Before you run",
    k: { trades: "Trades", tradesSub: "in the full backtest", win: "Win rate", winSub: "of all trades", pfSub: "wins ÷ losses", sharpe: "Sharpe since 2024", sharpeSub: "a period not used to choose it" },
    how: "How it trades", howSub: (sides: string, cap: string) => `${sides} · min. capital $${cap}`,
    dataUntil: (d: string) => `Backtest data runs to ${d} — after that, see the bots page live`, restored: "Last run · saved in this browser", csv: "Export CSV", gain: "Gain", loss: "Loss",
    r: { net: "Net", perTrade: (a: number) => `USDT · $${a} per trade`, margin: (a: number) => `USDT · $${a} margin`, win: "Win rate", nTrades: (n: number) => `${n} trades`, pfGrade: (pf: number): string => pf >= 1.5 ? "Excellent" : pf >= 1 ? "Good" : "Weak", avg: (w: string, l: string) => `avg win ${w} · loss ${l}`, dd: "Max drawdown" },
    priceTrades: "Price and trades", longIn: "LONG entry", shortIn: "SHORT entry", exit: "Exit", price: "Price",
    equity: "Equity curve", equitySub: "after each trade · USDT", afterTrade: (v: any) => `After trade ${v}`, balance: "Balance",
    yearly: "Profit by year", yearlySub: "sum of the trades closed in the year · USDT",
    serverChart: "Server chart", chartFailed: "The chart isn't available", chartAlt: "Backtest chart", chartLoading: "Loading the chart…", inFull: (n: number) => `${n} trades in the full backtest`,
    trades: "Trades", nTradesShort: (n: number) => `${n} trades`, head: ["Side", "Entry", "Exit", "Reason", "Result"], coinHead: "Coin",
    noTrades: "The strategy didn't enter any trade in this range — try a longer one", tech: "Technical details from the server",
  },
}
const METHOD_EN: Record<string, string> = {
  trend_daily: "Every day at the close, on the top 10 coins by volume: if the price is above its level of 20, 60 and 120 days ago on 2 of 3, it buys; when the trend stops, it sells. The size shrinks when the market gets wild, with a protective stop before liquidation. Built on time-series momentum research.",
  momentum_ls: "Every week it ranks the top 50 coins by volume on their last two weeks: long the strongest 5, short the weakest 5, swapped after a week (40% stop). Built on cross-sectional crypto momentum research (Liu, Tsyvinski & Wu 2022).",
  listing_short: "Shorts a new Binance listing 30 days after launch, closing after 90 days or if the price rises 40% above entry, at most 10 at once. Built on research showing new coins fall after the hype (Benedetti & Kostovetsky 2021).",
  ratio_trend: "Every pair among the top 7 coins by volume (21 pairs): if the ratio of the two prices is above its 50-day average, long the first and short the second, and the other way round. A big worst drawdown, and adding it to the other bots lowered their result in the last two years — hence High Risk.",
}

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
const inputCls = "w-full rounded-xl border border-line bg-void px-3 py-2.5 text-sm outline-none transition focus:border-corona/60"
function Step({ n, title, right }: { n: number, title: string, right?: React.ReactNode }){
  return <div className="flex items-center justify-between gap-2"><h2 className="flex items-center gap-2 text-[15px] font-semibold"><span className="grid h-[22px] w-[22px] place-items-center rounded-full bg-corona/15 font-mono text-[12px] text-corona">{n}</span>{title}</h2>{right}</div>
}

export default function BacktestPage(){
  const t = useT(T)
  const locale = useLocale(), en = locale === "en"
  const C = useThemeColors()
  const align = { textAlign: en ? "left" : "right" } as const
  const [symbol, setSymbol] = useState("BTC/USDT")
  const [timeframe, setTimeframe] = useState("1d")
  const [from, setFrom] = useState(()=> daysBack(toISODate(new Date()), 31))
  const [to, setTo] = useState(()=> toISODate(new Date()))
  const [amount, setAmount] = useState(20)
  const [leverage, setLeverage] = useState(2)
  // only the daily trend runs on one coin; the other three bots trade a whole portfolio (see the home page table)
  const [selected, setSelected] = useState<string[]>([TREND_ID])
  const sel = STRATEGIES.find(x=> x.id===selected[0])
  const portfolio = !!sel && !sel.perCoin     // trades many coins: results come from its full historical test
  const [dataTo, setDataTo] = useState("")
  const trend = selected.includes(TREND_ID)   // daily candles only
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<BacktestData|null>(null)
  const [ran, setRan] = useState<{from:string,to:string,strategies:string[]}|null>(null)
  const [stdout, setStdout] = useState("")
  const [error, setError] = useState("")
  const [chartKey, setChartKey] = useState(0)
  // server chart name comes from the backend (unique per run); browser backtests have no server chart
  const [chartFile, setChartFile] = useState("")
  const [chartSrc, setChartSrc] = useState("")
  useEffect(()=>{
    if(!chartFile){ setChartSrc(""); return }
    let url = "", stop = false
    apiChartObjectUrl(chartFile).then(u=>{ if(u){ url = u; if(!stop) setChartSrc(u); else URL.revokeObjectURL(u) } else if(!stop) setChartSrc("failed") })
    return ()=>{ stop = true; setChartSrc(""); if(url) URL.revokeObjectURL(url) }
  }, [chartFile, chartKey])
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

  const planCount = TIERS.find(t=> t.id===tier)?.count ?? 1
  function toggle(id:string){
    if(STRATEGIES.findIndex(x=> x.id===id) >= planCount) return   // locked by the plan (the server checks too)
    setSelected([id]); setTimeframe("1d"); setLeverage(2)    // every bot was tested at x2
    setResult(null); setError("")
  }
  async function run(){
    if(from > to){ setError(t.reversed); return }
    if(overLimit){ setError(t.tooLong(span, maxDays as number)); return }
    setLoading(true); setError(""); setResult(null); setChartFile(""); setStdout(""); setRestored(false)
    if(portfolio){
      try{
        const res = await runPortfolioBacktest({ strategy: selected[0], from, to, amount, leverage })
        if(res.ok){ setResult(res.data as unknown as BacktestData); setRan({ from, to, strategies: selected }); setDataTo(res.dataTo) }
        else setError(res.error)
      } finally { setLoading(false) }
      return
    }
    try{
      // Try browser-direct first (Bybit/OKX — no Render, no ban)
      const client = await runBacktestClient({ symbol, timeframe: trend ? "1d" : timeframe, from, to, strategies: selected, amount, leverage })
      if(client.ok && client.data){
        setResult(client.data as unknown as BacktestData)
        setRan({ from, to, strategies: selected })
        return
      }
      if("final" in client && client.final){ setError(client.error || t.failed); return }
      // Fallback: backend (Render), which also renders a chart image
      const j = await apiBacktest({ symbol, timeframe: trend ? "1d" : timeframe, from, to, strategies: selected, amount, leverage })
      setStdout((j.stdout||"") + (j.stderr ? "\n"+j.stderr : "") + (client.error ? "\nClient: "+client.error : ""))
      if(j.data){ setResult(j.data as BacktestData); setRan({ from, to, strategies: selected }); if(typeof j.chart === "string") setChartFile(j.chart) }
      else if(client.error) setError(client.error)
      else if(!j.ok) setError(j.error || (typeof j.detail === "string" ? j.detail : "") || j.stdout || t.failed)
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

  // the last run survives a reload (this browser only); a failed read or write just means no saved run
  const SAVED = "raqm:last-backtest"
  const [restored, setRestored] = useState(false)
  useEffect(()=>{
    try{
      const saved = JSON.parse(localStorage.getItem(SAVED) || "null")
      if(saved?.result?.stats && saved?.ran){ setResult(saved.result); setRan(saved.ran); setRestored(true) }
    }catch{}
  }, [])
  useEffect(()=>{
    if(!result || !ran || restored) return
    try{ localStorage.setItem(SAVED, JSON.stringify({ result, ran })) }catch{}
  }, [result, ran, restored])
  const yearly = useMemo(()=>{
    const by: Record<string, number> = {}
    for(const t of result?.trades || []){ const y = String(t.exit_ts).slice(0, 4); if(/^\d{4}$/.test(y)) by[y] = (by[y] || 0) + t.pnl }
    return Object.entries(by).sort(([a],[b])=> a.localeCompare(b))
  }, [result])
  function exportCsv(){
    if(!result) return
    const cols = ["symbol","side","entry_ts","entry","exit_ts","exit","qty","pnl","reason"] as const
    const esc = (v: unknown) => { const x = String(v ?? ""); return /[",\n]/.test(x) ? `"${x.replace(/"/g, '""')}"` : x }
    const csv = [cols.join(","), ...result.trades.map(t=> cols.map(c=> esc(c === "symbol" ? (t.symbol || result.symbol) : (t as any)[c])).join(","))].join("\n")
    const url = URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" }))
    const a = document.createElement("a"); a.href = url; a.download = `backtest-${(ran?.strategies || []).join("+")}-${ran?.from}-${ran?.to}.csv`; a.click()
    setTimeout(()=> URL.revokeObjectURL(url), 1000)
  }
  const roi = s ? s.pnl / amount * 100 : 0

  return (
    <AppShell active="/backtest" tier={tier} themed>
      <PageHeader title="Backtest" subtitle={t.subtitle}
        status={<>
          <Pill tone="profit"><span className="font-mono" dir="ltr">BYBIT · OKX · BINANCE</span></Pill>
          <Pill tone="corona"><span className="font-mono">{maxDays===null ? t.unlimited : t.upTo(maxDays)}</span></Pill>
        </>}/>

      <div className="grid items-start gap-4 lg:grid-cols-[380px_minmax(0,1fr)]">
        {/* settings — right column in RTL */}
        <section className="space-y-5 rounded-2xl border border-line bg-surface p-5 lg:sticky lg:top-8">
          <h2 className="text-[17px] font-bold">{t.settings}</h2>
          <div className="space-y-3">
            <Step n={1} title={t.step1}/>
            <div className="space-y-1.5">
              {STRATEGIES.map((st, i)=>{
                const on = selected.includes(st.id), locked = i >= planCount
                return (
                  <button key={st.id} onClick={()=>toggle(st.id)} aria-pressed={on} disabled={locked}
                    className={`flex w-full items-center justify-between gap-3 rounded-xl px-3 py-2 text-start transition disabled:cursor-not-allowed disabled:opacity-60 ${on ? "bg-surface2 ring-1 ring-corona/30" : "border border-line hover:bg-surface2/60"}`}>
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5 truncate text-sm font-bold">{strategyName(st, locale)}{st.risk === "high" && <span className="rounded-full bg-loss/10 px-1.5 text-[10px] text-loss">HIGH RISK</span>}</div>
                      <div className="font-mono text-[11px] text-muted"><span className={`font-bold ${pfTone(st.pf)}`}>PF {st.pf.toFixed(2)}</span><span className="mx-1.5 text-faint">·</span>WR {st.winRate}%<span className="mx-1.5 text-faint">·</span>Sharpe <span className={sharpeTone(st.sharpeOut)}>{st.sharpeOut.toFixed(2)}</span></div>
                      <div className="mt-0.5 text-[11px] text-faint">{st.perCoin ? t.oneCoin : t.allCoins} · {t.side(st.sides)} · <span className="font-bold text-corona" title={en ? undefined : minCapitalNote(st)}>{t.minCap} ${st.minCapital.toLocaleString("en-US")}</span></div>
                    </div>
                    {locked
                      ? <span className="flex shrink-0 items-center gap-1 rounded-full bg-corona/10 px-2 py-0.5 text-[10px] font-bold text-corona"><Lock size={11}/> {unlockTier(i).name}</span>
                      : <span className={`grid h-5 w-5 shrink-0 place-items-center rounded-full border ${on ? "border-corona bg-corona text-on-corona" : "border-faint"}`}>{on && <Check size={13} strokeWidth={3}/>}</span>}
                  </button>
                )
              })}
            </div>
            {portfolio && <p className="text-[11px] leading-5 text-faint">{t.portfolioNote}<a href={BOT_PAGE} target="_blank" rel="noopener" className="text-corona hover:underline">{t.botsPage}</a>.</p>}
          </div>

          <div className="space-y-3 border-t border-line pt-5">
            <Step n={2} title={t.step2} right={<span className={`font-mono text-[11px] font-bold ${overLimit ? "text-loss" : "text-muted"}`}>{span} {t.days}{maxDays!==null && ` / ${maxDays}`}</span>}/>
            <Field label={t.coin}>
              {portfolio
                ? <div className={`${inputCls} text-muted`}>{t.everyCoin(sel ? strategyName(sel, locale) : "")}</div>
                : <select value={symbol} onChange={e=>setSymbol(e.target.value)} className={`${inputCls} font-display font-bold`} dir="ltr">
                    {PAIRS.map(p=> <option key={p} value={p}>{p}</option>)}
                  </select>}
            </Field>
            <div>
              <span className="mb-1.5 block text-xs font-semibold text-muted">{t.tf}</span>
              <div className="grid grid-cols-4 gap-0.5 rounded-[10px] bg-surface2 p-[3px]" dir="ltr">
                {TIMEFRAMES.map(tf=>(
                  <button key={tf} onClick={()=>setTimeframe(tf)} disabled={trend && tf!=="1d"} className={`rounded-lg py-1.5 font-mono text-xs font-bold transition disabled:opacity-30 ${(trend ? tf==="1d" : timeframe===tf) ? "bg-corona text-on-corona" : "text-muted hover:text-ink"}`}>{tf}</button>
                ))}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Field label={t.from}><input type="date" value={from} max={to} onChange={e=>setFrom(e.target.value)} className={inputCls}/></Field>
              <Field label={t.to}><input type="date" value={to} min={from} onChange={e=>setTo(e.target.value)} className={inputCls}/></Field>
            </div>
            <div className="flex gap-1.5">
              {[7, 30, 90].map(n=>{
                const locked = maxDays!==null && n > maxDays
                return (
                  <button key={n} disabled={locked} onClick={()=>setFrom(daysBack(to, n))} title={locked ? t.needsPlan : undefined}
                    className={`flex-1 rounded-lg border py-1.5 text-xs font-semibold transition ${span===n ? "border-corona/50 bg-corona/10 text-corona" : "border-line text-muted hover:text-ink"} disabled:cursor-not-allowed disabled:opacity-40`}>
                    {t.lastN(n)}
                  </button>
                )
              })}
            </div>
            {overLimit && <p className="text-xs text-loss">{t.overLimit}<a href={en ? "/#pricing" : "/ar#pricing"} className="underline">{t.upgrade}</a>{t.orShorten}</p>}
          </div>

          <div className="space-y-3 border-t border-line pt-5">
            <Step n={3} title={t.step3} right={<span className="font-mono text-lg font-bold text-corona" dir="ltr">${amount}</span>}/>
            <input type="range" min={10} max={200} step={10} value={amount} onChange={e=>setAmount(parseInt(e.target.value))} className="w-full accent-corona" aria-label={t.amountLabel}/>
            <p className="text-xs text-faint">{t.sizeLine(amount, leverage, trend)}</p>
            <div className="grid grid-cols-4 gap-0.5 rounded-[10px] bg-surface2 p-[3px]" dir="ltr">
              {[1, 2, 3, 5].map(x=>(
                <button key={x} onClick={()=>setLeverage(x)} aria-pressed={leverage===x} disabled={portfolio && !(PORTFOLIO_LEVERAGES[selected[0]] || [2]).includes(x)} className={`rounded-lg py-1.5 font-mono text-xs font-bold transition disabled:opacity-30 ${leverage===x ? "bg-corona text-on-corona" : "text-muted hover:text-ink"}`}>x{x}</button>
              ))}
            </div>
            <p className="text-xs text-faint">{portfolio
              ? (selected[0] === "ratio_trend"
                ? t.ratioNote
                : t.levNote(leverage))
              : trend
              ? t.trendNote(leverage)
              : t.x5Note}</p>
          </div>

          <button onClick={run} disabled={loading || selected.length===0 || overLimit}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-corona py-3 text-sm font-bold text-on-corona transition hover:bg-corona-soft disabled:cursor-not-allowed disabled:bg-line disabled:text-faint">
            <Play size={15} fill="currentColor"/>{loading ? t.running : t.run}
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
                  <div className="mt-3 text-sm font-bold">{t.fetching}</div>
                  <div className="mt-1 font-mono text-xs text-faint" dir="ltr">{symbol} · {timeframe} · {from} → {to}</div>
                </div>
              </div>
            </div>
          )}

          {!result && !loading && sel && (
            <div className="space-y-4">
              <div className="flex flex-wrap items-end justify-between gap-3">
                <div>
                  <h2 className="text-[17px] font-bold">{t.fullTest(strategyName(sel, locale))}</h2>
                  <p className="text-[12px] text-muted">{t.fullSub}</p>
                </div>
                <Pill tone="corona">{t.before}</Pill>
              </div>
              <div className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
                <Kpi label={t.k.trades} value={sel.trades.toLocaleString("en-US")} tone="neutral" sub={t.k.tradesSub}/>
                <Kpi label={t.k.win} value={`${sel.winRate}%`} tone="neutral" sub={t.k.winSub}/>
                <Kpi label="Profit Factor" value={sel.pf.toFixed(2)} tone={sel.pf >= 1 ? "profit" : "loss"} sub={t.k.pfSub}/>
                <Kpi label={t.k.sharpe} value={sel.sharpeOut.toFixed(2)} tone={sel.sharpeOut >= 0.5 ? "profit" : "neutral"} sub={t.k.sharpeSub}/>
              </div>
              <Card>
                <CardHeader title={t.how} sub={t.howSub(t.side(sel.sides), sel.minCapital.toLocaleString("en-US"))}/>
                <p className="text-[14px] leading-7 text-muted">{t.method(sel)}</p>
              </Card>
            </div>
          )}

          {result && s && !loading && (
            <>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="font-display text-lg font-bold" dir="ltr" style={align}>{result.portfolio ? `${sel?.name || ""} · ALL COINS` : `${result.symbol} · ${result.timeframe}`}</h2>
                  <p className="font-mono text-xs text-muted" dir="ltr" style={align}>{ran?.from} → {ran?.to} · {ranStrategies.map(x=> x.name).join(" + ")}</p>
                  {result.portfolio && dataTo && ran?.to && ran.to > dataTo && <p className="text-[11px] text-corona">{t.dataUntil(dataTo)}</p>}
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  {restored && <Pill tone="neutral">{t.restored}</Pill>}
                  <button onClick={exportCsv} disabled={!result.trades.length} className="rounded-xl border border-line bg-surface2 px-3.5 py-2 text-[13px] font-semibold transition hover:border-corona/40 disabled:opacity-40">{t.csv}</button>
                  <span className={`rounded-full px-4 py-1.5 text-sm font-bold ${s.pnl>=0 ? "bg-profit/10 text-profit" : "bg-loss/10 text-loss"}`}>
                    {s.pnl>=0 ? t.gain : t.loss} <span className="font-mono" dir="ltr">{signed(s.pnl)} USDT</span>
                  </span>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
                <Kpi label={t.r.net} value={signed(s.pnl)} chip={result.portfolio ? undefined : `${roi>=0?"+":""}${roi.toFixed(1)}%`} tone={s.pnl>=0?"profit":"loss"} sub={result.portfolio ? t.r.perTrade(amount) : t.r.margin(amount)} spark={equity.map(e=> e.v)}/>
                <Kpi label={t.r.win} value={s.total ? `${s.win_rate.toFixed(1)}%` : "—"} chip={`${s.wins}W · ${s.losses}L`} tone={!s.total ? "neutral" : s.win_rate>=50?"profit":"loss"} sub={t.r.nTrades(s.total)}/>
                <Kpi label="Profit Factor" value={!s.profit_factor ? "—" : s.profit_factor >= 99 ? "∞" : fmt(s.profit_factor, 2)} chip={s.profit_factor ? t.r.pfGrade(s.profit_factor) : undefined} tone={!s.profit_factor ? "neutral" : s.profit_factor>=1?"profit":"loss"} sub={t.r.avg(fmt(s.avg_win,2), fmt(s.avg_loss,2))}/>
                <Kpi label={t.r.dd} value={s.max_dd ? `-${fmt(s.max_dd, 2)}` : "0.00"} tone={s.max_dd > amount*0.2 ? "loss" : "neutral"} sub="Max Drawdown · USDT"/>
              </div>

              {result.prices && result.prices.length > 1 && (
                <div className="rounded-2xl border border-line bg-surface p-5">
                  <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                    <h3 className="text-[17px] font-bold">{t.priceTrades}</h3>
                    <div className="flex flex-wrap gap-3 text-[11px] text-muted">
                      <span className="flex items-center gap-1"><i className="h-2 w-2 rounded-full bg-profit"/> {t.longIn}</span>
                      <span className="flex items-center gap-1"><i className="h-2 w-2 rounded-full bg-loss"/> {t.shortIn}</span>
                      <span className="flex items-center gap-1"><i className="h-2 w-2 rounded-full border border-ink"/> {t.exit}</span>
                    </div>
                  </div>
                  <div className="h-[300px]" dir="ltr">
                    <ResponsiveContainer width="100%" height="100%">
                      <ComposedChart data={result.prices} margin={{top:8, right:8, left:0, bottom:0}}>
                        <CartesianGrid stroke={C.line} vertical={false}/>
                        <XAxis dataKey="t" type="number" domain={["dataMin","dataMax"]} tickFormatter={(v)=> new Date(v).toLocaleDateString("en-GB",{day:"2-digit",month:"short"})} tick={{fill:C.faint,fontSize:10}} axisLine={false} tickLine={false} minTickGap={50}/>
                        <YAxis dataKey="c" domain={["auto","auto"]} orientation="right" tickFormatter={(v)=>fmt(v)} tick={{fill:C.faint,fontSize:10}} axisLine={false} tickLine={false} width={64}/>
                        <Tooltip cursor={{stroke:C.line}} contentStyle={{background:C.surface2, border:`1px solid ${C.line}`, borderRadius:8, fontSize:11, color:C.ink}} labelFormatter={(v)=> new Date(v as number).toLocaleString()} formatter={(v:any)=> [fmt(v), t.price]}/>
                        <Line dataKey="c" stroke={C.ink} strokeOpacity={0.55} strokeWidth={1.4} dot={false} isAnimationActive={false}/>
                        {/* an empty Scatter falls back to the chart data and marks every candle — render only non-empty sets */}
                        {marks.longIn.length > 0 && <Scatter data={marks.longIn} dataKey="c" fill={C.profit} shape="triangle" isAnimationActive={false}/>}
                        {marks.shortIn.length > 0 && <Scatter data={marks.shortIn} dataKey="c" fill={C.loss} shape="diamond" isAnimationActive={false}/>}
                        {marks.win.length > 0 && <Scatter data={marks.win} dataKey="c" fill={C.surface2} stroke={C.profit} isAnimationActive={false}/>}
                        {marks.lose.length > 0 && <Scatter data={marks.lose} dataKey="c" fill={C.surface2} stroke={C.loss} isAnimationActive={false}/>}
                      </ComposedChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              )}

              <div className="rounded-2xl border border-line bg-surface p-5">
                <div className="mb-3 flex items-center justify-between">
                  <h3 className="text-[17px] font-bold">{t.equity}</h3>
                  <span className="font-mono text-[11px] text-muted">{t.equitySub}</span>
                </div>
                <div className="h-[200px]" dir="ltr">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={equity} margin={{top:8, right:8, left:0, bottom:0}}>
                      <defs>
                        <linearGradient id="eq" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor={s.pnl>=0 ? C.corona : C.loss} stopOpacity={0.35}/>
                          <stop offset="100%" stopColor={s.pnl>=0 ? C.corona : C.loss} stopOpacity={0}/>
                        </linearGradient>
                      </defs>
                      <CartesianGrid stroke={C.line} vertical={false}/>
                      <XAxis dataKey="i" tick={{fill:C.faint,fontSize:10}} axisLine={false} tickLine={false} allowDecimals={false}/>
                      <YAxis orientation="right" tickFormatter={(v)=>fmt(v,0)} tick={{fill:C.faint,fontSize:10}} axisLine={false} tickLine={false} width={48}/>
                      <Tooltip contentStyle={{background:C.surface2, border:`1px solid ${C.line}`, borderRadius:8, fontSize:11, color:C.ink}} labelFormatter={(v)=> t.afterTrade(v)} formatter={(v:any)=> [signed(v), t.balance]}/>
                      <ReferenceLine y={0} stroke={C.faint} strokeDasharray="3 3"/>
                      <Area dataKey="v" type="monotone" stroke={s.pnl>=0 ? C.corona : C.loss} strokeWidth={2} fill="url(#eq)" isAnimationActive={false}/>
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </div>

              {yearly.length > 1 && (
                <Card>
                  <CardHeader title={t.yearly} sub={t.yearlySub}/>
                  <div className="grid gap-2" style={{ gridTemplateColumns: `repeat(${Math.min(yearly.length, 8)}, minmax(0, 1fr))` }}>
                    {yearly.map(([y, v]) => (
                      <div key={y} className={`rounded-xl px-2 py-2.5 text-center ${v >= 0 ? "bg-profit/10" : "bg-loss/10"}`}>
                        <div className={`font-mono text-[15px] font-medium tabular ${v >= 0 ? "text-profit" : "text-loss"}`} dir="ltr">{signed(v)}</div>
                        <div className="text-[12px] text-muted">{y}</div>
                      </div>
                    ))}
                  </div>
                </Card>
              )}

              {chartFile && (
                <div className="rounded-2xl border border-line bg-surface p-5">
                  <h3 className="mb-3 text-base font-bold">{t.serverChart}</h3>
                  {chartSrc === "failed" ? <div className="py-8 text-center text-xs text-faint">{t.chartFailed}</div> : chartSrc ? <img key={chartKey} src={chartSrc} alt={t.chartAlt} className="w-full rounded-xl border border-line"/> : <div className="py-8 text-center text-xs text-faint">{t.chartLoading}</div>}
                </div>
              )}

              <div className="grid gap-3 md:grid-cols-2">
                {ranStrategies.map(st=>(
                  <div key={st.id} className="rounded-2xl border border-line bg-surface p-4">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-bold">{en ? st.name : <>{st.nameAr} <span className="font-display font-medium text-muted">· {st.name}</span></>}</span>
                      <span className="font-mono text-[11px] text-muted"><span className={`font-bold ${pfTone(st.pf)}`}>PF {st.pf.toFixed(2)}</span> · WR {st.winRate}% · {t.inFull(st.trades)}</span>
                    </div>
                    <p className="mt-2 text-xs leading-6 text-muted">{t.method(st)}</p>
                  </div>
                ))}
              </div>

              <div className="overflow-hidden rounded-2xl border border-line bg-surface">
                <div className="flex items-center justify-between px-5 py-4">
                  <h3 className="text-[17px] font-bold">{t.trades}</h3>
                  <span className="font-mono text-[11px] text-muted">{t.nTradesShort(result.trades.length)}</span>
                </div>
                <div className="max-h-[420px] overflow-auto">
                  <table className="w-full min-w-[640px] text-[13px]">
                    <thead className="sticky top-0 bg-surface2 text-[11px] text-muted">
                      <tr>{[...(result.portfolio ? [t.coinHead] : []), ...t.head].map(h=> <th key={h} className="px-5 py-2.5 text-start font-semibold">{h}</th>)}</tr>
                    </thead>
                    <tbody>
                      {result.trades.length===0 ? (
                        <tr><td colSpan={result.portfolio ? 6 : 5} className="px-5 py-10 text-center text-sm text-faint">{t.noTrades}</td></tr>
                      ) : [...result.trades].reverse().map((tr,i)=>(
                        <tr key={i} className="border-t border-line">
                          {result.portfolio && <td className="px-5 py-3 font-bold" dir="ltr" style={align}>{tr.symbol}</td>}
                          <td className="px-5 py-3"><span className={`rounded-md px-1.5 py-0.5 font-mono text-[10px] font-bold ${tr.side==="long" ? "bg-profit/10 text-profit" : tr.side==="pair" ? "bg-corona/10 text-corona" : "bg-loss/10 text-loss"}`}>{tr.side==="long" ? "LONG" : tr.side==="pair" ? "LONG/SHORT" : "SHORT"}</span></td>
                          <td className="px-5 py-3 font-mono tabular" dir="ltr" style={align}>{tr.side==="pair" ? "" : fmt(tr.entry)} <span className="text-[11px] text-faint">{shortTs(tr.entry_ts)}</span></td>
                          <td className="px-5 py-3 font-mono tabular" dir="ltr" style={align}>{tr.side==="pair" ? "" : fmt(tr.exit)} <span className="text-[11px] text-faint">{shortTs(tr.exit_ts)}</span></td>
                          <td className="px-5 py-3 text-muted">{t.reasons[tr.reason] || tr.reason}</td>
                          <td className={`px-5 py-3 font-mono font-bold tabular ${tr.pnl>=0 ? "text-profit" : "text-loss"}`} dir="ltr" style={align}>{signed(tr.pnl)}</td>
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
              <summary className="cursor-pointer font-semibold">{t.tech}</summary>
              <pre className="mt-3 max-h-[240px] overflow-auto whitespace-pre-wrap font-mono text-[11px]" dir="ltr">{stdout.slice(-4000)}</pre>
            </details>
          )}
        </section>
      </div>
    </AppShell>
  )
}
