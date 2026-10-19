"use client"
import { useEffect, useState } from "react"
import { apiKlines } from "@/lib/api"
import { STRATEGIES } from "@/lib/strategies"

/** Landing hero card: live BTC price + 48h chart, and the top strategies by the site's own backtest stats. */
export function HeroPreview(){
  const [closes, setCloses] = useState<number[]>([])
  useEffect(()=>{
    const load = ()=> apiKlines("BTC/USDT", "1h", 48).then(k=> Array.isArray(k) && k.length && setCloses(k.map((c:any)=> +c.close))).catch(()=>{})
    load(); const t = setInterval(load, 60000); return ()=> clearInterval(t)
  }, [])
  const last = closes[closes.length-1], first = closes[0]
  const change = last && first ? (last - first) / first * 100 : 0
  const up = change >= 0
  const w = 420, h = 120
  const mn = Math.min(...closes), mx = Math.max(...closes)
  const pts = closes.map((v, i)=> `${(i / Math.max(1, closes.length-1) * w).toFixed(1)},${(h - 6 - (v - mn) / ((mx - mn) || 1) * (h - 12)).toFixed(1)}`)
  const top = [...STRATEGIES].sort((a,b)=> b.winRate - a.winRate).slice(0, 3)

  return (
    <div className="relative rounded-3xl border border-line bg-surface p-5 shadow-[0_30px_80px_-30px_rgba(245,184,65,0.25)]">
      <div className="flex items-start justify-between gap-3" dir="ltr">
        <div>
          <div className="font-display text-sm font-bold text-muted">BTC/USDT</div>
          <div className="mt-1 font-mono text-[28px] font-bold leading-none tabular">{last ? last.toLocaleString("en-US",{maximumFractionDigits:2}) : "—"}</div>
        </div>
        <div className="text-right">
          <span className={`rounded-md px-2 py-0.5 font-mono text-xs font-bold ${up ? "bg-profit/10 text-profit" : "bg-loss/10 text-loss"}`}>{closes.length ? `${up?"▲":"▼"} ${Math.abs(change).toFixed(2)}%` : "…"}</span>
          <div className="mt-1.5 flex items-center justify-end gap-1.5 font-mono text-[10px] text-faint"><i className="h-1.5 w-1.5 animate-pulse rounded-full bg-profit"/> LIVE · 48H</div>
        </div>
      </div>
      <svg viewBox={`0 0 ${w} ${h}`} className="mt-4 h-[120px] w-full" preserveAspectRatio="none" aria-hidden="true">
        <defs>
          <linearGradient id="hero-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#F5B841" stopOpacity="0.28"/><stop offset="100%" stopColor="#F5B841" stopOpacity="0"/>
          </linearGradient>
        </defs>
        {closes.length > 1 && <>
          <polygon points={`0,${h} ${pts.join(" ")} ${w},${h}`} fill="url(#hero-fill)"/>
          <polyline points={pts.join(" ")} fill="none" stroke="#F5B841" strokeWidth="2" strokeLinejoin="round" vectorEffect="non-scaling-stroke"/>
        </>}
      </svg>
      <div className="mt-4 border-t border-line pt-4">
        <div className="mb-3 flex items-center justify-between text-xs">
          <span className="font-bold">أعلى نسبة فوز</span>
          <span className="font-mono text-faint">Backtest · BTC 4h</span>
        </div>
        <div className="space-y-2.5">
          {top.map(s=>(
            <div key={s.id} className="flex items-center gap-3">
              <span className="w-28 shrink-0 truncate text-sm font-semibold">{s.nameAr}</span>
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-line" dir="ltr"><div className="h-full rounded-full bg-gradient-to-r from-umbra to-corona" style={{width: `${s.winRate}%`}}/></div>
              <span className="w-10 shrink-0 text-left font-mono text-xs font-bold text-profit">{s.winRate}%</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
