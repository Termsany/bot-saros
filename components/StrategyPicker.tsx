"use client"
import { STRATEGIES, TIERS } from "@/lib/strategies"

export function StrategyPicker({ selected, onToggle, tier }: { selected: string[], onToggle: (id:string)=>void, tier: string }){
  const tierOrder: Record<string,number> = { free: 2, starter: 6, pro: 7, elite: 15 }
  const maxCount = tierOrder[tier] ?? 2
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
      {STRATEGIES.map((s,i)=>{
        const locked = i >= maxCount
        const active = selected.includes(s.id)
        return (
          <button
            key={s.id}
            disabled={locked}
            onClick={()=>!locked && onToggle(s.id)}
            className={`text-right p-4 rounded-xl border text-sm transition flex flex-col min-h-[140px] ${locked ? "opacity-40 border-[#1c2632] bg-[#0c131c]" : active ? "border-[#00D395]/50 bg-[#00D395]/[0.07] shadow-[0_0_0_1px_rgba(0,211,149,0.15)]" : "border-[#1c2632] bg-[#0a1018] hover:border-[#2a3a56] hover:bg-[#111a25]"}`}
          >
            <div className="flex justify-between items-start">
              <span className="text-base leading-none">{s.icon}</span>
              {locked && <span className="text-[10px] px-2 py-0.5 rounded-full bg-[#2a2506] text-[#FFB800] font-bold">Elite</span>}
              {!locked && active && <span className="h-5 w-5 grid place-items-center rounded-full bg-[#00D395] text-[#062016] text-[11px] font-black">✓</span>}
            </div>
            <div className="font-bold mt-2.5 text-sm leading-tight">{s.nameAr}</div>
            <div className="font-mono text-xs text-[#8A9AB0] leading-tight mt-1">{s.desc}</div>
            <div className="mt-auto pt-3 flex gap-3 font-mono text-xs">
              <span className={s.winRate>=45 ? "text-[#00D395] font-bold" : s.winRate>=35 ? "text-[#FFB800] font-bold" : "text-[#FF3B5C] font-bold"}>WR {s.winRate}%</span>
              <span className="text-[#5f6e81]">PF {s.pf}</span>
            </div>
          </button>
        )
      })}
    </div>
  )
}
