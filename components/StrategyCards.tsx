"use client"
import { Lock } from "lucide-react"
import { STRATEGIES, TIERS, minCapitalNote, pfTone, sharpeTone, unlockTier } from "@/lib/strategies"

/** The four bot strategies with their tested numbers; locked ones show the plan that unlocks them. */
export function StrategyCards({ tier }: { tier: string }){
  const maxCount = TIERS.find(t => t.id === tier)?.count ?? 1
  return (
    <div className="space-y-2">
      {STRATEGIES.map((s, i) => {
        const locked = i >= maxCount
        return (
          <div key={s.id} className={`rounded-xl border px-3.5 py-3 ${locked ? "border-line/70 opacity-60" : s.risk === "high" ? "border-loss/35" : "border-line"}`}>
            <div className="flex items-center justify-between gap-2">
              <div className="flex min-w-0 items-center gap-2">
                <span className="text-corona">{s.icon}</span>
                <span className="truncate text-sm font-bold">{s.nameAr}</span>
                {s.risk === "high" && <span className="shrink-0 rounded-full bg-loss/10 px-1.5 py-0.5 text-[10px] font-bold text-loss">HIGH RISK</span>}
              </div>
              {locked
                ? <span className="flex shrink-0 items-center gap-1 rounded-full bg-corona/10 px-2 py-0.5 text-[10px] font-bold text-corona"><Lock size={11}/> {unlockTier(i).name}</span>
                : <span className="shrink-0 text-[11px] text-muted">{s.sides}</span>}
            </div>
            <p className="mt-1 text-xs leading-5 text-muted">{s.desc}</p>
            <div className="mt-1.5 flex items-center justify-between gap-2 rounded-lg bg-surface2/60 px-2.5 py-1.5" title={minCapitalNote(s)}>
              <span className="text-[11px] text-muted">أقل رأس مال</span>
              <span className="font-mono text-sm font-bold text-corona" dir="ltr">${s.minCapital.toLocaleString("en-US")}</span>
            </div>
            <div className="mt-1.5 font-mono text-[11px] text-muted tabular" dir="ltr" style={{ textAlign: "right" }}>
              <span className={`font-bold ${pfTone(s.pf)}`}>PF {s.pf.toFixed(2)}</span>
              <span className="mx-1.5 text-faint">·</span>WR {s.winRate}%
              <span className="mx-1.5 text-faint">·</span>Sharpe <span className={`font-bold ${sharpeTone(s.sharpeOut)}`}>{s.sharpeOut.toFixed(2)}</span> (2024+)
            </div>
          </div>
        )
      })}
    </div>
  )
}
