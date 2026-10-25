import { NextRequest, NextResponse } from "next/server"
import TRADES from "@/data/bot-trades.json"
import { BACKTEST_DAYS, STRATEGIES, TIERS, backtestSpanDays } from "@/lib/strategies"

// The portfolio bots' tested trades (research/bots_stats.py) are what the paid plans sell: served only for the
// strategies and date span the caller's plan unlocks — the plan comes from the backend, the same check its own
// backtest uses (admins count as elite). The full file is not public anymore.
const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
type Row = [number, number, string, string, number, number, number, string]
const FILE = TRADES as unknown as { meta: { to: string; marginUsdt: number }, trades: Record<string, Record<string, Row[]>> }
const DATE = /^\d{4}-\d{2}-\d{2}$/

export async function GET(req: NextRequest){
  const q = new URL(req.url).searchParams
  const strategy = q.get("strategy") || "", lev = q.get("leverage") || "2", from = q.get("from") || "", to = q.get("to") || ""
  if(!DATE.test(from) || !DATE.test(to) || Date.parse(from) > Date.parse(to)) return NextResponse.json({ error: "bad dates" }, { status: 400 })
  const idx = STRATEGIES.findIndex(s => s.id === strategy)
  if(idx < 0 || !Object.hasOwn(FILE.trades, strategy)) return NextResponse.json({ error: "unknown strategy" }, { status: 400 })

  const auth = req.headers.get("authorization") || ""
  if(!/^Bearer\s+\S+/i.test(auth)) return NextResponse.json({ error: "سجّل دخول الأول" }, { status: 401 })
  let tier = ""
  try {
    const r = await fetch(`${API}/api/user/tier`, { headers: { Authorization: auth }, cache: "no-store" })
    if(!r.ok) return NextResponse.json({ error: "سجّل دخول الأول" }, { status: 401 })
    tier = (await r.json()).tier
  } catch { return NextResponse.json({ error: "مقدرناش نتأكد من باقتك — جرّب تاني" }, { status: 503 }) }

  const count = TIERS.find(t => t.id === tier)?.count ?? 1
  if(idx >= count) return NextResponse.json({ error: "الاستراتيجية دي مش في باقتك" }, { status: 403 })
  // null = unlimited (elite) — `??` would turn it into the free plan's 7 days
  const maxDays = Object.hasOwn(BACKTEST_DAYS, tier) ? BACKTEST_DAYS[tier] : BACKTEST_DAYS.free
  if(maxDays !== null && backtestSpanDays(from, to) > maxDays) return NextResponse.json({ error: `باقتك لحد ${maxDays} يوم` }, { status: 403 })

  const byLev = FILE.trades[strategy]
  const useLev = Object.hasOwn(byLev, lev) ? lev : "2"
  const fromMs = Date.parse(from), toMs = Date.parse(to) + 86400000 - 1
  const rows = (byLev[useLev] || []).filter(r => r[0] >= fromMs && r[0] <= toMs)
  return NextResponse.json({ meta: { to: FILE.meta.to, marginUsdt: FILE.meta.marginUsdt }, leverage: Number(useLev), rows },
    { headers: { "Cache-Control": "private, no-store" } })
}
