"use client"
import { useEffect, useState } from "react"
import { apiKlines } from "@/lib/api"
import { BOT_PAGE } from "@/lib/strategies"
import { useLiveBots } from "@/lib/live-bots"

const money = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}$${Math.abs(v).toFixed(2)}`

/** Landing hero card: live BTC price + 48h chart, and the four paper bots live (bot.da3m.io data). */
export function HeroPreview(){
  const { bots, total, loaded } = useLiveBots(30_000)
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
          <span className="font-bold">البوتات شغالة دلوقتي</span>
          <span className="flex items-center gap-1.5 font-mono text-faint" dir="ltr"><i className="h-1.5 w-1.5 animate-pulse rounded-full bg-profit"/> {loaded ? `${total.running}/${bots.length} LIVE · PAPER` : "…"}</span>
        </div>
        <div className="space-y-2">
          {(loaded ? [...bots].sort((a, b) => b.open - a.open || Math.abs(b.realized + b.unrealized) - Math.abs(a.realized + a.unrealized)).slice(0, 3) : []).map(b=>{
            const t = b.realized + b.unrealized
            return (
              <div key={b.strategy.id} className="flex items-center justify-between gap-3 rounded-xl bg-surface2/60 px-3 py-2.5">
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5 truncate text-sm font-semibold">{b.strategy.nameAr}{b.strategy.risk === "high" && <span className="rounded-full border border-loss/40 bg-loss/10 px-1.5 text-[10px] font-semibold text-loss">خطورة عالية</span>}</div>
                  <div className="text-[11px] text-muted">{b.open ? `${b.open} مفتوحة` : "مفيش صفقات مفتوحة"}</div>
                </div>
                <span className={`shrink-0 font-mono text-[15px] font-medium ${t > 0 ? "text-profit" : t < 0 ? "text-loss" : "text-muted"}`} dir="ltr">{money(t)}</span>
              </div>
            )
          })}
          {!loaded && <div className="py-2 text-center text-xs text-faint">بيحمّل البوتات…</div>}
        </div>
        <p className="mt-3 text-[11px] leading-5 text-faint">فلوس وهمية، بتتحدث لوحدها. <a href={BOT_PAGE} target="_blank" rel="noopener" className="text-corona hover:underline">كل البوتات والصفقات مباشر ←</a></p>
      </div>
    </div>
  )
}
