"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { Logo } from "@/components/Logo"
import { BarChart3, Clock3, Crosshair, RefreshCw, Wifi, Activity } from "lucide-react"
import { StrategyPicker } from "@/components/StrategyPicker"
import { PaperWallet } from "@/components/PaperWallet"
import { PAIRS, NAMES } from "@/lib/pairs"
import { apiTrades, apiKlines } from "@/lib/api"

const GREEN = "#00D395"
const RED = "#FF3B5C"

type Candle = { time: number; open: number; high: number; low: number; close: number; volume: number }
type Trade = { id:number; symbol:string; side:string; entry:number; exit:number|null; qty:number; pnl:number|null; status:string; sl:number; tp:number; at:string }

function formatPrice(v: number){ return v > 1000 ? v.toLocaleString(undefined,{maximumFractionDigits:2}) : v.toFixed(2) }

function CandleTooltip({ active, payload }: any){
  if(!active || !payload?.[0]) return null
  const c = payload[0].payload
  return (
    <div className="rounded border border-[#26303c] bg-[#111923] px-3 py-2 text-[11px] shadow-xl">
      <div className="mb-1 font-mono text-[#8491a3]">{new Date(c.time).toLocaleString()}</div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 font-mono"><span>O {formatPrice(c.open)}</span><span>H {formatPrice(c.high)}</span><span>L {formatPrice(c.low)}</span><span>C {formatPrice(c.close)}</span></div>
    </div>
  )
}

