
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
export async function apiKlines(symbol: string, interval: string, limit=200){
  // Try backend proxy first, fallback to Binance directly
  const sym = symbol.replace("/","")
  try{
    const r=await fetch(`${API}/api/klines?symbol=${symbol}&interval=${interval}&limit=${limit}`)
    if(r.ok) return r.json()
  }catch{}
  try{
    const r=await fetch(`https://api.binance.com/api/v3/klines?symbol=${sym}&interval=${interval}&limit=${limit}`)
    if(r.ok){
      const raw = await r.json()
      // Binance returns [openTime, open, high, low, close, volume, ...]
      return raw.map((k:any)=> ({ time: Math.floor(k[0]/1000), open:+k[1], high:+k[2], low:+k[3], close:+k[4] }))
    }
  }catch{}
  return []
}
