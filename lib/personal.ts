// Capital-based setup: pick the largest tested size of a bot that fits the user's capital, the margin per trade,
// and the user's personal paper portfolio — the live bot's trades limited to that size and scaled to that margin.
import type { Strategy } from "./strategies"

export type Profile = { id: string; label: string; n: number; trades: number; winRate: number; pf: number; pnl: number; maxDD: number
  sharpeIn: number; sharpeOut: number; pnlOut: number; minMargin: number; minCapital: number; maxOpen: number }
export type Setup = { profile: Profile; margin: number }

/** Largest tested size whose minimum capital fits; margin per trade = capital / (positions + drawdown reserve). */
export function pickSetup(s: Strategy, capital: number): Setup | null {
  const fits = (s.profiles || []).filter(p => p.minCapital <= capital).sort((a, b) => b.n - a.n)
  if (!fits.length) return null
  const p = fits[0]
  // same rule as the minimum: capital = margin × positions + worst drawdown scaled to that margin ($20 in the test)
  const margin = Math.floor(capital / (p.maxOpen + p.maxDD / 20) * 100) / 100
  return { profile: p, margin: Math.max(margin, p.minMargin) }
}
export const smallestCapital = (s: Strategy) => Math.min(...(s.profiles || []).map(p => p.minCapital))

export type PersonalTrade = { manual?: boolean; label: string; side: string; entry?: number; exit?: number; price?: number; pnl: number; opened: string; closed?: string; reason?: string }
export type Personal = { open: PersonalTrade[]; closed: PersonalTrade[]; realized: number; unrealized: number; scale: number }

const after = (iso: string | undefined, start: string) => !!iso && Date.parse(iso) >= Date.parse(start)

/** The live bot's trades kept by the user's size, opened after `startedAt`, scaled to the user's margin (x2 as tested). */
/** A trade's identity across the bot's file and the user's own closes (the server builds the same key). */
export const tradeKey = (t: { label: string; opened: string }) => `${t.label}@${t.opened}`

export function personalPortfolio(s: Strategy, raw: any, setup: Setup, startedAt: string,
                                  closes: { key: string; bot_pnl: number; exit_price: number | null; closed_at: string }[] = []): Personal {
  const n = setup.profile.n
  // bot position notional = its margin × leverage (trend bot: $100 × 5; the others $20 × 2); user = margin × 2
  const scale = (setup.margin * 2) / ((+raw?.margin || 20) * (+raw?.leverage || 2))
  let open: PersonalTrade[] = [], closed: PersonalTrade[] = []
  const pos = raw?.positions || [], hist = raw?.history || []
  if (s.live === "status") {                                   // trend: only coins ranked within the top n by volume
    open = pos.filter((p: any) => p.rank && p.rank <= n && after(p.opened, startedAt))
      .map((p: any) => ({ label: p.symbol.replace("/USDT", ""), side: "long", entry: p.entry, price: p.price, pnl: p.pnl * scale, opened: p.opened }))
    closed = hist.filter((h: any) => h.rank && h.rank <= n && after(h.opened, startedAt))
      .map((h: any) => ({ label: h.symbol.replace("/USDT", ""), side: "long", entry: h.entry, exit: h.exit, pnl: h.pnl * scale, opened: h.opened, closed: h.time, reason: h.reason }))
  } else if (s.live === "momentum") {                          // momentum: the strongest n longs and weakest n shorts of each week
    const keep = (rows: any[]) => {
      const byWeek: Record<string, any[]> = {}
      for (const r of rows) if (after(r.opened, startedAt)) (byWeek[(r.opened || "").slice(0, 10)] ??= []).push(r)
      return Object.values(byWeek).flatMap(w => [
        ...w.filter(r => r.side === "long").sort((a, b) => b.ret - a.ret).slice(0, n),
        ...w.filter(r => r.side === "short").sort((a, b) => a.ret - b.ret).slice(0, n)])
    }
    open = keep(pos).map((p: any) => ({ label: p.symbol.replace("/USDT", ""), side: p.side, entry: p.entry, price: p.price, pnl: p.pnl * scale, opened: p.opened }))
    closed = keep(hist).map((h: any) => ({ label: h.symbol.replace("/USDT", ""), side: h.side, entry: h.entry, exit: h.exit, pnl: h.pnl * scale, opened: h.opened, closed: h.time, reason: h.reason }))
  } else if (s.live === "listing") {                           // new-listing short: the bot's entries with a cap of n open at once
    const all = [...hist.map((h: any) => ({ ...h, done: true })), ...pos.map((p: any) => ({ ...p, done: false }))]
      .filter((r: any) => after(r.opened, startedAt)).sort((a: any, b: any) => Date.parse(a.opened) - Date.parse(b.opened))
    const kept: any[] = []
    for (const r of all) {
      const openNow = kept.filter(k => !k.done || Date.parse(k.time) > Date.parse(r.opened)).length
      if (openNow < n) kept.push(r)
    }
    open = kept.filter(r => !r.done).map(p => ({ label: p.symbol.replace("/USDT", ""), side: "short", entry: p.entry, price: p.price, pnl: p.pnl * scale, opened: p.opened }))
    closed = kept.filter(r => r.done).map(h => ({ label: h.symbol.replace("/USDT", ""), side: "short", entry: h.entry, exit: h.exit, pnl: h.pnl * scale, opened: h.opened, closed: h.time, reason: h.reason }))
  } else {                                                     // ratio: pairs whose two coins were within the top n by volume
    const inTop = (r: any) => Array.isArray(r.ranks) && r.ranks.every((x: number) => x && x <= n)
    open = (raw?.pairs || []).filter((p: any) => inTop(p) && after(p.opened, startedAt))
      .map((p: any) => ({ label: `${p.long.symbol.replace("/USDT", "")} / ${p.short.symbol.replace("/USDT", "")}`, side: "pair", pnl: p.pnl * scale, opened: p.opened }))
    closed = hist.filter((h: any) => inTop(h) && after(h.opened, startedAt))
      .map((h: any) => ({ label: h.pair, side: "pair", pnl: h.pnl * scale, opened: h.opened, closed: h.time, reason: h.reason }))
  }
  // the user's own manual closes win over the bot: closed at the bot's PnL of that moment, scaled to the user
  const mine = new Map(closes.map(c => [c.key, c]))
  const asClosed = (t: PersonalTrade): PersonalTrade => {
    const c = mine.get(tradeKey(t))!
    return { ...t, pnl: c.bot_pnl * scale, exit: c.exit_price ?? undefined, closed: c.closed_at, reason: "قفل يدوي", manual: true }
  }
  closed = [...open.filter(t => mine.has(tradeKey(t))).map(asClosed), ...closed.map(t => mine.has(tradeKey(t)) ? asClosed(t) : t)]
    .sort((a, b) => Date.parse(b.closed || "") - Date.parse(a.closed || ""))
  open = open.filter(t => !mine.has(tradeKey(t)))
  return { open, closed, scale, realized: closed.reduce((a, t) => a + t.pnl, 0), unrealized: open.reduce((a, t) => a + t.pnl, 0) }
}
