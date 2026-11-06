"use client"
// The hero's live card: the real-money basket as https://realbot.da3m.io shows it (via /api/realbot), never a sample.
import { useRealBots } from "@/components/RealMoney"
import { LANDING, type Locale } from "@/lib/i18n/landing"

const money = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}$${Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
const coin = (s: string) => s.split(":")[0]

export function nextRebalanceText(iso: string, locale: Locale){
  const d = new Date(iso)
  return locale === "ar"
    ? d.toLocaleString("ar-EG", { weekday: "long", hour: "2-digit", minute: "2-digit", timeZone: "Africa/Cairo", numberingSystem: "latn" }) + " بتوقيت مصر"
    : d.toLocaleString("en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "UTC" }) + " UTC"
}

export function LiveRealCard({ locale, href }: { locale: Locale; href: string }){
  const t = LANDING[locale].live
  const { bots, state } = useRealBots(20_000)
  const bot = bots.find(b => b.strategy === "momentum_ls") || bots[0]
  const legs = (bot?.positions || []).map(p => ({ ...p, pnl: Number(p.pnl) || 0, margin: (p.entry * p.qty * (p.contract_size || 1)) / (bot?.leverage || 2) }))
  const open = legs.reduce((a, p) => a + p.pnl, 0)
  const top = [...legs].sort((a, b) => Math.abs(b.pnl) - Math.abs(a.pnl)).slice(0, 3)
  const maxAbs = Math.max(1e-9, ...legs.map(p => Math.abs(p.pnl)))
  return (
    <a href={href} target="_blank" rel="noopener" data-testid="live-card"
      className="group block w-full rounded-3xl border border-line bg-surface p-6 shadow-[0_24px_60px_-30px_rgba(0,0,0,.55)] transition duration-300 hover:-translate-y-0.5 hover:border-line2 lg:w-[520px]">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-[19px] font-semibold">{t.title}</div>
          <div className="mt-0.5 text-[12px] text-faint">{bot ? t.legs(legs.length) : " "}</div>
        </div>
        {bot && <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-semibold ${bot.running ? "border-profit/35 bg-profit/10 text-profit" : "border-line bg-surface2 text-muted"}`}>
          <i className={`h-1.5 w-1.5 rounded-full ${bot.running ? "bg-profit" : "bg-faint"}`}/>{bot.running ? t.running : t.stopped}</span>}
      </div>
      {state === "loading" && !bot && <p className="py-16 text-center text-[13px] text-faint">{t.loading}</p>}
      {state === "error" && !bot && <p className="py-16 text-center text-[13px] text-faint">{t.error}</p>}
      {bot && <>
        <div className="mt-4 flex items-baseline gap-2.5" dir="ltr" style={{ justifyContent: locale === "ar" ? "flex-end" : "flex-start" }}>
          <span className={`font-mono text-[40px] font-bold leading-none tabular ${open >= 0 ? "text-profit" : "text-loss"}`}>{money(open)}</span>
          <span className="text-[12px] text-faint">{t.openPnl}</span>
        </div>
        {/* every leg's P&L, longest bar = biggest move: the basket at a glance */}
        <div className="mt-5 flex h-[86px] items-center gap-[5px]" dir="ltr" aria-hidden>
          {legs.map(p => {
            const h = `${Math.max(4, Math.abs(p.pnl) / maxAbs * 100)}%`
            return (
              <div key={p.symbol} className="flex h-full flex-1 flex-col" title={`${coin(p.symbol)} ${money(p.pnl)}`}>
                <div className="flex flex-1 items-end">{p.pnl >= 0 && <div className="w-full rounded-t-[3px] bg-profit/80 transition-all duration-500" style={{ height: h }}/>}</div>
                <div className="h-px bg-line2"/>
                <div className="flex flex-1 items-start">{p.pnl < 0 && <div className="w-full rounded-b-[3px] bg-loss/80 transition-all duration-500" style={{ height: h }}/>}</div>
              </div>
            )
          })}
        </div>
        <div className="mt-4 overflow-hidden rounded-2xl border border-line">
          {top.map(p => (
            <div key={p.symbol} className="flex items-center justify-between gap-3 border-t border-line bg-surface2/45 px-4 py-2.5 first:border-t-0">
              <div className="flex items-center gap-2.5" dir="ltr">
                <span className="text-[13px] font-semibold">{coin(p.symbol)}</span>
                <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${p.side === "long" ? "bg-profit/10 text-profit" : "bg-loss/10 text-loss"}`}>{p.side.toUpperCase()}</span>
              </div>
              <div className="flex items-center gap-3" dir="ltr">
                <span className={`font-mono text-[14px] tabular ${p.pnl >= 0 ? "text-profit" : "text-loss"}`}>{money(p.pnl)}</span>
                <span className="font-mono text-[11px] text-faint tabular">{p.margin ? `${p.pnl >= 0 ? "+" : ""}${(p.pnl / p.margin * 100).toFixed(1)}%` : ""}</span>
              </div>
            </div>
          ))}
        </div>
        <div className="mt-4 flex flex-wrap items-center justify-between gap-2 text-[12px]">
          <span className="text-muted">{bot.next_rebalance ? <>{t.next} · <span dir="ltr">{nextRebalanceText(bot.next_rebalance, locale)}</span></> : t.more(Math.max(0, legs.length - 3))}</span>
          <span className="font-semibold text-corona">{t.stops}</span>
        </div>
      </>}
    </a>
  )
}
