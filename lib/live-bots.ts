"use client"
// Live data of the four paper bots on the VPS — the same files https://bot.da3m.io reads.
// nginx sends Access-Control-Allow-Origin for these files (deploy/vps/nginx-bot.da3m.io.conf).
import { useEffect, useState } from "react"
import { BOT_PAGE, STRATEGIES, type Strategy } from "./strategies"

/** sl = the stop price; exit = when/where it takes profit or leaves (each bot has its own rule — some have no fixed target). */
export type LivePosition = { label: string; side: "long" | "short" | "pair"; entry?: number; price?: number; pnl: number; detail?: string
  sl?: number; exit?: string }

const day = (iso?: string) => iso ? new Date(iso).toLocaleDateString("ar-EG", { day: "numeric", month: "short", timeZone: "UTC" }) : "—"
const num = (v: number) => Number(v).toLocaleString("en-US", { maximumSignificantDigits: 6 })

/** The exit rule of one position, in words, from what the bot publishes. */
function exitRule(s: Strategy, d: any, p: any): string {
  if (s.live === "status") return p.exit_below ? `هدف: الترند يقف — لو قفل يومي تحت ${num(p.exit_below)}` : "هدف: الترند يقف (مفيش سعر هدف ثابت)"
  if (s.live === "momentum") return `هدف: التبديل الأسبوعي ${day(d.next_rebalance)}`
  if (s.live === "listing") return `هدف: خروج ${day(p.exit_at)} (بعد ${d.rules?.hold_days ?? 90} يوم)`
  return "مفيش وقف ثابت — خروج لما النسبة تعدي متوسط 50 يوم"
}
export type LiveBot = {
  strategy: Strategy; ok: boolean; updated?: string; fresh: boolean
  realized: number; unrealized: number; open: number; closed: number; wins: number; losses: number
  positions: LivePosition[]; note?: string; raw?: any
}

function normalise(s: Strategy, d: any): LiveBot {
  const st = d.stats || {}
  const fresh = !!d.updated && Date.now() - Date.parse(d.updated) < 15 * 60_000
  let positions: LivePosition[] = []
  let note: string | undefined
  if (s.live === "ratio") {
    positions = (d.pairs || []).map((p: any) => ({ label: `${p.long.symbol.replace("/USDT", "")} / ${p.short.symbol.replace("/USDT", "")}`,
      side: "pair", pnl: p.pnl, detail: "لونج / شورت", exit: exitRule(s, d, p) }))
    if (d.members?.length) note = `القائمة: ${d.members.join(" · ")}`
  } else {
    positions = (d.positions || []).map((p: any) => ({ label: p.symbol.replace("/USDT", ""), side: p.side, entry: p.entry, price: p.price, pnl: p.pnl,
      detail: p.ret !== undefined ? `${p.ret > 0 ? "+" : ""}${Number(p.ret).toFixed(0)}% أسبوعين` : undefined,
      sl: p.sl ?? undefined, exit: exitRule(s, d, p) }))
    if (s.live === "listing" && d.upcoming?.length) note = `جاي: ${d.upcoming.slice(0, 3).map((u: any) => `${u.symbol.replace("/USDT", "")} بعد ${Math.max(0, Math.ceil(u.days_left))} يوم`).join(" · ")}`
    if (s.live === "momentum" && d.next_rebalance) note = `التبديل الجاي: ${new Date(d.next_rebalance).toLocaleDateString("ar-EG", { weekday: "long", day: "numeric", month: "short", timeZone: "UTC" })}`
  }
  return { strategy: s, ok: true, updated: d.updated, fresh, realized: +st.realized || 0, unrealized: +st.unrealized || 0,
    open: positions.length, closed: st.closed || 0, wins: st.wins || 0, losses: st.losses || 0, positions, note, raw: d }
}

export function useLiveBots(intervalMs = 15_000){
  const [bots, setBots] = useState<LiveBot[]>([])
  const [loaded, setLoaded] = useState(false)
  useEffect(() => {
    let stop = false
    const load = async () => {
      const res = await Promise.all(STRATEGIES.map(async s => {
        try {
          const r = await fetch(`${BOT_PAGE}/${s.live}.json?t=${Date.now()}`, { cache: "no-store" })
          if (!r.ok) throw 0
          return normalise(s, await r.json())
        } catch {
          return { strategy: s, ok: false, fresh: false, realized: 0, unrealized: 0, open: 0, closed: 0, wins: 0, losses: 0, positions: [] } as LiveBot
        }
      }))
      if (!stop) { setBots(res); setLoaded(true) }
    }
    load(); const t = setInterval(load, intervalMs)
    return () => { stop = true; clearInterval(t) }
  }, [intervalMs])
  const total = bots.reduce((a, b) => ({ realized: a.realized + b.realized, unrealized: a.unrealized + b.unrealized, open: a.open + b.open,
    closed: a.closed + b.closed, wins: a.wins + b.wins, losses: a.losses + b.losses, running: a.running + (b.fresh ? 1 : 0) }),
    { realized: 0, unrealized: 0, open: 0, closed: 0, wins: 0, losses: 0, running: 0 })
  return { bots, total, loaded }
}

export const ago = (iso?: string) => {
  if (!iso) return "—"
  const s = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 1000))
  return s < 60 ? `من ${s} ثانية` : s < 3600 ? `من ${Math.round(s / 60)} دقيقة` : s < 86400 ? `من ${Math.round(s / 3600)} ساعة` : `من ${Math.round(s / 86400)} يوم`
}
