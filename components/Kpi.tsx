"use client"
import { Pill } from "@/components/ui"

export function Sparkline({ values, color, w = 110, h = 30 }: { values: number[], color: string, w?: number, h?: number }){
  const vals = values.length >= 2 ? values : [0, 0]
  const mn = Math.min(...vals), mx = Math.max(...vals)
  const pts = vals.map((v, i) => `${(i / (vals.length - 1) * w).toFixed(1)},${(h - 3 - (v - mn) / ((mx - mn) || 1) * (h - 6)).toFixed(1)}`)
  return <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} className="shrink-0"><polyline points={pts.join(" ")} fill="none" stroke={color} strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round"/></svg>
}

/** Stat card (Figma StatCard): label, the number, one line of context. */
export function Kpi({ label, value, chip, tone, sub, spark }: { label: string, value: string, chip?: string, tone: "profit"|"loss"|"neutral", sub: string, spark?: number[] }){
  return (
    <div className="min-w-0 rounded-2xl border border-line bg-surface px-5 py-[18px]">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-[13px] text-muted">{label}</span>
        {chip && <Pill tone={tone === "neutral" ? "neutral" : tone}><span className="font-mono tabular">{chip}</span></Pill>}
      </div>
      <div className={`mt-1.5 truncate font-mono text-[22px] font-bold leading-tight tabular sm:text-[26px] ${tone==="loss" ? "text-loss" : tone==="profit" ? "text-profit" : "text-ink"}`} dir="ltr" style={{textAlign:"right"}}>{value}</div>
      <div className="mt-1.5 flex items-center justify-between gap-2">
        <span className="text-[12px] text-faint">{sub}</span>
        {spark && spark.length >= 2 && <Sparkline values={spark} color={tone==="loss" ? "#FF5470" : "#F5B841"}/>}
      </div>
    </div>
  )
}