export default function Dashboard(){
  // Strategy + pair state (our logic)
  const [tier, setTier] = useState("elite")
  const [selected, setSelected] = useState<string[]>(["ict"])
  const [symbol, setSymbol] = useState("BTC/USDT")
  const [tf, setTf] = useState("4h")
  const toggle = (id:string)=> setSelected(s=> s.includes(id) ? s.filter(x=>x!==id) : [...s, id])

  // Chart state (v0 style)
  const [candles, setCandles] = useState<Candle[]>([])
  const [loading, setLoading] = useState(true)
  const [lastUpdated, setLastUpdated] = useState<Date|null>(null)

  // Trades state (our backend)
  const [trades, setTrades] = useState<Trade[]>([])
  const [stats, setStats] = useState({ pnl:0, wins:0, losses:0, total:0, pf:0 })

  const binanceSymbol = symbol.replace("/","")
  const binanceInterval = tf

  const loadKlines = useCallback(async()=>{
    setLoading(true)
    try{
      const kl = await apiKlines(symbol, binanceInterval, 200)
      if(Array.isArray(kl) && kl.length){
        // kl is {time, open, high, low, close}[] — time is seconds
        const fmt: Candle[] = kl.map((k:any)=> ({
          time: (k.time * 1000) as number,  // recharts expects ms
          open: +k.open, high: +k.high, low: +k.low, close: +k.close, volume: (k.volume||0) as number
        }))
        setCandles(fmt)
        setLastUpdated(new Date())
      } else {
        // direct Binance fallback
        const r = await fetch(`https://api.binance.com/api/v3/klines?symbol=${binanceSymbol}&interval=${binanceInterval}&limit=200`, { cache: "no-store" })
        if(r.ok){
          const rows = await r.json()
          setCandles(rows.map((row:any)=> ({ time: Number(row[0]), open:Number(row[1]), high:Number(row[2]), low:Number(row[3]), close:Number(row[4]), volume:Number(row[5]) })))
          setLastUpdated(new Date())
        }
      }
    }catch{ setCandles([]) }
    finally{ setLoading(false) }
  }, [symbol, binanceInterval, binanceSymbol])

  const loadTrades = useCallback(async()=>{
    try{
      const tr = await apiTrades(50)
      const list: Trade[] = Array.isArray(tr) ? tr : []
      setTrades(list)
      const wins = list.filter(t=> (t.pnl||0)>0).length
      const losses = list.filter(t=> (t.pnl||0)<0).length
      const pnl = list.reduce((s,t)=> s+(t.pnl||0), 0)
      const sumWin = list.filter(t=> (t.pnl||0)>0).reduce((s,t)=> s+(t.pnl||0),0)
      const sumLoss = Math.abs(list.filter(t=> (t.pnl||0)<0).reduce((s,t)=> s+(t.pnl||0),0))
      const pf = sumLoss ? sumWin/sumLoss : sumWin ? 99 : 0
      setStats({ pnl, wins, losses, total: list.length, pf })
    }catch{}
  }, [])

  useEffect(()=>{ loadKlines(); const t=setInterval(loadKlines, 30000); return ()=>clearInterval(t) }, [loadKlines])
  useEffect(()=>{ loadTrades(); const t=setInterval(loadTrades, 30000); return ()=>clearInterval(t) }, [loadTrades])

  const current = candles[candles.length-1]
  const previous = candles[candles.length-2]
  const change = current && previous ? ((current.close - previous.close)/previous.close)*100 : 0
  const chartData = useMemo(()=> candles.map(c=> ({ ...c, body:[Math.min(c.open,c.close), Math.max(c.open,c.close)], wick:[c.low,c.high], direction: c.close>=c.open ? "up":"down" })), [candles])
  const avgVolume = candles.length ? candles.reduce((s,c)=> s+c.volume,0)/candles.length : 0
  const openTrades = trades.filter(t=> t.status==="open" || !t.exit)
  const closedTrades = trades.filter(t=> t.status==="closed" || t.exit)

  return (
    <main className="min-h-screen bg-[#070B12] text-[#E8EEF5]">
      <header className="flex h-16 items-center justify-between border-b border-[#1c2632] bg-[#0a1018] px-5 lg:px-8">
        <Logo />
        <div className="hidden items-center gap-4 md:flex">
          <span className="flex items-center gap-2 text-[11px] text-[#00D395]"><Wifi size={13}/> BINANCE SPOT <i className="h-1.5 w-1.5 rounded-full bg-[#00D395] animate-pulse"/></span>
          <span className="font-mono text-[11px] text-[#778597]">UTC {new Date().toISOString().slice(11,19)}</span>
          <a href="/" className="text-[11px] text-[#778597] hover:text-white">الرئيسية</a>
          <a href="/backtest" className="text-[11px] text-[#778597] hover:text-white">Backtest</a>
        </div>
      </header>

      <div className="mx-auto max-w-[1600px] space-y-5 p-4 lg:p-7">
        {/* KPIs — v0 style + real data */}
        <section className="grid grid-cols-2 gap-3 md:grid-cols-5">
          <div className={`rounded border p-4 ${stats.pnl>=0?"border-[#00D395]/30 bg-[#0c131c]":"border-[#FF3B5C]/30 bg-[#0c131c]"}`}>
            <div className="text-[10px] tracking-[0.14em] text-[#68778a]">TOTAL PnL</div>
            <div className={`mt-2 font-mono text-xl font-semibold tracking-tight ${stats.pnl>=0?"text-[#00D395]":"text-[#FF3B5C]"}`}>{stats.pnl>=0?"+":""}{stats.pnl.toFixed(2)} USDT</div>
            <div className="mt-1 font-mono text-[10px] text-[#68778a]">{stats.total} صفقات</div>
          </div>
          <div className="rounded border border-[#1c2632] bg-[#0c131c] p-4">
            <div className="text-[10px] tracking-[0.14em] text-[#68778a]">WIN RATE</div>
            <div className={`mt-2 font-mono text-xl font-semibold ${stats.total ? (stats.wins/stats.total*100>=50?"text-[#00D395]":"text-[#FFB800]") : "text-white"}`}>{stats.total ? (stats.wins/stats.total*100).toFixed(1):"—"}%</div>
            <div className="mt-1 font-mono text-[10px] text-[#68778a]">{stats.wins}W / {stats.losses}L</div>
          </div>
          <div className="rounded border border-[#1c2632] bg-[#0c131c] p-4">
            <div className="text-[10px] tracking-[0.14em] text-[#68778a]">PROFIT FACTOR</div>
            <div className="mt-2 font-mono text-xl font-semibold">{stats.pf ? stats.pf.toFixed(2) : "—"}</div>
            <div className="mt-1 font-mono text-[10px] text-[#68778a]">{stats.pf>=1.5?"ممتاز":stats.pf>=1?"جيد":"ضعيف"}</div>
          </div>
          <div className="rounded border border-[#1c2632] bg-[#0c131c] p-4">
            <div className="text-[10px] tracking-[0.14em] text-[#68778a]">مفتوحة</div>
            <div className="mt-2 font-mono text-xl font-semibold text-[#8B9AFF]">{openTrades.length.toString().padStart(2,"0")}</div>
            <div className="mt-1 font-mono text-[10px] text-[#68778a]">{openTrades.length ? openTrades.map(t=>t.side.toUpperCase()).join(" · ") : "لا يوجد"}</div>
          </div>
          <div className="rounded border border-[#1c2632] bg-[#0c131c] p-4">
            <div className="text-[10px] tracking-[0.14em] text-[#68778a]">مقفولة</div>
            <div className="mt-2 font-mono text-xl font-semibold">{closedTrades.length.toString().padStart(2,"0")}</div>
            <div className="mt-1 font-mono text-[10px] text-[#68778a]">{closedTrades.length ? `${closedTrades.filter(t=>(t.pnl||0)>0).length} رابحة` : "—"}</div>
          </div>
        </section>

        <div className="grid gap-5 lg:grid-cols-[320px_minmax(0,1fr)]">
          {/* Strategy picker — keep our 15 */}
          <aside className="rounded border border-[#1c2632] bg-[#0c131c] p-4 h-fit">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-xs font-semibold tracking-[0.14em]">اختر الاستراتيجيات ({selected.length})</h2>
              <select value={tier} onChange={e=>setTier(e.target.value)} className="bg-[#0a1018] border border-[#1d2936] rounded px-2 py-1 text-[10px] font-mono">
                <option value="free">Free</option><option value="starter">Starter</option><option value="pro">Pro</option><option value="elite">Elite</option>
              </select>
            </div>
            <div className="flex gap-1.5 mb-3">
              <select value={symbol} onChange={e=>setSymbol(e.target.value)} className="flex-1 bg-[#0a1018] border border-[#1d2936] rounded px-2 py-1.5 text-xs">
                {PAIRS.map(p=><option key={p} value={p}>{NAMES[p]||p}</option>)}
              </select>
              <select value={tf} onChange={e=>setTf(e.target.value)} className="bg-[#0a1018] border border-[#1d2936] rounded px-2 py-1.5 text-xs">
                <option value="15m">15m</option><option value="1h">1h</option><option value="4h">4h</option><option value="1d">1d</option>
              </select>
            </div>
            <StrategyPicker selected={selected} onToggle={toggle} tier={tier}/>
            <div className="mt-4"><PaperWallet/></div>
            {tier!=="elite" && selected.some(s=>["smc","vwap","supertrend","bollinger","harmonic","ict","heikin","ai"].includes(s)) && (
              <div className="mt-3 text-[11px] text-[#FFB800] bg-[#2a2506] border border-[#4a3a00] rounded-xl px-3 py-2">⚠️ للباقة Elite — <a href="/#pricing" className="underline">حدّث</a></div>
            )}
            <div className="mt-4 border-t border-[#1c2632] pt-3">
              <div className="text-[10px] tracking-[0.14em] text-[#718095] mb-2">الصفقات</div>
              {openTrades.length===0 ? <div className="text-[11px] text-[#647386] text-center py-2">لا صفقات مفتوحة</div> :
                openTrades.map(t=>(
                  <div key={t.id} className="rounded border border-[#1d2936] bg-[#0a1018] p-2 text-xs mb-1.5">
                    <div className="flex justify-between"><span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${t.side==="long"?"bg-[#00D395]/20 text-[#00D395]":"bg-[#FF3B5C]/20 text-[#FF3B5C]"}`}>{t.side.toUpperCase()}</span><span className="font-mono text-[11px]">{t.symbol}</span></div>
                    <div className="mt-1 font-mono text-[11px] flex justify-between"><span>{Number(t.entry).toFixed(2)}</span><span className="text-[#647386]">SL {Number(t.sl).toFixed(0)} TP {Number(t.tp).toFixed(0)}</span></div>
                  </div>
                ))}
              {closedTrades.length>0 && (
                <div className="mt-3">
                  <div className="text-[10px] text-[#647386] mb-1">آخر المقفولة</div>
                  {closedTrades.slice(-5).reverse().map(t=>(
                    <div key={t.id} className="flex justify-between text-[11px] font-mono border-t border-[#1c2632] py-1"><span>{t.symbol}</span><span className={(t.pnl||0)>=0?"text-[#00D395]":"text-[#FF3B5C]"}>{(t.pnl||0)>=0?"+":""}{(t.pnl||0).toFixed(2)}</span></div>
                  ))}
                </div>
              )}
            </div>
          </aside>

          {/* Chart — v0 Recharts style */}
          <section className="min-w-0 rounded border border-[#1c2632] bg-[#0c131c]">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#1c2632] px-4 py-3">
              <div className="flex items-center gap-3">
                <span className="text-sm font-semibold">{symbol.replace("/"," / ")}</span>
                <span className="font-mono text-xs" style={{color: change>=0 ? GREEN : RED}}>{current ? `${formatPrice(current.close)}  ${change>=0?"+":""}${change.toFixed(2)}%` : "—"}</span>
              </div>
              <div className="flex items-center gap-1 text-[10px] font-mono text-[#728095]">
                {["15m","1h","4h","1d"].map(item=>(
                  <button key={item} onClick={()=>setTf(item)} className={`rounded px-2.5 py-1.5 ${tf===item?"bg-[#1b2b35] text-[#00D395]":"hover:text-white"}`}>{item}</button>
                ))}
                <button onClick={loadKlines} className="ml-1 rounded p-1.5 hover:bg-[#1b2b35]" aria-label="refresh"><RefreshCw size={14} className={loading?"animate-spin":""}/></button>
              </div>
            </div>
            <div className="flex items-center gap-5 px-4 py-2 text-[10px] font-mono text-[#67768a]">
              <span className="flex items-center gap-1"><BarChart3 size={12}/> CANDLES 200</span>
              <span className="flex items-center gap-1"><Clock3 size={12}/> 30s</span>
              <span className="hidden sm:flex items-center gap-1"><Crosshair size={12}/> BINANCE</span>
              <span className="ml-auto">{lastUpdated ? `UPDATED ${lastUpdated.toLocaleTimeString()}` : "CONNECTING..."}</span>
            </div>
            <div className="h-[460px] w-full px-2 pb-3">
              {loading && !candles.length ? <div className="flex h-full items-center justify-center font-mono text-xs text-[#647386]">FETCHING BINANCE KLINES...</div>
              : !candles.length ? <div className="flex h-full items-center justify-center font-mono text-xs text-[#FF3B5C]">BINANCE DATA UNAVAILABLE</div>
              : (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData} margin={{top:12, right:55, left:5, bottom:5}} barCategoryGap="12%">
                    <CartesianGrid stroke="#1b2631" strokeDasharray="2 4" vertical={false}/>
                    <XAxis dataKey="time" tickFormatter={(v)=> new Date(v).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"})} tick={{fill:"#607084",fontSize:10}} axisLine={false} tickLine={false} minTickGap={55}/>
                    <YAxis domain={["auto","auto"]} orientation="right" tickFormatter={formatPrice} tick={{fill:"#607084",fontSize:10}} axisLine={false} tickLine={false} width={52}/>
                    <Tooltip content={<CandleTooltip/> as any}/>
                    <ReferenceLine y={current?.close} stroke="#718095" strokeDasharray="3 3"/>
                    <Bar dataKey="body" barSize={6} isAnimationActive={false}>
                      {chartData.map((entry:any)=> <Cell key={entry.time} fill={entry.direction==="up" ? GREEN : RED}/>)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>
          </section>
        </div>

        <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-[#1c2632] pt-4 font-mono text-[10px] text-[#5f6e81]">
          <span>ENGINE STATUS <b className="text-[#00D395]">● OPERATIONAL</b></span>
          <span>AVG VOLUME {avgVolume ? `${(avgVolume/1000).toFixed(1)}K` : "—"} BTC</span>
          <span>Bot Saros © 2026 — 15 استراتيجية + Backtest + Futures LONG/SHORT</span>
        </footer>
      </div>
    </main>
  )
}
