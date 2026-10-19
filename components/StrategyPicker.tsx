"use client"
import { Lock } from "lucide-react"
import { STRATEGIES, TIERS, pfTone } from "@/lib/strategies"

// A plan unlocks the first `count` strategies (same rule as the backend's TIER_STRATEGY_COUNT)
function unlockTier(index: number){
  return TIERS.find(t => t.count > index)?.name || "Elite"
}

export function StrategyPicker({ selected, onToggle, tier }: { selected: string[], onToggle: (id:string)=>void, tier: string }){
  const maxCount = TIERS.find(t => t.id === tier)?.count ?? 2
  return (
    <div className="space-y-1.5">
      {STRATEGIES.map((s,i)=>{
        const locked = i >= maxCount
        const active = selected.includes(s.id)
        return (
          <button
            key={s.id}
            disabled={locked}
            onClick={()=>!locked && onToggle(s.id)}
            aria-pressed={active}
            className={`w-full flex items-center justify-between gap-3 rounded-xl px-3.5 py-2.5 text-right transition ${locked ? "border border-line/70 opacity-60 cursor-not-allowed" : active ? "bg-surface2 ring-1 ring-corona/25" : "border border-line hover:bg-surface2/60"}`}
          >
            <div className="min-w-0">
              <div className={`text-sm font-bold truncate ${active ? "text-ink" : "text-ink/80"}`}>{s.nameAr}</div>
              <div className="font-mono text-[11px] text-muted tabular">
                <span className={`font-bold ${pfTone(s.pf)}`}>PF {s.pf.toFixed(2)}</span>
                <span className="mx-1.5 text-faint">·</span>WR {s.winRate}%<span className="mx-1.5 text-faint">·</span>{s.setsWon}/8
              </div>
            </div>
            {locked ? (
              <span className="flex shrink-0 items-center gap-1 rounded-full bg-corona/10 px-2 py-0.5 text-[10px] font-bold text-corona"><Lock size={11}/> {unlockTier(i)}</span>
            ) : (
              <span className={`relative h-5 w-9 shrink-0 rounded-full transition ${active ? "bg-corona" : "bg-line"}`} dir="ltr">
                <span className={`absolute top-0.5 h-4 w-4 rounded-full transition-all ${active ? "left-[18px] bg-void" : "left-0.5 bg-muted"}`}/>
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}
