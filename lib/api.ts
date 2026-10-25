import { authHeaders } from "./supabase"

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
const JSON_CT = { "Content-Type": "application/json" }

/** Auth headers, or null when nobody is signed in — callers skip requests that would just be rejected. */
async function signedInHeaders(): Promise<Record<string,string>|null>{
  const h = await authHeaders()
  return h.Authorization ? h : null
}

export async function apiBacktest(body: any){
  const r = await fetch(`${API}/api/backtest`, { method:"POST", headers: await authHeaders(JSON_CT), body: JSON.stringify(body) })
  return r.json()
}
export async function apiHealth(){
  try{ const r=await fetch(`${API}/api/health`); return r.json() }catch{ return {ok:false} }
}
export async function apiBotStatus(){
  try{
    const headers = await signedInHeaders(); if(!headers) return {running:false}
    const r=await fetch(`${API}/api/bot/status`, { headers }); return r.ok ? r.json() : {running:false}
  }catch{ return {running:false} }
}
export async function apiBotStart(cfg:any){
  const r=await fetch(`${API}/api/bot/start`, {method:"POST", headers: await authHeaders(JSON_CT), body: JSON.stringify(cfg)})
  return r.json()
}
export async function apiBotStop(){
  const r=await fetch(`${API}/api/bot/stop`, {method:"POST", headers: await authHeaders()})
  return r.json()
}
/** Plan as the backend sees it (admins count as elite) — same source the server limits use. */
export async function apiUserTier(): Promise<string|null>{
  try{
    const headers = await signedInHeaders(); if(!headers) return null
    const r=await fetch(`${API}/api/user/tier`, { headers }); return r.ok ? (await r.json()).tier : null
  }catch{ return null }
}
export type UserClose = { key: string; bot_pnl: number; exit_price: number|null; closed_at: string }
export type UserSettings = { capital?: number; strategy?: string; started_at?: string; closes?: UserClose[] }
/** The user's capital + chosen bot (personal paper portfolio on the dashboard). */
export async function apiGetSettings(): Promise<UserSettings|null>{
  try{
    const headers = await signedInHeaders(); if(!headers) return null
    const r=await fetch(`${API}/api/user/settings`, { headers }); return r.ok ? r.json() : {}
  }catch{ return {} }
}
export async function apiSaveSettings(body: { capital: number; strategy: string }): Promise<UserSettings>{
  const r=await fetch(`${API}/api/user/settings`, { method:"POST", headers: await authHeaders(JSON_CT), body: JSON.stringify(body) })
  const d = await r.json().catch(()=>({}))
  if(!r.ok) throw new Error(d.detail || "ما اتحفظش")
  return d
}
/** Is the signed-in user the admin (shows the admin buttons; every admin endpoint checks again). */
export async function apiIsAdmin(): Promise<boolean>{
  try{
    const headers = await signedInHeaders(); if(!headers) return false
    const r=await fetch(`${API}/api/user/me`, { headers, cache: "no-store" }); return r.ok ? !!(await r.json()).admin : false
  }catch{ return false }
}
async function postJson(path: string, body: any){
  const r=await fetch(`${API}${path}`, { method:"POST", headers: await authHeaders(JSON_CT), body: JSON.stringify(body) })
  const d = await r.json().catch(()=>({}))
  if(!r.ok) throw new Error(d.detail || "الطلب ما اتبعتش")
  return d
}
/** Close one trade in the caller's own paper portfolio (at the bot's current price, on the server). */
export const apiPortfolioClose = (label: string, opened: string) => postJson("/api/user/portfolio/close", { label, opened })
/** Admin: ask a paper bot to close one of its positions; the result comes from apiPaperCloseResult. */
export const apiPaperClose = (bot: string, symbol: string): Promise<{ id: string }> => postJson("/api/paper/close", { bot, symbol })
export async function apiPaperCloseResult(bot: string, id: string): Promise<any>{
  const r=await fetch(`${API}/api/paper/close/${bot}/${id}`, { headers: await authHeaders(), cache: "no-store" })
  return r.ok ? r.json() : { done: false }
}

// ── real-orders bot (admin only): positions, manual close, its result
export async function apiLiveStatus(): Promise<any|null>{
  try{
    const headers = await signedInHeaders(); if(!headers) return null
    const r=await fetch(`${API}/api/live/status`, { headers, cache: "no-store" }); return r.ok ? r.json() : null
  }catch{ return null }
}
export async function apiLiveClose(symbol: string): Promise<{ id: string }>{
  const r=await fetch(`${API}/api/live/close`, { method:"POST", headers: await authHeaders(JSON_CT), body: JSON.stringify({ symbol }) })
  const d = await r.json().catch(()=>({}))
  if(!r.ok) throw new Error(d.detail || "الطلب ما اتبعتش")
  return d
}
export async function apiLiveCloseResult(id: string): Promise<any>{
  const r=await fetch(`${API}/api/live/close/${id}`, { headers: await authHeaders(), cache: "no-store" })
  return r.ok ? r.json() : { done: false }
}
export function chartUrl(file:string){ return `${API}/api/chart?file=${encodeURIComponent(file)}` }
/** The chart needs the user's login (it's theirs only) — an <img src> can't send it, so fetch it and show a local copy. */
export async function apiChartObjectUrl(file:string): Promise<string|null>{
  try{
    const headers = await signedInHeaders(); if(!headers) return null
    const r=await fetch(chartUrl(file), { headers }); if(!r.ok) return null
    return URL.createObjectURL(await r.blob())
  }catch{ return null }
}
export const API_URL = API

export async function apiTrades(limit=20){
  // admin-only on the backend; non-admins just see no trades
  try{
    const headers = await signedInHeaders(); if(!headers) return []
    const r=await fetch(`${API}/api/trades?limit=${limit}`, { headers }); return r.ok ? r.json() : []
  }catch{ return [] }
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
        return sorted.map((k:any)=> ({ time: Math.floor(Number(k[0])/1000) as any, open:+k[1], high:+k[2], low:+k[3], close:+k[4], volume:+k[5] }))
      }
    }
  }catch{}
  // 2) OKX (light too)
  try{
    const okxTf = interval.replace(/h$/, "H").replace(/d$/, "D")  // OKX bars are 1H, 4H, 1D (15m stays lowercase)
    const r=await fetch(`https://www.okx.com/api/v5/market/candles?instId=${sym.replace("USDT","-USDT")}&bar=${okxTf}&limit=${limit}`)
    if(r.ok){
      const j = await r.json()
      const data = j?.data
      if(Array.isArray(data) && data.length){
        const sorted = [...data].reverse()
        return sorted.map((k:any)=> ({ time: Math.floor(Number(k[0])/1000) as any, open:+k[1], high:+k[2], low:+k[3], close:+k[4], volume:+k[5] }))
      }
    }
  }catch{}
  // 3) Binance fallback (may be banned)
  try{
    const r=await fetch(`https://api.binance.com/api/v3/klines?symbol=${sym}&interval=${interval}&limit=${limit}`)
    if(r.ok){
      const raw = await r.json()
      if(Array.isArray(raw) && raw.length){
        return raw.map((k:any)=> ({ time: Math.floor(k[0]/1000) as any, open:+k[1], high:+k[2], low:+k[3], close:+k[4], volume:+k[5] }))
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
