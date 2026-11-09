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
/** The signed-in user as the API sees them: admin or not, and for the admin the 2FA state (null: not signed in or
 *  the API can't be reached). */
export async function apiMe(): Promise<{ admin: boolean, mfa?: { enrolled: boolean, aal: string, required: boolean } } | null>{
  try{
    const headers = await signedInHeaders(); if(!headers) return null
    const r=await fetch(`${API}/api/user/me`, { headers, cache: "no-store" }); return r.ok ? await r.json() : null
  }catch{ return null }
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
/** Admin: approve (or remove) an account for its own Demo bots — the provisioner on the server still checks the rest. */
export const apiAdminApproveUser = (uid: string, on: boolean) => postJson(`/api/admin/user-bots/${encodeURIComponent(uid)}/approve`, { on })
/** Close one trade in the caller's own paper portfolio (at the bot's current price, on the server). */
export const apiPortfolioClose = (label: string, opened: string) => postJson("/api/user/portfolio/close", { label, opened })
/** Admin: ask a paper bot to close one of its positions; the result comes from apiPaperCloseResult. */
export const apiPaperClose = (bot: string, symbol: string): Promise<{ id: string }> => postJson("/api/paper/close", { bot, symbol })
export async function apiPaperCloseResult(bot: string, id: string): Promise<any>{
  const r=await fetch(`${API}/api/paper/close/${bot}/${id}`, { headers: await authHeaders(), cache: "no-store" })
  return r.ok ? r.json() : { done: false }
}

// ── real-orders bots (admin only, one per strategy on the admin's account): yes/no per strategy, positions, manual close
export async function apiLiveStatus(): Promise<any|null>{
  try{
    const headers = await signedInHeaders(); if(!headers) return null
    const r=await fetch(`${API}/api/live/status`, { headers, cache: "no-store" }); return r.ok ? r.json() : null
  }catch{ return null }
}
/** The Demo measurement: each strategy's own closed Demo trades against the backtest baseline (app/demo_measure.py). */
export async function apiLiveMeasurement(): Promise<any|null>{
  try{
    const headers = await signedInHeaders(); if(!headers) return null
    const r=await fetch(`${API}/api/live/measurement`, { headers, cache: "no-store" }); return r.ok ? r.json() : null
  }catch{ return null }
}
/** `acct`: a live strategy's own Binance sub-account (backend/app/live_accounts.py); "" = the main account. Sent only
 *  when set: the frontend deploys before the API, and an API without `acct` refuses unknown fields on some routes. */
const subAccount = (env: "live"|"demo", acct: string) => env === "live" && acct ? { acct } : {}
export async function apiLiveStrategies(env: "live"|"demo" = "live", acct = ""): Promise<any|null>{
  try{
    const headers = await signedInHeaders(); if(!headers) return null
    const q = new URLSearchParams({ env, ...(env === "live" && acct ? { acct } : {}) })
    const r=await fetch(`${API}/api/live/strategies?${q}`, { headers, cache: "no-store" }); return r.ok ? r.json() : null
  }catch{ return null }
}
export async function apiSetLiveStrategies(env: "live"|"demo", account: string, strategies: string[], acct = ""): Promise<any>{
  const r=await fetch(`${API}/api/live/strategies`, { method:"POST", headers: await authHeaders(JSON_CT), body: JSON.stringify({ env, account, strategies, ...subAccount(env, acct) }) })
  const d = await r.json().catch(()=>({}))
  if(!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : "ما اتحفظش")
  return d
}
/** A save the server asks about first (409: the plan looks like the other account's) — confirm, then send again. */
export class CapitalQuestion extends Error {}
export async function apiSetCapital(env: "live"|"demo", capital_usdt: number, capital_margin_override_usdt: number, confirm = false, acct = ""): Promise<any>{
  const r=await fetch(`${API}/api/live/capital`, { method:"POST", headers: await authHeaders(JSON_CT), body: JSON.stringify({ env, capital_usdt, capital_margin_override_usdt, confirm, ...subAccount(env, acct) }) })
  const d = await r.json().catch(()=>({}))
  if(r.status === 409 && typeof d.detail === "string") throw new CapitalQuestion(d.detail)
  if(!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : "ما اتحفظش")
  return d
}
/** An account's risk limits (% of its equity): per trade, aggregate, correlated, daily loss, drawdown. */
export async function apiSetLimits(env: "live"|"demo", limits: Record<string, number>, acct = ""): Promise<any>{
  const r=await fetch(`${API}/api/live/limits`, { method:"POST", headers: await authHeaders(JSON_CT), body: JSON.stringify({ env, ...limits, ...subAccount(env, acct) }) })
  const d = await r.json().catch(()=>({}))
  if(!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : "ما اتحفظش")
  return d
}
/** A real account's kill switch: trip stops every strategy's entries on it, reset lets them enter again. */
export async function apiKillSwitch(action: "trip"|"reset", acct = ""): Promise<any>{
  const r=await fetch(`${API}/api/admin/risk/kill-switch`, { method:"POST", headers: await authHeaders(JSON_CT),
    body: JSON.stringify({ action, ...subAccount("live", acct), confirm: true, reason: action === "trip" ? "operator action (dashboard)" : null }) })
  const d = await r.json().catch(()=>({}))
  if(!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : "ما اتنفذش")
  return d
}
export async function apiLiveClose(strategy: string, symbol: string): Promise<{ id: string }>{
  const r=await fetch(`${API}/api/live/close`, { method:"POST", headers: await authHeaders(JSON_CT), body: JSON.stringify({ strategy, symbol }) })
  const d = await r.json().catch(()=>({}))
  if(!r.ok) throw new Error(d.detail || "الطلب ما اتبعتش")
  return d
}
export async function apiLiveCloseResult(strategy: string, id: string): Promise<any>{
  const r=await fetch(`${API}/api/live/close/${strategy}/${id}`, { headers: await authHeaders(), cache: "no-store" })
  return r.ok ? r.json() : { done: false }
}
/** The signed-in account's own activity (security plan item 10): sign-in sessions and sensitive changes, newest first. */
export type ActivityItem = { at: string, kind: "session" | "account" | "real_money" | "admin", what: string,
  ip: string | null, device: string | null, details: Record<string, unknown> | null }
export async function apiUserActivity(): Promise<{ items: ActivityItem[], keep_days: number }|null>{
  try{
    const headers = await signedInHeaders(); if(!headers) return null
    const r=await fetch(`${API}/api/user/activity`, { headers, cache: "no-store" }); return r.ok ? r.json() : null
  }catch{ return null }
}
/** A user's monthly statement (GET /api/user/statement): their own bots' closed trades in one month. */
export type StatementSummary = { trades: number, wins: number, losses: number, unknown: number, net_usdt: number,
  funding_usdt: number | null, best_usdt: number | null, worst_usdt: number | null }
export type StatementTrade = { strategy: string, env: string, symbol: string, side: string, opened: string | null, time: string,
  entry: number | null, exit: number | null, qty: number | null, pnl: number | null, funding_pnl: number | null, reason: string | null }
export type Statement = { month: string, env: string | null, months: string[], total: StatementSummary,
  strategies: Record<string, StatementSummary & { env: string }>, trades: StatementTrade[] }
export async function apiUserStatement(month: string, env: "live" | "demo"): Promise<Statement|null>{
  try{
    const headers = await signedInHeaders(); if(!headers) return null
    const q = new URLSearchParams({ env, ...(month ? { month } : {}) })
    const r=await fetch(`${API}/api/user/statement?${q}`, { headers, cache: "no-store" }); return r.ok ? r.json() : null
  }catch{ return null }
}
// ── a user's own bots (Phase 2): what they ask for, their bots' status, closing — always the signed-in user's own
export async function apiUserBots(): Promise<any|null>{
  try{
    const headers = await signedInHeaders(); if(!headers) return null
    const r=await fetch(`${API}/api/user/bots`, { headers, cache: "no-store" }); return r.ok ? r.json() : null
  }catch{ return null }
}
/** A real-money plan's risk before the user accepts it (GET /api/user/bots/risk): one stop, the worst week, the level. */
export type LiveRisk = { one_stop_usdt: number, per_trade_pct: number, legs: number, worst_usdt: number, aggregate_pct: number,
  level: "low" | "medium" | "high" | "very_high", ok: boolean, why: string | null,
  reserve_pct: number, max_open: number, fits: boolean, max_margin: number }   // the whole basket after the reserve
export async function apiUserBotsRisk(capital: number, margin: number, reserve = 40, strategies: string[] = ["momentum_ls"]): Promise<LiveRisk | null>{
  try{
    const headers = await signedInHeaders(); if(!headers) return null
    const q = new URLSearchParams({ capital: String(capital), margin: String(margin), reserve: String(reserve), strategies: strategies.join(",") })
    const r = await fetch(`${API}/api/user/bots/risk?${q}`, { headers, cache: "no-store" })
    return r.ok ? r.json() : null
  }catch{ return null }
}
export async function apiSetUserBots(body: any): Promise<any>{
  let r: Response | undefined
  try{ r = await fetch(`${API}/api/user/bots`, { method:"POST", headers: await authHeaders(JSON_CT), body: JSON.stringify(body) }) }
  catch{ r = undefined }
  // a server error answered without CORS headers reaches the page as no answer at all (2026-11-07: "reading 'json'")
  if(!r) throw new Error("الطلب ما وصلش للسيرفر أو السيرفر وقع — جرّب تاني بعد شوية، ولو اتكرر بلّغ")
  const d = await r.json().catch(()=>({}))
  if(!r.ok) throw new Error(d.detail || (r.status >= 500 ? "حصل خطأ في السيرفر — ما اتحفظش" : "ما اتحفظش"))
  return d
}
export async function apiUserBotClose(strategy: string, symbol: string): Promise<{ id: string }>{
  const r=await fetch(`${API}/api/user/bots/close`, { method:"POST", headers: await authHeaders(JSON_CT), body: JSON.stringify({ strategy, symbol }) })
  const d = await r.json().catch(()=>({}))
  if(!r.ok) throw new Error(d.detail || "الطلب ما اتبعتش")
  return d
}
export async function apiAdminUserBots(): Promise<any|null>{
  try{
    const headers = await signedInHeaders(); if(!headers) return null
    const r=await fetch(`${API}/api/admin/user-bots`, { headers, cache: "no-store" }); return r.ok ? r.json() : null
  }catch{ return null }
}
/** Admin: the owner's switch for real money for invited users (root's main lock on the server is needed too). */
export async function apiAdminUsersLive(): Promise<{ on: boolean, by: string | null, at: string | null } | null>{
  try{
    const headers = await signedInHeaders(); if(!headers) return null
    const r=await fetch(`${API}/api/admin/users-live`, { headers, cache: "no-store" }); return r.ok ? r.json() : null
  }catch{ return null }
}
export const apiSetAdminUsersLive = (on: boolean) => postJson("/api/admin/users-live", { on, confirm: true })
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
