"use client"
import { useEffect, useState } from "react"
import { supabase } from "@/lib/supabase"
import { Wallet, TrendingUp, TrendingDown } from "lucide-react"

export function PaperWallet(){
  const [balance, setBalance] = useState<number|null>(null)
  const [pnl, setPnl] = useState(0)
  const [loading, setLoading] = useState(true)

  useEffect(()=>{
    async function load(){
      if(!supabase){ setLoading(false); return }  // Supabase env not set (e.g. local dev)
      const { data: { user } } = await supabase.auth.getUser()
      if(!user){ setLoading(false); return }
      const { data } = await supabase.from("profiles").select("paper_balance, paper_pnl").eq("id", user.id).single()
      if(data){
        setBalance(Number(data.paper_balance ?? 1000))
        setPnl(Number(data.paper_pnl ?? 0))
      } else {
        setBalance(1000)
      }
      setLoading(false)
    }
    load()
  }, [])

  if(loading) return <div className="rounded-xl border border-[#1c2632] bg-[#0c131c] p-3 animate-pulse h-[80px]" />
  if(balance === null) return null // guest — no wallet

  const total = balance + pnl
  const isProfit = pnl >= 0

  return (
    <div className="rounded-xl border border-[#1c2632] bg-[#0c131c] p-4">
      <div className="flex items-center gap-2 text-[11px] tracking-[0.12em] text-[#5f6e81] font-mono"><Wallet size={12}/> المحفظة الوهمية</div>
      <div className="mt-2 flex items-baseline gap-2">
        <span className="text-xl font-black font-mono">${total.toFixed(2)}</span>
        <span className={`text-xs font-bold font-mono flex items-center gap-1 ${isProfit?"text-[#00D395]":"text-[#FF3B5C]"}`}>
          {isProfit ? <TrendingUp size={12}/> : <TrendingDown size={12}/>}
          {isProfit?"+":""}{pnl.toFixed(2)}
        </span>
      </div>
      <div className="font-mono text-[11px] text-[#5f6e81] mt-1">رصيد {balance.toFixed(0)}$ + ربح {pnl>=0?"+":""}{pnl.toFixed(2)}$ · وهمي 100%</div>
      <div className="mt-2 h-1.5 rounded-full bg-[#1c2632] overflow-hidden">
        <div className={`h-full rounded-full ${isProfit?"bg-[#00D395]":"bg-[#FF3B5C]"}`} style={{width: `${Math.min(100, Math.max(4, 50 + (pnl/20)))}%`}} />
      </div>
    </div>
  )
}
