"use client"
import { useState, useEffect, useCallback } from "react"
import { StrategyPicker } from "@/components/StrategyPicker"
import { LiveTicker } from "@/components/LiveTicker"
import { TradingChart } from "@/components/TradingChart"
import { PAIRS, NAMES } from "@/lib/pairs"
import { apiTrades, apiKlines } from "@/lib/api"

type Trade = { id:number; symbol:string; side:string; entry:number; exit:number|null; qty:number; pnl:number|null; status:string; sl:number; tp:number; at:string }

export default function Dashboard(){
  const [tier, setTier] = useState("elite")
  const [selected, setSelected] = useState<string[]>(["ict"])
  const [symbol, setSymbol] = useState("BTC/USDT")
  const [tf, setTf] = useState("4h")
  const [trades, setTrades] = useState<Trade[]>([])
  const [candles, setCandles] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [stats, setStats] = useState({ pnl:0, wins:0, losses:0, total:0, pf:0 })

  function toggle(id:string){ setSelected(s=> s.includes(id) ? s.filter(x=>x!==id) : [...s, id]) }

  const load = useCallback(async()=>{
    try{
      const [tr, kl] = await Promise.all([
        apiTrades(50),
        apiKlines(symbol, tf, 200),
      ])
      const list: Trade[] = Array.isArray(tr) ? tr : []
      setTrades(list)
      // stats
      const wins = list.filter(t=> (t.pnl||0) > 0).length
      const losses = list.filter(t=> (t.pnl||0) < 0).length
      const pnl = list.reduce((s,t)=> s + (t.pnl||0), 0)
      const sumWin = list.filter(t=> (t.pnl||0)>0).reduce((s,t)=> s+(t.pnl||0),0)
      const sumLoss = Math.abs(list.filter(t=> (t.pnl||0)<0).reduce((s,t)=> s+(t.pnl||0),0))
      const pf = sumLoss ? sumWin/sumLoss : sumWin ? 99 : 0
      setStats({ pnl, wins, losses, total: list.length, pf })
      // candles: kl may be already formatted or raw
      if(Array.isArray(kl) && kl.length){
        // if kl is from backend /api/klines it may be raw binance format
        const fmt = kl[0]?.open !== undefined ? kl : kl.map((k:any)=> ({ time: Math.floor(k[0]/1000), open:+k[1], high:+k[2], low:+k[3], close:+k[4] }))
        setCandles(fmt)
      }
    }catch(e){ console.log(e) }
    setLoading(false)
  }, [symbol, tf])

  useEffect(()=>{ load(); const id=setInterval(load, 30000); return ()=>clearInterval(id) }, [load])

  const openTrades = trades.filter(t=> t.status==="open" || !t.exit)
  const closedTrades = trades.filter(t=> t.status==="closed" || t.exit)

  // markers for chart: entry/exit
  const markers = trades.slice(-6).flatMap(t=>{
    const entryTime = Math.floor(new Date(t.at).getTime()/1000)
    // find nearest candle
    const m:any[] = []
    m.push({ time: entryTime, position: (t.side==="long"?"belowBar":"aboveBar"), color: t.side==="long"?"#00D395":"#FF3B5C", shape: t.side==="long"?"arrowUp":"arrowDown" as const, text: `${t.side} ${t.entry?.toFixed(0)}` })
    if(t.exit) m.push({ time: Math.floor(new Date(t.at).getTime()/1000)+ 4*3600, position: t.side==="long"?"aboveBar":"belowBar" as const, color: (t.pnl||0)>=0?"#00D395":"#FF3B5C", shape: "circle" as const, text: `${(t.pnl||0)>=0?"+":""}${(t.pnl||0).toFixed(2)}` })
    return m
  })

  return (
    <div className="min-h-screen bg-[#070B12] text-[#E6EEF8]">
      <header className="sticky top-0 z-20 backdrop-blur bg-[#070B12]/80 border-b border-[#1E2A3A]">
        <div className="max-w-[1400px] mx-auto px-3 py-2 flex justify-between items-center gap-2 flex-wrap">
          <div className="flex items-center gap-2">
            <a href="/" className="w-7 h-7 rounded-lg bg-[#00D395] grid place-items-center font-black text-[#062016] text-xs">S</a>
            <span className="font-black text-sm">Bot Saros</span>
            <span className="text-[10px] px-1.5 py-0.5 rounded-full border border-[#1E2A3A]">FUTURES x5 Paper</span>
            <LiveTicker/>
          </div>
          <div className="flex items-center gap-1.5">
            <select value={tier} onChange={e=>setTier(e.target.value)} className="bg-[#0E141D] border border-[#1E2A3A] rounded-lg px-2 py-1 text-xs">
              <option value="free">Free</option><option value="starter">Starter</option><option value="pro">Pro</option><option value="elite">Elite</option>
            </select>
            <select value={symbol} onChange={e=>setSymbol(e.target.value)} className="bg-[#0E141D] border border-[#1E2A3A] rounded-lg px-2 py-1 text-xs">
              {PAIRS.map(p=><option key={p} value={p}>{NAMES[p]||p}</option>)}
            </select>
            <select value={tf} onChange={e=>setTf(e.target.value)} className="bg-[#0E141D] border border-[#1E2A3A] rounded-lg px-2 py-1 text-xs">
              <option value="15m">15m</option><option value="1h">1h</option><option value="4h">4h</option><option value="1d">1d</option>
            </select>
            <a href="/backtest" className="px-2.5 py-1 rounded-lg bg-[#1E2A3A] text-xs">Backtest</a>
          </div>
        </div>
      </header>

      {/* KPIs */}
      <div className="max-w-[1400px] mx-auto px-3 pt-3 grid grid-cols-2 md:grid-cols-5 gap-2">
        <div className={`rounded-xl border p-3 text-center ${stats.pnl>=0?"bg-[#0A1A14] border-[#00D395]/30":"bg-[#1A0F14] border-[#FF3B5C]/30"}`}>
          <div className="text-[10px] text-[#8A9AB0]">إجمالي PnL</div>
          <div className={`text-lg font-black ${stats.pnl>=0?"text-[#00D395]":"text-[#FF3B5C]"}`}>{stats.pnl>=0?"+":""}{stats.pnl.toFixed(2)} USDT</div>
          <div className="text-[10px] text-[#8A9AB0]">{stats.total} صفقة</div>
        </div>
        <div className="rounded-xl border border-[#1E2A3A] bg-[#111827] p-3 text-center">
          <div className="text-[10px] text-[#8A9AB0]">Win Rate</div>
          <div className={`text-lg font-black ${stats.total? (stats.wins/stats.total*100>=50?"text-[#00D395]":"text-[#FFB800]"):"text-white"}`}>{stats.total ? (stats.wins/stats.total*100).toFixed(1):"—"}%</div>
          <div className="text-[10px] text-[#8A9AB0]">{stats.wins}W / {stats.losses}L</div>
        </div>
        <div className="rounded-xl border border-[#1E2A3A] bg-[#111827] p-3 text-center">
          <div className="text-[10px] text-[#8A9AB0]">Profit Factor</div>
          <div className="text-lg font-black">{stats.pf ? stats.pf.toFixed(2) : "—"}</div>
          <div className="text-[10px] text-[#8A9AB0]">{stats.pf>=1.5?"ممتاز":stats.pf>=1?"جيد":"ضعيف"}</div>
        </div>
        <div className="rounded-xl border border-[#1E2A3A] bg-[#111827] p-3 text-center">
          <div className="text-[10px] text-[#8A9AB0]">مفتوحة</div>
          <div className="text-lg font-black text-[#60A5FA]">{openTrades.length}</div>
          <div className="text-[10px] text-[#8A9AB0]">صفقة</div>
        </div>
        <div className="rounded-xl border border-[#1E2A3A] bg-[#111827] p-3 text-center">
          <div className="text-[10px] text-[#8A9AB0]">مقفولة</div>
          <div className="text-lg font-black">{closedTrades.length}</div>
          <div className="text-[10px] text-[#8A9AB0]">صفقة</div>
        </div>
      </div>

      <div className="max-w-[1400px] mx-auto p-3 grid lg:grid-cols-[360px_1fr] gap-3">
        <div className="space-y-3">
          <div className="rounded-2xl border border-[#1E2A3A] bg-[#111827] p-3">
            <div className="text-xs font-bold mb-2">اختر الاستراتيجيات ({selected.length}) — باقة {tier}</div>
            <StrategyPicker selected={selected} onToggle={toggle} tier={tier}/>
            {tier!=="elite" && selected.some(s=>["smc","vwap","supertrend","bollinger","harmonic","ict","heikin","ai"].includes(s)) && (
              <div className="mt-2 text-[11px] text-[#FFB800] bg-[#2a2506] border border-[#4a3a00] rounded-xl px-3 py-2">⚠️ هذه الاستراتيجيات للباقة Elite — حدث من <a href="/#pricing" className="underline">الأسعار</a></div>
            )}
            <div className="text-[11px] text-[#8A9AB0] mt-3">الأمر: <code className="bg-[#0E141D] px-1 py-0.5 rounded">--strategies {selected.join(",")}</code></div>
          </div>
          <div className="rounded-2xl border border-[#1E2A3A] bg-[#111827] p-3">
            <div className="text-xs font-bold flex justify-between">الصفقات المفتوحة <span className="text-[#60A5FA]">{openTrades.length}</span></div>
            {openTrades.length===0 ? (
              <div className="text-xs text-[#8A9AB0] text-center py-4">لا يوجد — {loading ? "جاري التحميل..." : "البوت لم يفتح صفقات بعد"}</div>
            ) : openTrades.map(t=>(
              <div key={t.id} className="mt-2 rounded-xl border border-[#1E2A3A] bg-[#0E141D] p-2 text-xs">
                <div className="flex justify-between"><span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${t.side==="long"?"bg-[#0A2E1A] text-[#00D395]":"bg-[#2e0a14] text-[#FF3B5C]"}`}>{t.side.toUpperCase()}</span><span className="text-[#8A9AB0]">{t.symbol} x5</span></div>
                <div className="mt-1 flex justify-between"><span>دخول {Number(t.entry).toFixed(2)}</span><span className="text-[#8A9AB0]">SL {Number(t.sl).toFixed(2)} TP {Number(t.tp).toFixed(2)}</span></div>
              </div>
            ))}
          </div>
          <div className="rounded-2xl border border-[#1E2A3A] bg-[#111827] p-3">
            <div className="text-xs font-bold">آخر الصفقات المقفولة</div>
            {closedTrades.length===0 ? <div className="text-xs text-[#8A9AB0] text-center py-3">لا يوجد</div> : (
              <div className="space-y-1.5 mt-2 max-h-[300px] overflow-auto">
                {closedTrades.slice(-10).reverse().map(t=>(
                  <div key={t.id} className="flex justify-between text-xs border-t border-[#1E2A3A] pt-1.5">
                    <span className={t.side==="long"?"text-[#00D395]":"text-[#FF3B5C]"}>{t.side}</span>
                    <span>{t.symbol}</span>
                    <span className={(t.pnl||0)>=0?"text-[#00D395] font-bold":"text-[#FF3B5C] font-bold"}>{(t.pnl||0)>=0?"+":""}{(t.pnl||0).toFixed(2)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="space-y-3">
          <div className="rounded-2xl border border-[#1E2A3A] bg-[#111827] p-3">
            <div className="flex justify-between items-center">
              <span className="text-xs font-bold">الشارت — {NAMES[symbol]||symbol} {tf}</span>
              <span className="text-[11px] px-2 py-1 rounded-full bg-[#0A2E1A] text-[#00D395]">{candles.length} شمعة</span>
            </div>
            <div className="mt-2">
              <TradingChart candles={candles} markers={markers} height={380} />
            </div>
            <div className="text-[11px] text-[#8A9AB0] mt-2 text-center">يتحدث كل 30 ثانية من Binance + علامات دخول/خروج</div>
          </div>
          <div className="rounded-2xl border border-[#1E2A3A] bg-[#111827] p-3">
            <div className="text-xs font-bold">الـ 15 استراتيجية — ICT بطل BTC 4h</div>
            <div className="text-[11px] text-[#8A9AB0] mt-1">الداشبورد لايف — الباك تست من <a href="/backtest" className="text-[#00D395] underline">/backtest</a></div>
          </div>
        </div>
      </div>
    </div>
  )
}
