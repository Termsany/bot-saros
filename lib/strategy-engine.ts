/**
 * Browser port of the bot's strategies (backtest.py + strategies_advanced.py) and its backtest engine.
 * Must match Python bar-for-bar: research/parity_test checks it against scores computed by the bot.
 * pandas details that matter here: ewm(span) uses adjust=True, rolling std uses ddof=1,
 * NaN comparisons are false, and each score looks at the last WINDOW candles like the live bot.
 */
export type Candle = { ts: number; open: number; high: number; low: number; close: number; vol: number }
export type Strategy = "ichimoku"|"dow"|"gann"|"elliott"|"classical"|"sr"|"rsi_macd"|"smc"|"vwap"|"supertrend"|"bollinger"|"harmonic"|"ict"|"heikin"|"ai"

export const WINDOW = 300
export const WEIGHTS: Record<Strategy, number> = {
  ichimoku:0.10, dow:0.05, gann:0.05, elliott:0.08, classical:0.05, sr:0.05, rsi_macd:0.12, smc:0.10,
  vwap:0.07, supertrend:0.07, bollinger:0.07, harmonic:0.05, ict:0.05, heikin:0.05, ai:0.04,
}
/** Engine settings — keep in sync with CONFIG in backtest.py / bot.py */
export const ENGINE = {
  buyThreshold: 0.35, sellThreshold: -0.35, strongBuy: 0.35, strongSell: -0.35,
  cooldownBars: 3, slPct: 0.03, tpPct: 0.06, warmup: 60, minAdx: 10,
}

const clip = (x: number, lo = -1, hi = 1) => Math.max(lo, Math.min(hi, x))
const last = (a: number[]) => a[a.length - 1]

// ── pandas-equivalent series helpers (return full arrays, NaN where pandas would) ──
function rollingMean(a: number[], n: number): number[]{
  const out = new Array(a.length).fill(NaN)
  for(let i = n - 1; i < a.length; i++){
    let s = 0, ok = true
    for(let j = i - n + 1; j <= i; j++){ if(Number.isNaN(a[j])){ ok = false; break } s += a[j] }
    if(ok) out[i] = s / n
  }
  return out
}
function rollingSum(a: number[], n: number){ return rollingMean(a, n).map(v => v * n) }
function rollingStd(a: number[], n: number): number[]{          // ddof=1
  const m = rollingMean(a, n), out = new Array(a.length).fill(NaN)
  for(let i = n - 1; i < a.length; i++){
    if(Number.isNaN(m[i])) continue
    let s = 0; for(let j = i - n + 1; j <= i; j++) s += (a[j] - m[i]) ** 2
    out[i] = Math.sqrt(s / (n - 1))
  }
  return out
}
function rollingMax(a: number[], n: number){ const o = new Array(a.length).fill(NaN); for(let i = n-1; i < a.length; i++){ let m = -Infinity; for(let j = i-n+1; j <= i; j++) m = Math.max(m, a[j]); o[i] = m } return o }
function rollingMin(a: number[], n: number){ const o = new Array(a.length).fill(NaN); for(let i = n-1; i < a.length; i++){ let m = Infinity; for(let j = i-n+1; j <= i; j++) m = Math.min(m, a[j]); o[i] = m } return o }
function ewm(a: number[], span: number): number[]{              // adjust=True
  const alpha = 2 / (span + 1), out: number[] = []
  let num = 0, den = 0
  for(let i = 0; i < a.length; i++){ num = a[i] + (1 - alpha) * num; den = 1 + (1 - alpha) * den; out.push(num / den) }
  return out
}
const diffPos = (c: number[]) => c.map((v, i) => i === 0 ? 0 : Math.max(0, v - c[i-1]))   // diff().where(>0, 0)
const diffNeg = (c: number[]) => c.map((v, i) => i === 0 ? 0 : Math.max(0, c[i-1] - v))
function trueRange(h: number[], l: number[], c: number[]){
  return h.map((_, i) => i === 0 ? h[0] - l[0] : Math.max(h[i] - l[i], Math.abs(h[i] - c[i-1]), Math.abs(l[i] - c[i-1])))
}
function rsiSimple(c: number[], n = 14){                          // rolling-mean RSI as in the bot
  const g = rollingMean(diffPos(c), n), l = rollingMean(diffNeg(c), n)
  return g.map((gv, i) => { const rs = gv / l[i]; return 100 - 100 / (1 + rs) })   // l=0 -> rs=Inf -> 100; 0/0 -> NaN
}

