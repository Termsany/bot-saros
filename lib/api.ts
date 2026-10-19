
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
