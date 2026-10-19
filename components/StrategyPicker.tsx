"use client"
import { STRATEGIES, TIERS } from "@/lib/strategies"

export function StrategyPicker({ selected, onToggle, tier }: { selected: string[], onToggle: (id:string)=>void, tier: string }){
  const allowed = new Set(TIERS.find(t=>t.id===tier)?.features ? [] : [])
  // Map tier to allowed strategy ids
  const tierOrder = { free: 2, starter: 6, pro: 7, elite: 15 }
  // Simple: by index
  const maxCount = tierOrder[tier as keyof typeof tierOrder] ?? 2
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
      {STRATEGIES.map((s,i)=>{
        const locked = i >= maxCount
        const active = selected.includes(s.id)
        return (
          <button
            key={s.id}
            disabled={locked}
            onClick={()=>!locked && onToggle(s.id)}
            className={`text-right p-3 rounded-xl border text-sm transition ${locked ? "opacity-40 border-[#1E2A3A] bg-[#111827]" : active ? "border-[#00D395] bg-[#0A2E1A]" : "border-[#1E2A3A] bg-[#0E141D] hover:border-[#2a3a56]"}`}
          >
            <div className="flex justify-between items-center">
              <span className="text-xs px-1.5 py-0.5 rounded bg-[#1E2A3A]">{s.icon}</span>
              {locked && <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#2a2506] text-[#FFB800]">Elite</span>}
              {!locked && active && <span className="text-[10px] text-[#00D395]">✓</span>}
            </div>
            <div className="font-bold mt-1 text-xs">{s.nameAr}</div>
            <div className="text-[11px] text-[#8A9AB0]">{s.desc}</div>
            <div className="flex gap-2 mt-1 text-[10px]">
              <span className={s.winRate>=45 ? "text-[#00D395]" : s.winRate>=35 ? "text-[#FFB800]" : "text-[#FF3B5C]"}>WR {s.winRate}%</span>
              <span className="text-[#8A9AB0]">PF {s.pf}</span>
            </div>
          </button>
        )
      })}
    </div>
  )
}
