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

  if(loading) return <div className="rounded-xl bg-surface2 p-4 animate-pulse h-[118px]" />
  if(balance === null) return null // guest — no wallet

  const total = balance + pnl
  const isProfit = pnl >= 0
  const pct = balance ? pnl / balance * 100 : 0

  return (
    <div className="rounded-xl bg-surface2 p-4">
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-2 text-[13px] font-semibold text-muted"><Wallet size={14}/> المحفظة التجريبية</span>
        <span className={`flex items-center gap-1 font-mono text-xs font-bold tabular ${isProfit?"text-profit":"text-loss"}`}>
          {isProfit ? <TrendingUp size={12}/> : <TrendingDown size={12}/>}
          {isProfit?"+":""}{pct.toFixed(1)}%
        </span>
      </div>
      <div className="mt-2 font-mono text-2xl font-bold tabular" dir="ltr">{total.toLocaleString("en-US",{minimumFractionDigits:2, maximumFractionDigits:2})} <span className="text-sm text-muted">USDT</span></div>
      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-line" dir="ltr">
        <div className="h-full rounded-full bg-gradient-to-r from-umbra to-corona" style={{width: `${Math.min(100, Math.max(4, 50 + pct*2))}%`}} />
      </div>
      <div className="mt-2 text-[11px] text-faint">رأس المال {balance.toLocaleString("en-US")} USDT · فلوس وهمية 100%</div>
    </div>
  )
}