type W = { o: number[]; h: number[]; l: number[]; c: number[]; v: number[]; ts: number[] }

// ── strategies (backtest.py) ──
function ichimoku({ h, l, c }: W){
  const min9 = rollingMin(l, 9), min26 = rollingMin(l, 26)
  const tenkan = rollingMax(h, 9).map((v, i) => (v + min9[i]) / 2)
  const kijun = rollingMax(h, 26).map((v, i) => (v + min26[i]) / 2)
  const n = c.length, k = n - 1 - 26
  const sa = k >= 0 ? (tenkan[k] + kijun[k]) / 2 : NaN
  const sb = k >= 0 ? (rollingMax(h, 52)[k] + rollingMin(l, 52)[k]) / 2 : NaN
  const p = last(c); let score = 0
  if(p > sa && p > sb) score += 1
  else if(p < sa && p < sb) score -= 1
  score += last(tenkan) > last(kijun) ? 0.5 : -0.5
  return clip(score / 2)
}
function dow({ c }: W){
  const highs: number[] = [], lows: number[] = []
  for(let i = 1; i < c.length - 1; i++){ if(c[i] > c[i-1] && c[i] > c[i+1]) highs.push(c[i]); if(c[i] < c[i-1] && c[i] < c[i+1]) lows.push(c[i]) }
  const hs = highs.slice(-5), ls = lows.slice(-5)
  if(hs.length < 2 || ls.length < 2) return 0
  let hh = 0, hl = 0
  for(let i = 1; i < hs.length; i++) if(hs[i] > hs[i-1]) hh++
  for(let i = 1; i < ls.length; i++) if(ls[i] > ls[i-1]) hl++
  return clip((hh + hl) / 8 * 2 - 1)
}
function gann({ h, l, c }: W){
  const hi = last(rollingMax(h, 50)), lo = last(rollingMin(l, 50)), rng = hi !== lo ? hi - lo : 1
  const slope = (last(c) - c[c.length - 10]) / 10, avg = rng / 50
  return clip(slope / avg) * 0.7
}
function pivots5(c: number[]){
  const p: { v: number; t: "H"|"L" }[] = []
  for(let i = 2; i < c.length - 2; i++){
    if(c[i] > c[i-1] && c[i] > c[i-2] && c[i] > c[i+1] && c[i] > c[i+2]) p.push({ v: c[i], t: "H" })
    if(c[i] < c[i-1] && c[i] < c[i-2] && c[i] < c[i+1] && c[i] < c[i+2]) p.push({ v: c[i], t: "L" })
  }
  return p
}
function elliott({ c }: W){
  const pv = pivots5(c).slice(-9)
  if(pv.length < 5) return 0
  const H = pv.filter(p => p.t === "H").map(p => p.v), L = pv.filter(p => p.t === "L").map(p => p.v)
  if(!H.length || !L.length) return 0
  const lastH = Math.max(...H), lastL = Math.min(...L), price = last(c), prev = c[c.length - 2]
  const f05 = lastH - (lastH - lastL) * 0.5, f618 = lastH - (lastH - lastL) * 0.618
  if(f618 < price && price < f05 && price > prev) return 0.8
  if(price < f618 && price < prev) return -0.6
  if(price > lastH) return 0.5
  return 0.1
}
function classical({ c }: W){
  const sma20 = last(rollingMean(c, 20)), sma50 = last(rollingMean(c, 50)), price = last(c)
  let score = 0
  if(price > sma20 && sma20 > sma50) score += 0.6
  else if(price < sma20 && sma20 < sma50) score -= 0.6
  if(c.length >= 20){
    const y = c.slice(-20); let sx = 0, sy = 0, sxy = 0, sxx = 0
    y.forEach((v, x) => { sx += x; sy += v; sxy += x * v; sxx += x * x })
    const slope = (20 * sxy - sx * sy) / (20 * sxx - sx * sx)
    score += clip(slope / (price * 0.002), -0.4, 0.4)
  }
  return clip(score)
}
/** round(x, 6) on a pandas value (numpy.float64): numpy scales first, then rounds half to even
 *  (plain Python float rounding would differ on ties). */
