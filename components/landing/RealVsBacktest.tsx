"use client"
// "The real account, next to its backtest": the live basket's closed trades (via /api/realbot) against the
// momentum_ls baseline (lib/demo-baseline.json). Nothing is called a result before SAMPLE closed trades.
import BASELINE from "@/lib/demo-baseline.json"
import { useRealBots } from "@/components/RealMoney"
import { LANDING, type Locale } from "@/lib/i18n/landing"

export const SAMPLE = 30
const B = (BASELINE as any).strategies.momentum_ls.all as { win_rate: number; profit_factor: number; trades: number }

export function RealVsBacktest({ locale }: { locale: Locale }){
  const t = LANDING[locale].proof
  const { bots, state } = useRealBots(30_000)
  const bot = bots.find(b => b.strategy === "momentum_ls")
  const closed = (bot?.history || []).map(h => Number(h.pnl) || 0)
  const n = closed.length, wins = closed.filter(v => v > 0), losses = closed.filter(v => v < 0)
  const gl = -losses.reduce((a, v) => a + v, 0)
  const enough = n >= SAMPLE
  const pending = state === "loading" ? "…" : t.wait(n, SAMPLE)
  const rows: [string, string, string, string?][] = [
    [t.rows.fees, t.feesReal, "0.040%", "text-corona"],
    [t.rows.closed, state === "loading" ? "…" : String(n), B.trades.toLocaleString("en-US")],
    [t.rows.win, enough ? `${(wins.length / n * 100).toFixed(1)}%` : pending, `${B.win_rate}%`, enough ? undefined : "text-faint"],
    [t.rows.pf, enough && gl > 0 ? (wins.reduce((a, v) => a + v, 0) / gl).toFixed(2) : pending, B.profit_factor.toFixed(2), enough ? undefined : "text-faint"],
    [t.rows.edge, "—", t.edgeBt, "text-faint"],
  ]
  return (
    <div className="overflow-hidden rounded-[20px] border border-line bg-surface" data-testid="real-vs-backtest">
      <div className="grid grid-cols-[1.3fr_1fr_1fr] bg-surface2 px-6 py-3 text-[11px] font-semibold uppercase tracking-wide text-faint">
        <span>{t.measure}</span><span>{t.real}</span><span>{t.backtest}</span>
      </div>
      {rows.map(([label, real, bt, cls]) => (
        <div key={label} className="grid grid-cols-[1.3fr_1fr_1fr] items-center border-t border-line px-6 py-4 text-[14px]">
          <span className="font-medium">{label}</span>
          <span className={`font-mono tabular ${cls || "text-ink"}`} dir="ltr" style={{ textAlign: locale === "ar" ? "right" : "left" }}>{real}</span>
          <span className="font-mono tabular text-ink" dir="ltr" style={{ textAlign: locale === "ar" ? "right" : "left" }}>{bt}</span>
        </div>
      ))}
    </div>
  )
}
