"use client"
// Live data of the four paper bots on the VPS — the same files https://bot.da3m.io reads.
// nginx sends Access-Control-Allow-Origin for these files (deploy/vps/nginx-bot.da3m.io.conf).
import { useEffect, useState } from "react"
import { BOT_PAGE, LIVE_BOTS, type LiveStrategy } from "./strategies"
import { useLocale } from "./i18n/locale"
import type { Locale } from "./i18n/landing"

/** sl = the stop price; exit = when/where it takes profit or leaves (each bot has its own rule — some have no fixed target). */
export type LivePosition = { label: string; side: "long" | "short" | "pair"; entry?: number; price?: number; pnl: number; detail?: string
  sl?: number; exit?: string; ref: string }   // ref: what an admin close request names (the coin, or the ratio pair key)

const day = (iso: string | undefined, l: Locale = "ar") => iso ? new Date(iso).toLocaleDateString(l === "en" ? "en-GB" : "ar-EG", { day: "numeric", month: "short", timeZone: "UTC" }) : "—"
const num = (v: number) => Number(v).toLocaleString("en-US", { maximumSignificantDigits: 6 })

/** The exit rule of one position, in words, from what the bot publishes. */
function exitRule(s: LiveStrategy, d: any, p: any, l: Locale = "ar"): string {
  const en = l === "en"
  if (s.live === "status") return p.exit_below ? (en ? `Exit: the trend stops — a daily close under ${num(p.exit_below)}` : `هدف: الترند يقف — لو قفل يومي تحت ${num(p.exit_below)}`) : (en ? "Exit: the trend stops (no fixed target)" : "هدف: الترند يقف (مفيش سعر هدف ثابت)")
  if (s.live === "momentum") return en ? `Exit: the weekly rebalance, ${day(d.next_rebalance, l)}` : `هدف: التبديل الأسبوعي ${day(d.next_rebalance)}`
  if (s.live === "breakout") return en ? "Exit: tomorrow's open, 00:00 UTC" : "هدف: خروج افتتاح بكرة 00:00 UTC"
  if (s.live === "tbreak") return en ? "Exit: the first daily close under the 20-day average (no fixed target)" : "هدف: أول قفل يومي تحت متوسط 20 يوم (مفيش سعر هدف ثابت)"
  if (s.live === "rsi2") return en ? `Exit: the first daily close over the 5-day average (by ${day(p.exit_at, l)})` : `هدف: أول قفل يومي فوق متوسط 5 أيام (لحد ${day(p.exit_at)})`
  if (s.live === "listing") return en ? `Exit: ${day(p.exit_at, l)} (after ${d.rules?.hold_days ?? 90} days)` : `هدف: خروج ${day(p.exit_at)} (بعد ${d.rules?.hold_days ?? 90} يوم)`
  return en ? "No fixed stop — exits when the ratio crosses its 50-day average" : "مفيش وقف ثابت — خروج لما النسبة تعدي متوسط 50 يوم"
}
export type LiveBot = {
  strategy: LiveStrategy; ok: boolean; updated?: string; fresh: boolean
  realized: number; unrealized: number; open: number; closed: number; wins: number; losses: number
  positions: LivePosition[]; note?: string; raw?: any
}

function normalise(s: LiveStrategy, d: any, l: Locale = "ar"): LiveBot {
  const en = l === "en"
  const st = d.stats || {}
  const fresh = !!d.updated && Date.now() - Date.parse(d.updated) < 15 * 60_000
  let positions: LivePosition[] = []
  let note: string | undefined
  if (s.live === "ratio") {
    positions = (d.pairs || []).map((p: any) => ({ label: `${p.long.symbol.replace("/USDT", "")} / ${p.short.symbol.replace("/USDT", "")}`,
      side: "pair", pnl: p.pnl, detail: en ? "long / short" : "لونج / شورت", exit: exitRule(s, d, p, l), ref: p.pair }))
    if (d.members?.length) note = `${en ? "Members" : "القائمة"}: ${d.members.join(" · ")}`
  } else {
    positions = (d.positions || []).map((p: any) => ({ label: p.symbol.replace("/USDT", ""), side: p.side, entry: p.entry, price: p.price, pnl: p.pnl,
      detail: p.ret !== undefined ? `${p.ret > 0 ? "+" : ""}${Number(p.ret).toFixed(0)}% ${en ? "2 weeks" : "أسبوعين"}` : undefined,
      sl: p.sl ?? undefined, exit: exitRule(s, d, p, l), ref: p.symbol }))
    if (s.live === "listing" && d.upcoming?.length) note = `${en ? "Next" : "جاي"}: ${d.upcoming.slice(0, 3).map((u: any) => en ? `${u.symbol.replace("/USDT", "")} in ${Math.max(0, Math.ceil(u.days_left))} d` : `${u.symbol.replace("/USDT", "")} بعد ${Math.max(0, Math.ceil(u.days_left))} يوم`).join(" · ")}`
    if (s.live === "momentum" && d.next_rebalance) note = `${en ? "Next rebalance" : "التبديل الجاي"}: ${new Date(d.next_rebalance).toLocaleDateString(en ? "en-GB" : "ar-EG", { weekday: "long", day: "numeric", month: "short", timeZone: "UTC" })}`
  }
  return { strategy: s, ok: true, updated: d.updated, fresh, realized: +st.realized || 0, unrealized: +st.unrealized || 0,
    open: positions.length, closed: st.closed || 0, wins: st.wins || 0, losses: st.losses || 0, positions, note, raw: d }
}

export function useLiveBots(intervalMs = 15_000){
  const locale = useLocale()
  const [bots, setBots] = useState<LiveBot[]>([])
  const [loaded, setLoaded] = useState(false)
  useEffect(() => {
    let stop = false
    const load = async () => {
      const res = await Promise.all(LIVE_BOTS.map(async s => {
        try {
          const r = await fetch(`${BOT_PAGE}/${s.live}.json?t=${Date.now()}`, { cache: "no-store" })
          if (!r.ok) throw 0
          return normalise(s, await r.json(), locale)
        } catch {
          return { strategy: s, ok: false, fresh: false, realized: 0, unrealized: 0, open: 0, closed: 0, wins: 0, losses: 0, positions: [] } as LiveBot
        }
      }))
      if (!stop) { setBots(res); setLoaded(true) }
    }
    load(); const t = setInterval(load, intervalMs)
    return () => { stop = true; clearInterval(t) }
  }, [intervalMs, locale])
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