function round6(x: number){
  const y = x * 1e6, f = Math.floor(y), d = y - f
  const r = d > 0.5 ? f + 1 : d < 0.5 ? f : (f % 2 === 0 ? f : f + 1)
  return r / 1e6
}
function sr({ h, l, c }: W){
  const price = last(c), hi: number[] = [], lo: number[] = []
  for(let i = 2; i < h.length - 2; i++){
    if(h[i] === Math.max(...h.slice(i - 2, i + 3))) hi.push(h[i])
    if(l[i] === Math.min(...l.slice(i - 2, i + 3))) lo.push(l[i])
  }
  const sups = lo.slice(-6).map(round6), ress = hi.slice(-6).map(round6)
  const below = sups.filter(x => x < price), above = ress.filter(x => x > price)
  const sup = below.length ? Math.max(...below) : null, res = above.length ? Math.min(...above) : null
  if(sup && (price - sup) / price < 0.015) return 0.7
  if(res && (res - price) / price < 0.015) return -0.7
  if(sup && res) return clip((price - (sup + res) / 2) / (res - sup) * 0.3, -0.3, 0.3)
  return 0
}
function rsiMacd({ c }: W){
  const r = last(rsiSimple(c))
  const e26 = ewm(c, 26), macd = ewm(c, 12).map((v, i) => v - e26[i]), sig = ewm(macd, 9)
  const hist = macd.map((v, i) => v - sig[i])
  let score = 0
  if(r < 30) score += 0.8; else if(r > 70) score -= 0.8; else if(r < 40) score += 0.3; else if(r > 60) score -= 0.3
  score += last(hist) > 0 ? 0.5 : -0.5
  return clip(score)
}

// ── strategies (strategies_advanced.py) ──
function smc({ h, l, c }: W){
  const price = last(c), n = c.length, highs: number[] = [], lows: number[] = []
  for(let i = 2; i < n - 2; i++){
    if(c[i] === Math.max(...c.slice(i - 2, i + 3))) highs.push(c[i])
    if(l[i] === Math.min(...l.slice(i - 2, i + 3))) lows.push(l[i])
  }
  const H = highs.slice(-4), L = lows.slice(-4); let score = 0
  if(H.length >= 2 && price > H[H.length - 2]) score += 0.5
  else if(L.length >= 2 && price < L[L.length - 2]) score -= 0.5
  if(l[n-1] > h[n-3] && c[n-1] > c[n-2]) score += 0.4
  else if(h[n-1] < l[n-3] && c[n-1] < c[n-2]) score -= 0.4
  if(L.length && n >= 5 && c[n-2] < c[n-3] && c[n-1] > c[n-2] && (price - L[L.length - 1]) / price < 0.02) score += 0.3
  return clip(score)
}
function vwap({ h, l, c, v }: W){
  const typ = h.map((x, i) => (x + l[i] + c[i]) / 3)
  const vw = last(rollingSum(typ.map((t, i) => t * v[i]), 20)) / last(rollingSum(v, 20))
  const price = last(c); let score = price > vw ? 0.5 : -0.5
  const m = last(rollingMean(v, 20)), vr = m ? last(v) / m : 1   // NaN is truthy in Python: v/NaN -> NaN
  if(vr > 1.8 && score > 0) score += 0.3
  else if(vr > 1.8 && score < 0) score -= 0.3
  return clip(score)
}
function supertrend({ h, l, c }: W){
  const atr = rollingMean(h.map((x, i) => x - l[i]), 10), e = ewm(c, 10), price = last(c)
  if(price > last(e) + last(atr) * 1.5) return 0.7
  if(price < last(e) - last(atr) * 1.5) return -0.7
  return 0
}
function bollinger({ c }: W){
  const sma = rollingMean(c, 20), sd = rollingStd(c, 20)
  const upper = last(sma) + 2 * last(sd), lower = last(sma) - 2 * last(sd), price = last(c)
  const rr = last(rsiSimple(c)), r = Number.isNaN(rr) ? 50 : rr
  if(price > upper && r > 60) return 0.8
  if(price < lower && r < 40) return -0.8
  if(r < 30) return 0.4
  if(r > 70) return -0.4
  return 0
}
function harmonic({ c }: W){
  const pv = pivots5(c).slice(-5)
  if(pv.length < 4) return 0
  const [p0, p1, p2, p3] = pv.slice(-4)
  const xa = Math.abs(p1.v - p0.v), ab = Math.abs(p2.v - p1.v), ret = xa ? ab / xa : 0, price = last(c)
  if(ret >= 0.618 && ret <= 0.786){
    if(p3.t === "L" && price > p3.v * 1.01) return 0.6
    if(p3.t === "H" && price < p3.v * 0.99) return -0.6
  }
  return 0
}
function ict({ h, l, c, ts }: W){
  const hour = new Date(last(ts)).getUTCHours(), inKill = (hour >= 7 && hour <= 10) || (hour >= 12 && hour <= 15)
  const n = c.length, hi = rollingMax(h, 20)[n - 2], lo = rollingMin(l, 20)[n - 2], price = last(c)
  if(price > hi && inKill) return -0.5
  if(price < lo && inKill) return 0.5
  return 0
}
function heikin({ o, h, l, c }: W){
  const haC = o.map((x, i) => (x + h[i] + l[i] + c[i]) / 4), haO = [o[0]]
  for(let i = 1; i < c.length; i++) haO.push((haO[i-1] + haC[i-1]) / 2)
  const atr = rollingMean(trueRange(h, l, c), 14)
  const pdm = rollingMean(diffPos(c), 14).map((v, i) => v / atr[i] * 100), mdm = rollingMean(diffNeg(c), 14).map((v, i) => v / atr[i] * 100)
  const adx = rollingMean(pdm.map((v, i) => Math.abs(v - mdm[i])), 14)
  const n = c.length; let score = 0
  if(haC[n-1] > haO[n-1] && haC[n-2] > haO[n-2]) score += 0.5
  else if(haC[n-1] < haO[n-1] && haC[n-2] < haO[n-2]) score -= 0.5
  const a = Number.isNaN(last(adx)) ? 15 : last(adx)
  if(a > 25 && score > 0) score += 0.3
  else if(a > 25 && score < 0) score -= 0.3
  else if(a < 15) score *= 0.5
  return clip(score)
}
function ai(base: Record<string, number>){
  const vals = Object.values(base); if(!vals.length) return 0
  const avg = vals.reduce((s, x) => s + x, 0) / vals.length
  const pos = vals.filter(x => x > 0.2).length, neg = vals.filter(x => x < -0.2).length
  let score = avg
  if(pos >= 4 && avg > 0) score = Math.min(1, avg * 1.3)
  else if(neg >= 4 && avg < 0) score = Math.max(-1, avg * 1.3)
  return clip(score)
}

