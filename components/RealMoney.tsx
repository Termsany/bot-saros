"use client"
// The real-money bots on the dashboard: the same file https://realbot.da3m.io shows, via /api/realbot.
// Laid out like Figma "RAQM — Global Redesign 2026" 04 · Dashboard: four numbers, then every leg in a table.
import { useEffect, useState } from "react"
import { Card, CardHeader, Dot, Pill } from "@/components/ui"
import { STRATEGIES, strategyName } from "@/lib/strategies"
import { agoText, useLocale, useT } from "@/lib/i18n/locale"
import type { Locale } from "@/lib/i18n/landing"

type Pos = { symbol: string; side: "long" | "short"; entry: number; price?: number; qty: number; contract_size?: number; sl?: number; pnl?: number; loss_at_sl?: number }
type Trade = { pnl?: number }
type Bot = { strategy: string; updated?: string; running: boolean; leverage?: number; positions: Pos[]; history: Trade[]; next_rebalance?: string | null }

export const REAL_PAGE = "https://realbot.da3m.io"
/** The real-money page in the reader's language (the page reads ?lang=, deploy/vps/realbot/index.html). */
export const realPage = (l: Locale) => `${REAL_PAGE}/?lang=${l}`
const fmt = (v: number, d = 2) => v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d })
const signed = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${fmt(Math.abs(v))}`
const px = (v?: number) => v == null ? "—" : Number(v).toLocaleString("en-US", { maximumSignificantDigits: 6 })
const tone = (v: number) => v > 0 ? "text-profit" : v < 0 ? "text-loss" : "text-muted"
const when = (iso: string, l: Locale) => l === "en"
  ? new Date(iso).toLocaleString("en-GB", { weekday: "long", day: "numeric", month: "long", hour: "2-digit", minute: "2-digit", timeZone: "UTC" }) + " UTC"
  : new Date(iso).toLocaleString("ar-EG", { weekday: "long", day: "numeric", month: "long", hour: "2-digit", minute: "2-digit", timeZone: "Africa/Cairo", numberingSystem: "latn" }) + " بتوقيت مصر"

const T = {
  ar: {
    title: "التداول الحقيقي", sub: "فلوس حقيقية على Binance Futures · كل صفقة ليها وقف على المنصة", badge: "LIVE · فلوس حقيقية",
    running: (a: string) => `شغال · ${a}`, none: "مفيش بوت حقيقي شغال", loading: "بيحمّل…", error: "بيانات البوت الحقيقي مش متاحة دلوقتي", empty: "مفيش بوت بفلوس حقيقية شغال دلوقتي",
    k: { open: "ربح الصفقات المفتوحة", openSub: "USDT · قبل الرسوم والـ funding", real: "الربح المحقق", realSub: (w: number, l: number) => `${w} كسبانة · ${l} خسرانة`, legs: "صفقات مفتوحة", legsSub: (m: string) => `هامش مستخدم $${m}`, stops: "لو كل الوقفات اتضربت", stopsSub: "أقصى خسارة للمفتوح دلوقتي" },
    head: ["العملة", "الجهة", "الدخول", "السعر", "الوقف على Binance", "الهامش", "الربح", "لو الوقف اتضرب"],
    legsLine: (n: number, x: number) => `${n} مفتوحة · رافعة x${x}`, next: "التبديل الجاي (البوت الحقيقي)", page: "الصفحة المباشرة بالأسعار اللحظية ←",
  },
  en: {
    title: "Real money", sub: "Real money on Binance Futures · every trade has its stop on the exchange", badge: "LIVE · real money",
    running: (a: string) => `Running · ${a}`, none: "No real-money bot running", loading: "Loading…", error: "The real bot's data isn't available right now", empty: "No real-money bot is running right now",
    k: { open: "Open P&L", openSub: "USDT · before fees and funding", real: "Realized", realSub: (w: number, l: number) => `${w} won · ${l} lost`, legs: "Open legs", legsSub: (m: string) => `margin in use $${m}`, stops: "If every stop hit", stopsSub: "the most the open legs can lose now" },
    head: ["Coin", "Side", "Entry", "Price", "Stop on Binance", "Margin", "P&L", "If stop hits"],
    legsLine: (n: number, x: number) => `${n} open · x${x} leverage`, next: "Next rebalance (real bot)", page: "Live page with live prices →",
  },
}

export function useRealBots(intervalMs = 20_000){
  const [bots, setBots] = useState<Bot[]>([])
  const [state, setState] = useState<"loading" | "ok" | "error">("loading")
  useEffect(() => {
    let stop = false
    const load = async () => {
      try {
        const r = await fetch(`/api/realbot?t=${Date.now()}`, { cache: "no-store" })
        if(!r.ok) throw 0
        const d = await r.json()
        if(!stop){ setBots(Array.isArray(d.bots) ? d.bots : []); setState("ok") }
      } catch { if(!stop) setState(s => s === "ok" ? "ok" : "error") }
    }
    load(); const t = setInterval(load, intervalMs)
    return () => { stop = true; clearInterval(t) }
  }, [intervalMs])
  return { bots, state }
}

export function RealMoney(){
  const t = useT(T)
  const locale = useLocale()
  const { bots, state } = useRealBots()
  const running = bots.filter(b => b.running).length
  let unreal = 0, realized = 0, wins = 0, losses = 0, open = 0, margin = 0, atStops = 0
  for(const b of bots){
    const lev = b.leverage || 2
    for(const p of b.positions){ unreal += p.pnl || 0; open += 1; atStops += p.loss_at_sl || 0; margin += p.entry * p.qty * (p.contract_size || 1) / lev }
    for(const h of b.history){ realized += h.pnl || 0; if((h.pnl || 0) > 0) wins++; else if((h.pnl || 0) < 0) losses++ }
  }
  const name = (id: string) => { const s = STRATEGIES.find(x => x.id === id); return s ? strategyName(s, locale) : id }
  const next = bots.find(b => b.next_rebalance)?.next_rebalance
  const align = { textAlign: locale === "en" ? "left" : "right" } as const

  return (
    <Card className="border-loss/40">
      <CardHeader title={t.title} sub={t.sub}
        action={<div className="flex flex-wrap items-center gap-2">
          <Pill tone="loss">{t.badge}</Pill>
          {state === "ok" && <Pill tone={running ? "profit" : "neutral"}><Dot tone={running ? "profit" : "neutral"} pulse={!!running}/>{running ? t.running(agoText(bots[0]?.updated, locale)) : t.none}</Pill>}
        </div>}/>

      {state === "loading" && <div className="rounded-xl bg-surface2/50 px-3 py-6 text-center text-xs text-faint">{t.loading}</div>}
      {state === "error" && <div className="rounded-xl bg-loss/10 px-3 py-6 text-center text-xs text-loss">{t.error}</div>}
      {state === "ok" && !bots.length && <div className="rounded-xl bg-surface2/50 px-3 py-6 text-center text-xs text-faint">{t.empty}</div>}

      {state === "ok" && bots.length > 0 && <>
        <div className="grid grid-cols-2 gap-2.5 xl:grid-cols-4">
          {[
            { l: t.k.open, v: signed(unreal), c: tone(unreal), s: t.k.openSub },
            { l: t.k.real, v: signed(realized), c: tone(realized), s: t.k.realSub(wins, losses) },
            { l: t.k.legs, v: String(open), c: "text-ink", s: t.k.legsSub(fmt(margin)) },
            { l: t.k.stops, v: signed(atStops), c: "text-loss", s: t.k.stopsSub },
          ].map(k => (
            <div key={k.l} className="min-w-0 rounded-xl bg-surface2/55 px-3.5 py-3">
              <div className="text-[12px] text-muted">{k.l}</div>
              <div className={`mt-1 truncate font-mono text-[20px] font-bold tabular ${k.c}`} dir="ltr" style={align}>{k.v}</div>
              <div className="mt-0.5 text-[11px] leading-4 text-faint">{k.s}</div>
            </div>
          ))}
        </div>

        {bots.map(b => {
          const lev = b.leverage || 2
          return (
            <div key={b.strategy} className="mt-4">
              <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
                <span className="text-[15px] font-semibold">{name(b.strategy)}</span>
                <span className="text-[12px] text-faint">{t.legsLine(b.positions.length, lev)}</span>
              </div>
              <div className="overflow-x-auto rounded-xl border border-line">
                <table className="w-full min-w-[760px] text-[13px]">
                  <thead className="bg-surface2 text-[11px] text-faint">
                    <tr>{t.head.map(h => <th key={h} className="px-3 py-2 text-start font-semibold">{h}</th>)}</tr>
                  </thead>
                  <tbody>
                    {[...b.positions].sort((x, y) => (y.pnl || 0) - (x.pnl || 0)).map(p => {
                      const m = p.entry * p.qty * (p.contract_size || 1) / lev
                      return (
                        <tr key={p.symbol} className="border-t border-line">
                          <td className="px-3 py-2.5 font-semibold" dir="ltr" style={align}>{p.symbol.split(":")[0]}</td>
                          <td className="px-3 py-2.5"><span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${p.side === "long" ? "bg-profit/10 text-profit" : "bg-loss/10 text-loss"}`}>{p.side === "long" ? "LONG" : "SHORT"}</span></td>
                          {[px(p.entry), px(p.price), px(p.sl), `$${fmt(m)}`].map((v, i) => <td key={i} className="px-3 py-2.5 font-mono tabular" dir="ltr" style={align}>{v}</td>)}
                          <td className={`px-3 py-2.5 font-mono font-bold tabular ${tone(p.pnl || 0)}`} dir="ltr" style={align}>{signed(p.pnl || 0)}</td>
                          <td className="px-3 py-2.5 font-mono tabular text-loss" dir="ltr" style={align}>{p.loss_at_sl != null ? signed(p.loss_at_sl) : "—"}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )
        })}

        <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
          {next ? <div className="rounded-xl border border-corona/35 bg-corona/[0.08] px-3.5 py-2.5">
            <div className="text-[12px] font-semibold text-corona">{t.next}</div>
            <div className="text-[14px] font-semibold">{when(next, locale)}</div>
          </div> : <span/>}
          <a href={realPage(locale)} target="_blank" rel="noopener noreferrer" className="text-[13px] font-semibold text-corona">{t.page}</a>
        </div>
      </>}
    </Card>
  )
}
