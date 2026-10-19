"use client"
import { useEffect, useState } from "react"

export function LiveTicker(){
  const [price, setPrice] = useState<number| null>(null)
  useEffect(()=>{
    async function tick(){
      try{
        const r = await fetch("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT")
        const j = await r.json()
        setPrice(parseFloat(j.price))
      }catch{}
    }
    tick()
    const id = setInterval(tick, 5000)
    return ()=>clearInterval(id)
  },[])
  return <span className="font-mono text-xs px-2 py-1 rounded-lg bg-surface border border-line">BTC {price ? `$${price.toLocaleString()}` : "—"}</span>
}