const FNS: Record<Exclude<Strategy, "ai">, (w: W) => number> = {
  ichimoku, dow, gann, elliott, classical, sr, rsi_macd: rsiMacd, smc, vwap, supertrend, bollinger, harmonic, ict, heikin,
}
export const STRATEGY_IDS = [...Object.keys(FNS), "ai"] as Strategy[]

function toWindow(candles: Candle[], end: number): W{
  const s = Math.max(0, end - WINDOW + 1), part = candles.slice(s, end + 1)
  return { o: part.map(x => x.open), h: part.map(x => x.high), l: part.map(x => x.low), c: part.map(x => x.close), v: part.map(x => x.vol), ts: part.map(x => x.ts) }
}
/** Scores of the requested strategies at candle `end` (AI needs all 14 others). */
export function scoresAt(candles: Candle[], end: number, ids: Strategy[] = STRATEGY_IDS): Partial<Record<Strategy, number>>{
  const w = toWindow(candles, end), out: Partial<Record<Strategy, number>> = {}
  const need = ids.includes("ai") ? (Object.keys(FNS) as Exclude<Strategy,"ai">[]) : ids.filter((x): x is Exclude<Strategy,"ai"> => x !== "ai")
  for(const k of need){ const v = FNS[k](w); out[k] = Number.isNaN(v) ? 0 : v }
  if(ids.includes("ai")) out.ai = ai(out as Record<string, number>)
  return out
}

// ── engine filters (backtest.py adx_value_bt / regime_detect_bt) ──
function adxValue(c: number[], h: number[], l: number[]){
  const atr = rollingMean(trueRange(h, l, c), 14)
  const p = rollingMean(diffPos(c), 14).map((v, i) => v / atr[i] * 100), m = rollingMean(diffNeg(c), 14).map((v, i) => v / atr[i] * 100)
  const dx = p.map((v, i) => { const s = v + m[i]; return s === 0 ? NaN : Math.abs(v - m[i]) / s * 100 })
  const a = last(rollingMean(dx, 14)); return Number.isNaN(a) ? 20 : a
}
function regime(c: number[], h: number[], l: number[]){
  const adx = adxValue(c, h, l), sma = last(rollingMean(c, 20)), sd = last(rollingStd(c, 20))
  const bw = !Number.isNaN(sma) && sma !== 0 ? sd / sma : 0.02
  if(adx > 20 && bw > 0.015) return "trend"
  if(adx < 15 || bw < 0.01) return "range"
  return "mixed"
}

