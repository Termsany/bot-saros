"use client"
import { Lock } from "lucide-react"
import { Pill } from "@/components/ui"
import { STRATEGIES, TIERS, minCapitalNote, pfTone, sharpeTone, unlockTier } from "@/lib/strategies"

/** The bot strategies with their tested numbers; locked ones show the plan that unlocks them. */
export function StrategyCards({ tier }: { tier: string }){
  const maxCount = TIERS.find(t => t.id === tier)?.count ?? 1
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {STRATEGIES.map((s, i) => {
        const locked = i >= maxCount
        return (
          <div key={s.id} className={`flex flex-col rounded-2xl border bg-surface2/40 p-4 ${locked ? "border-line/70 opacity-60" : s.risk === "high" ? "border-loss/35" : "border-line"}`}>
            <div className="flex items-start justify-between gap-2">
              <span className="text-[15px] font-bold leading-snug">{s.nameAr}</span>
              {locked ? <Pill tone="corona"><Lock size={11}/> {unlockTier(i).name}</Pill>
                : s.risk === "high" ? <Pill tone="loss">خطورة عالية</Pill> : <Pill>{s.sides}</Pill>}
            </div>
            <p className="mt-1.5 flex-1 text-[13px] leading-6 text-muted">{s.desc}</p>
            <div className="mt-3 grid grid-cols-3 gap-2 border-t border-line pt-3 text-center">
              <div title={minCapitalNote(s)}><div className="font-mono text-sm font-bold text-corona tabular" dir="ltr">${s.minCapital.toLocaleString("en-US")}</div><div className="text-[11px] text-faint">أقل رأس مال</div></div>
              <div><div className={`font-mono text-sm font-bold tabular ${pfTone(s.pf)}`}>{s.pf.toFixed(2)}</div><div className="text-[11px] text-faint">PF</div></div>
              <div><div className={`font-mono text-sm font-bold tabular ${sharpeTone(s.sharpeOut)}`}>{s.sharpeOut.toFixed(2)}</div><div className="text-[11px] text-faint">Sharpe 2024+</div></div>
            </div>
          </div>
        )
      })}
    </div>
  )
}
