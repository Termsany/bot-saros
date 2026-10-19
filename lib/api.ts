
const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

export async function apiBacktest(body: any){
  const r = await fetch(`${API}/api/backtest`, { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(body) })
  return r.json()
}
export async function apiHealth(){
  try{ const r=await fetch(`${API}/api/health`); return r.json() }catch{ return {ok:false} }
}
export async function apiBotStatus(){
  try{ const r=await fetch(`${API}/api/bot/status`); return r.json() }catch{ return {running:false} }
}
export async function apiBotStart(cfg:any){
  const r=await fetch(`${API}/api/bot/start`, {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(cfg)})
  return r.json()
}
export async function apiBotStop(){
  const r=await fetch(`${API}/api/bot/stop`, {method:"POST"})
  return r.json()
}
export function chartUrl(file:string){ return `${API}/api/chart?file=${encodeURIComponent(file)}` }
export const API_URL = API

export async function apiTrades(limit=20){
  try{ const r=await fetch(`${API}/api/trades?limit=${limit}`); return r.json() }catch{ return [] }
}

function toBybitInterval(tf: string){
  const map: Record<string,string> = { "1m":"1", "5m":"5", "15m":"15", "1h":"60", "4h":"240", "1d":"D" }
  return map[tf] || "60"
}

export async function apiKlines(symbol: string, interval: string, limit=200){
  const sym = symbol.replace("/","")
  const bybitInterval = toBybitInterval(interval)
  // 1) Bybit (no ban, light)
  try{
    const r=await fetch(`https://api.bybit.com/v5/market/kline?category=linear&symbol=${sym}&interval=${bybitInterval}&limit=${limit}`)
    if(r.ok){
      const j = await r.json()
      const list = j?.result?.list
      if(Array.isArray(list) && list.length){
        // Bybit: [startTime, open, high, low, close, volume, turnover] — newest first, reverse
        const sorted = [...list].reverse()
        return sorted.map((k:any)=> ({ time: Math.floor(Number(k[0])/1000) as any, open:+k[1], high:+k[2], low:+k[3], close:+k[4] }))
      }
    }
  }catch{}
  // 2) OKX (light too)
  try{
    const okxTf = interval === "1d" ? "1D" : interval
    const r=await fetch(`https://www.okx.com/api/v5/market/candles?instId=${sym.replace("USDT","-USDT")}&bar=${okxTf}&limit=${limit}`)
    if(r.ok){
      const j = await r.json()
      const data = j?.data
      if(Array.isArray(data) && data.length){
        const sorted = [...data].reverse()
        return sorted.map((k:any)=> ({ time: Math.floor(Number(k[0])/1000) as any, open:+k[1], high:+k[2], low:+k[3], close:+k[4] }))
      }
    }
  }catch{}
  // 3) Binance fallback (may be banned)
  try{
    const r=await fetch(`https://api.binance.com/api/v3/klines?symbol=${sym}&interval=${interval}&limit=${limit}`)
    if(r.ok){
      const raw = await r.json()
      if(Array.isArray(raw) && raw.length){
        return raw.map((k:any)=> ({ time: Math.floor(k[0]/1000) as any, open:+k[1], high:+k[2], low:+k[3], close:+k[4] }))
      }
    }
  }catch{}
  // 4) Backend proxy last resort
  try{
    const r=await fetch(`${API}/api/klines?symbol=${symbol}&interval=${interval}&limit=${limit}`)
    if(r.ok){
      const j = await r.json()
      const raw = Array.isArray(j) ? j : j.candles || j.data || []
      if(raw.length) return raw.map((k:any)=> Array.isArray(k) ? ({ time: Math.floor(k[0]/1000) as any, open:+k[1], high:+k[2], low:+k[3], close:+k[4] }) : k)
    }
  }catch{}
  return []
}
