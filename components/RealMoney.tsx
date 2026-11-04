"use client"
// The real-money bots on the dashboard: the same file https://realbot.da3m.io shows, via /api/realbot.
import { useEffect, useState } from "react"
import { Card, CardHeader, Dot, Pill } from "@/components/ui"
import { STRATEGIES } from "@/lib/strategies"
import { ago } from "@/lib/live-bots"

type Pos = { symbol: string; side: "long" | "short"; entry: number; price?: number; qty: number; contract_size?: number; sl?: number; pnl?: number; loss_at_sl?: number }
type Trade = { pnl?: number }
type Bot = { strategy: string; updated?: string; running: boolean; leverage?: number; positions: Pos[]; history: Trade[]; next_rebalance?: string | null }

export const REAL_PAGE = "https://realbot.da3m.io"
const fmt = (v: number, d = 2) => v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d })
const signed = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${fmt(Math.abs(v))}`
const px = (v?: number) => v == null ? "—" : Number(v).toLocaleString("en-US", { maximumSignificantDigits: 6 })
const tone = (v: number) => v > 0 ? "text-profit" : v < 0 ? "text-loss" : "text-muted"
const when = (iso: string) => new Date(iso).toLocaleString("ar-EG", { weekday: "long", day: "numeric", month: "long", hour: "2-digit", minute: "2-digit", timeZone: "Africa/Cairo", numberingSystem: "latn" }) + " بتوقيت مصر"

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
  const { bots, state } = useRealBots()
  const running = bots.filter(b => b.running).length
  let unreal = 0, realized = 0, wins = 0, losses = 0, open = 0, margin = 0, atStops = 0
  for(const b of bots){
    const lev = b.leverage || 2
    for(const p of b.positions){ unreal += p.pnl || 0; open += 1; atStops += p.loss_at_sl || 0; margin += p.entry * p.qty * (p.contract_size || 1) / lev }
    for(const h of b.history){ realized += h.pnl || 0; if((h.pnl || 0) > 0) wins++; else if((h.pnl || 0) < 0) losses++ }
  }
  const name = (id: string) => STRATEGIES.find(s => s.id === id)?.nameAr || id
  const next = bots.find(b => b.next_rebalance)?.next_rebalance

  return (
    <Card className="border-loss/40">
      <CardHeader title="التداول الحقيقي" sub="فلوس حقيقية على Binance Futures · كل صفقة ليها وقف على المنصة"
        action={<div className="flex flex-wrap items-center gap-2">
          <Pill tone="loss">LIVE · فلوس حقيقية</Pill>
          {state === "ok" && <Pill tone={running ? "profit" : "neutral"}><Dot tone={running ? "profit" : "neutral"} pulse={!!running}/>{running ? `شغال · ${ago(bots[0]?.updated)}` : "مفيش بوت حقيقي شغال"}</Pill>}
        </div>}/>

      {state === "loading" && <div className="rounded-xl bg-surface2/50 px-3 py-6 text-center text-xs text-faint">بيحمّل…</div>}
      {state === "error" && <div className="rounded-xl bg-loss/10 px-3 py-6 text-center text-xs text-loss">بيانات البوت الحقيقي مش متاحة دلوقتي</div>}
      {state === "ok" && !bots.length && <div className="rounded-xl bg-surface2/50 px-3 py-6 text-center text-xs text-faint">مفيش بوت بفلوس حقيقية شغال دلوقتي</div>}

      {state === "ok" && bots.length > 0 && <>
        <div className="grid grid-cols-2 gap-2.5 xl:grid-cols-4">
          {[
            { l: "ربح الصفقات المفتوحة", v: `${signed(unreal)}`, t: tone(unreal), s: "USDT · قبل الرسوم والـ funding" },
            { l: "الربح المحقق", v: signed(realized), t: tone(realized), s: `${wins} كسبانة · ${losses} خسرانة` },
            { l: "صفقات مفتوحة", v: String(open), t: "text-ink", s: `هامش مستخدم $${fmt(margin)}` },
            { l: "لو كل الوقفات اتضربت", v: signed(atStops), t: "text-loss", s: "أقصى خسارة للمفتوح دلوقتي" },
          ].map(k => (
            <div key={k.l} className="min-w-0 rounded-xl bg-surface2/55 px-3.5 py-3">
              <div className="text-[12px] text-muted">{k.l}</div>
              <div className={`mt-1 truncate font-mono text-[20px] font-bold tabular ${k.t}`} dir="ltr" style={{ textAlign: "right" }}>{k.v}</div>
              <div className="mt-0.5 text-[11px] leading-4 text-faint">{k.s}</div>
            </div>
          ))}
        </div>

        {bots.map(b => (
          <div key={b.strategy} className="mt-4">
            <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
              <span className="text-[15px] font-semibold">{name(b.strategy)}</span>
              <span className="text-[12px] text-faint">{b.positions.length} مفتوحة · رافعة x{b.leverage || 2}</span>
            </div>
            <div className="grid gap-1.5 sm:grid-cols-2 xl:grid-cols-5">
              {b.positions.map(p => (
                <div key={p.symbol} className="flex items-center justify-between gap-2 rounded-lg bg-surface2/55 px-3 py-2">
                  <div className="min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className="truncate text-[13px] font-semibold" dir="ltr">{p.symbol.split(":")[0].replace("/USDT", "")}</span>
                      <span className={`text-[10px] font-bold ${p.side === "long" ? "text-profit" : "text-loss"}`}>{p.side === "long" ? "LONG" : "SHORT"}</span>
                    </div>
                    <div className="font-mono text-[10.5px] text-faint" dir="ltr" style={{ textAlign: "right" }}>{px(p.price)} · SL {px(p.sl)}</div>
                  </div>
                  <span className={`shrink-0 font-mono text-[13px] font-bold tabular ${tone(p.pnl || 0)}`} dir="ltr">{signed(p.pnl || 0)}</span>
                </div>
              ))}
            </div>
          </div>
        ))}

        <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
          {next ? <div className="rounded-xl border border-corona/35 bg-corona/[0.08] px-3.5 py-2.5">
            <div className="text-[12px] font-semibold text-corona">التبديل الجاي (البوت الحقيقي)</div>
            <div className="text-[14px] font-semibold">{when(next)}</div>
          </div> : <span/>}
          <a href={REAL_PAGE} target="_blank" rel="noopener noreferrer" className="text-[13px] font-semibold text-corona">الصفحة المباشرة بالأسعار اللحظية ←</a>
        </div>
      </>}
    </Card>
  )
}
