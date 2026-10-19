"use client"

export function Sparkline({ values, color, w = 110, h = 30 }: { values: number[], color: string, w?: number, h?: number }){
  const vals = values.length >= 2 ? values : [0, 0]
  const mn = Math.min(...vals), mx = Math.max(...vals)
  const pts = vals.map((v, i) => `${(i / (vals.length - 1) * w).toFixed(1)},${(h - 3 - (v - mn) / ((mx - mn) || 1) * (h - 6)).toFixed(1)}`)
  return <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} className="shrink-0"><polyline points={pts.join(" ")} fill="none" stroke={color} strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round"/></svg>
}

/** Stat card used on the dashboard and backtest report. */
export function Kpi({ label, value, chip, tone, sub, spark }: { label: string, value: string, chip?: string, tone: "profit"|"loss"|"neutral", sub: string, spark?: number[] }){
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
        {spark && spark.length >= 2 && <Sparkline values={spark} color={tone==="loss" ? "#FF5470" : "#F5B841"}/>}
      </div>
    </div>
  )
}
