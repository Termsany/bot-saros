/**
 * Daily trend following with volatility-sized entries — browser port of strategies_trend.py.
 * Keep both identical: research/trend_parity.ts compares them trade by trade.
 * On at a daily close when the close is above the close 20, 60 and 120 days ago for at least 2 of the 3;
 * buy at the next open (size = margin × leverage × min(1, 80% / 30-day volatility)), sell at the next open
 * once it is off, protective stop at entry × (1 − 0.8 / leverage). Long only; fees + funding included.
 */
import type { Candle, EngineTrade } from "./strategy-engine"

const LOOKBACKS = [20, 60, 120], VOL_DAYS = 30, VOL_TARGET = 0.8, STOP_SHARE = 0.8
export const TREND_WARMUP = 150   // daily candles needed before the first signal
export type TrendTrade = EngineTrade & { kind: string }

const trendOn = (c: number[], i: number) => i >= Math.max(...LOOKBACKS) && LOOKBACKS.filter(L => c[i] > c[i - L]).length >= 2
function sizeFactor(c: number[], i: number){
  const r: number[] = []
  for(let k = i - VOL_DAYS + 1; k <= i; k++) r.push(c[k] / c[k - 1] - 1)
  const m = r.reduce((s, x) => s + x, 0) / r.length
  const v = Math.sqrt(r.reduce((s, x) => s + (x - m) ** 2, 0) / (r.length - 1)) * Math.sqrt(365)
  return v > 0 ? Math.min(1, VOL_TARGET / v) : 1
}

/** funding[i] = funding rate paid over candle i (sum of its payments); omit for none. */
export function runTrendDaily(candles: Candle[], funding?: number[], amount = 20, leverage = 2, fee = 0.0004, startTs = 0): TrendTrade[]{
  const o = candles.map(x => x.open), l = candles.map(x => x.low), c = candles.map(x => x.close), ts = candles.map(x => x.ts)
  const n = c.length, trades: TrendTrade[] = []
  let pos: { entry: number, qty: number, ts: number, funding: number, stop: number } | null = null
  let pending: "buy" | "sell" | null = null, pendSize = 1
  const close = (price: number, exitTs: number, reason: string): TrendTrade => {
    const p = pos!, q = p.qty
    return { entry_ts: p.ts, exit_ts: exitTs, side: "long", entry: p.entry, exit: price, qty: q,
      pnl: (price - p.entry) * q - (p.entry * q + price * q) * fee - p.funding, reason, kind: "Trend" }
  }
  for(let i = 0; i < n; i++){
    if(pending === "buy"){
      const qty = amount * leverage * pendSize / o[i]
      pos = { entry: o[i], qty, ts: ts[i], funding: 0, stop: o[i] * (1 - STOP_SHARE / leverage) }
    } else if(pending === "sell" && pos){ trades.push(close(o[i], ts[i], "signal off")); pos = null }
    pending = null
    if(pos){
      if(l[i] <= pos.stop){ trades.push(close(Math.min(o[i], pos.stop), ts[i], "stop")); pos = null }
      else if(funding) pos.funding += pos.qty * c[i] * funding[i]
    }
    // decision at candle i's close
    if(i + 1 < n && i >= VOL_DAYS){
      const on = trendOn(c, i)
      if(!pos && on && ts[i] >= startTs){ pending = "buy"; pendSize = sizeFactor(c, i) }
      else if(pos && !on) pending = "sell"
    }
  }
  if(pos) trades.push(close(c[n-1], ts[n-1], "close"))
  return trades
}