export type EngineTrade = { entry_ts: number; exit_ts: number; side: "long"|"short"; entry: number; exit: number; qty: number; pnl: number; reason: string }

/** Same loop as backtest.py run_backtest (one position at a time, fixed SL/TP, breakeven at 50%, fees).
 *  startTs: candles before it are history for the indicators only — no entries there. */
export function runEngine(candles: Candle[], enabled: Strategy[], amount: number, leverage: number, fee = 0.0004, cfg = ENGINE, startTs = 0){
  const wsum = enabled.reduce((s, k) => s + (WEIGHTS[k] || 0), 0) || 1
  const trades: EngineTrade[] = []
  let pos: { side: "long"|"short"; entry: number; qty: number; sl: number; tp: number; ts: number; be: boolean } | null = null
  let lastExit = -1e9
  const C = candles.map(x => x.close), H = candles.map(x => x.high), L = candles.map(x => x.low)
  for(let i = cfg.warmup; i < candles.length; i++){
    const price = C[i], ts = candles[i].ts
    const sc = scoresAt(candles, i, enabled)
    const total = enabled.reduce((s, k) => s + (sc[k] ?? 0) * (WEIGHTS[k] || 0), 0) / wsum
    if(pos){
      let hit = false, exit = price, reason = ""
      if(pos.side === "long"){
        if(L[i] <= pos.sl){ hit = true; exit = pos.sl; reason = "SL" }
        else if(H[i] >= pos.tp){ hit = true; exit = pos.tp; reason = "TP" }
        else if(total < cfg.strongSell){ hit = true; reason = "reverse" }
      } else {
        if(H[i] >= pos.sl){ hit = true; exit = pos.sl; reason = "SL" }
        else if(L[i] <= pos.tp){ hit = true; exit = pos.tp; reason = "TP" }
        else if(total > cfg.strongBuy){ hit = true; reason = "reverse" }
      }
      if(hit){
        const q = pos.qty
        const pnl = (pos.side === "long" ? (exit - pos.entry) * q : (pos.entry - exit) * q) - (pos.entry * q + exit * q) * fee
        trades.push({ entry_ts: pos.ts, exit_ts: ts, side: pos.side, entry: pos.entry, exit, qty: q, pnl, reason })
        pos = null; lastExit = i; continue
      }
      // breakeven after this bar's SL/TP check, so the new SL only counts from the next bar
      if(!pos.be){
        const trig = pos.entry + (pos.tp - pos.entry) * 0.5
        if(pos.side === "long" ? H[i] >= trig : L[i] <= trig){
          const be = pos.side === "long" ? pos.entry * 1.001 : pos.entry * 0.999
          if(pos.side === "long" && be > pos.sl) pos.sl = be
          if(pos.side === "short" && be < pos.sl) pos.sl = be
          pos.be = true
        }
      }
      continue
    }
    if(ts < startTs || i - lastExit <= cfg.cooldownBars) continue
    const side = total > cfg.buyThreshold ? "long" : total < cfg.sellThreshold ? "short" : null
    if(!side) continue
    const c = C.slice(0, i + 1), h = H.slice(0, i + 1), l = L.slice(0, i + 1)
    const tail = Math.max(0, c.length - 120)   // ADX/regime only depend on the last ~42 bars
    if(adxValue(c.slice(tail), h.slice(tail), l.slice(tail)) < cfg.minAdx) continue
    if(regime(c.slice(tail), h.slice(tail), l.slice(tail)) === "range" && Math.abs(total) < 0.30) continue
    const qty = amount * leverage / price
    pos = { side, entry: price, qty, ts, be: false,
      sl: side === "long" ? price * (1 - cfg.slPct) : price * (1 + cfg.slPct),
      tp: side === "long" ? price * (1 + cfg.tpPct) : price * (1 - cfg.tpPct) }
  }
  if(pos){
    const price = C[C.length - 1], q = pos.qty
    const pnl = (pos.side === "long" ? (price - pos.entry) * q : (pos.entry - price) * q) - (pos.entry * q + price * q) * fee
    trades.push({ entry_ts: pos.ts, exit_ts: candles[candles.length - 1].ts, side: pos.side, entry: pos.entry, exit: price, qty: q, pnl, reason: "close" })
  }
  return trades
}
