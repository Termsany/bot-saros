// Backtest for the portfolio bots (momentum, new-listing short, ratio trend): they trade many coins at once, so instead
// of re-simulating one coin, the page shows the trades of their full historical test (research/bots_stats.py ->
// public/bot-trades.json: every Binance USDT-M perpetual since 2019, coins picked by volume at the time, fees + real
// funding, $20 margin) that were opened inside the chosen dates, with PnL scaled to the chosen margin.
// Each leverage is simulated separately (the protective stop sits before liquidation: 0.8 / leverage); the ratio
// trend has no stop, so it only exists at x2.

type Row = [number, number, string, string, number, number, number, string]   // entry_ts, exit_ts, symbol, side, entry, exit, pnl, reason
type TradesFile = { meta: { to: string; marginUsdt: number; leverages: Record<string, number[]> }, trades: Record<string, Record<string, Row[]>> }

let cache: Promise<TradesFile> | null = null
const load = () => (cache ??= fetch("/bot-trades.json").then(r => { if(!r.ok) throw new Error("bot-trades.json"); return r.json() }))

/** Leverages simulated for a strategy (x2 only for the ratio trend). */
export const PORTFOLIO_LEVERAGES: Record<string, number[]> = { momentum_ls: [1, 2, 3, 5], listing_short: [1, 2, 3, 5], ratio_trend: [2] }

export async function runPortfolioBacktest(opts: { strategy: string; from: string; to: string; amount: number; leverage: number }){
  let file: TradesFile
  try { file = await load() } catch { cache = null; return { ok: false as const, error: "مقدرناش نحمّل صفقات الاختبار — جرّب تاني" } }
  const byLev = file.trades[opts.strategy] || {}
  const lev = byLev[String(opts.leverage)] ? opts.leverage : 2
  const fromMs = Date.parse(opts.from), toMs = Date.parse(opts.to) + 86400000 - 1
  const k = opts.amount / file.meta.marginUsdt          // PnL, fees and funding all scale with the margin
  const rows = (byLev[String(lev)] || []).filter(r => r[0] >= fromMs && r[0] <= toMs)
  const trades = rows.map(([e, x, symbol, side, entry, exit, pnl, reason]) => ({
    entry_ts: new Date(e).toISOString(), exit_ts: new Date(x).toISOString(), symbol, side, entry, exit, qty: 0, pnl: pnl * k, reason,
  }))
  const pnls = trades.map(t => t.pnl)
  const wins = pnls.filter(p => p > 0).length, losses = pnls.length - wins
  const sumWin = pnls.filter(p => p > 0).reduce((s, p) => s + p, 0), sumLoss = Math.abs(pnls.filter(p => p <= 0).reduce((s, p) => s + p, 0))
  // drawdown on the realised curve, in exit order
  let eq = 0, peak = 0, maxDD = 0
  for(const p of [...trades].sort((a, b) => a.exit_ts.localeCompare(b.exit_ts)).map(t => t.pnl)){ eq += p; peak = Math.max(peak, eq); maxDD = Math.max(maxDD, peak - eq) }
  return {
    ok: true as const,
    dataTo: file.meta.to, leverage: lev,
    data: {
      symbol: "PORTFOLIO", timeframe: "1d", portfolio: true,
      stats: {
        total: trades.length, wins, losses, win_rate: trades.length ? wins / trades.length * 100 : 0,
        pnl: pnls.reduce((s, p) => s + p, 0), avg_win: wins ? sumWin / wins : 0, avg_loss: losses ? -sumLoss / losses : 0,
        profit_factor: sumLoss ? sumWin / sumLoss : sumWin ? 99 : 0, max_dd: maxDD,
      },
      trades,
    },
  }
}
