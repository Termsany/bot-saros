/**
 * Wave Flats (Regular / Running / Expanded Flat) — browser port of strategies_wave.py, which ports the
 * Pine Script strategy. Keep both identical: research/parity.ts compares them trade by trade.
 * Entries fill at the next candle's open; stops/targets fill inside the candle like TradingView's broker emulator.
 * No higher-timeframe filter (the Pine option is off — see strategies_wave.py).
 */
import type { Candle, EngineTrade } from "./strategy-engine"

export const TF_SEC: Record<string, number> = { "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400, "1d": 86400, "1w": 604800 }
const ZONE_FROM = 0.382, ZONE_TO = 0.236, TARGET = 1.272
const FIBS = [0.236, 0.382, 0.5, 0.618, 0.786]
const MAX_B = 1.272, TP1 = 1.414, TP2 = 1.618, TP1_PCT = 50
const STOP_BUF = 0.2, PIN_RATIO = 2.0, MAX_BARS = 300

const presetDev = (s: number) => s <= 900 ? 1.5 : s <= 3600 ? 3.0 : s <= 14400 ? 5.0 : s <= 86400 ? 8.0 : 15.0
const presetMove = (s: number) => s <= 900 ? 4.0 : s <= 3600 ? 8.0 : s <= 14400 ? 15.0 : s <= 86400 ? 25.0 : 40.0
const above = (a: number, b: number, d: number) => d * (a - b) > 0

type Setup = { dir: number; active: boolean; phase: number; touched: boolean; p0: number; p1: number; aExt: number | null; bExt: number | null; cExt: number | null; startB: number }
type Tr = { dir: number; kind: string; stop: number; two: boolean; tp1Hit: boolean; tgt1: number; tgt2: number | null; be: number; beDone: boolean }
type Pos = { dir: number; entry: number; qty: number; left: number; pnl: number; exitVal: number; entryTs: number; kind: string; legs: string[] }
export type WaveTrade = EngineTrade & { kind: string }

const lvl = (s: Setup, x: number) => s.p0 + x * (s.p1 - s.p0)
const newSetup = (dir: number): Setup => ({ dir, active: false, phase: 1, touched: false, p0: 0, p1: 0, aExt: null, bExt: null, cExt: null, startB: 0 })

export function runWaveFlats(candles: Candle[], timeframe: string, amount = 20, leverage = 5, fee = 0.0004, startTs = 0): WaveTrade[]{
  const o = candles.map(x => x.open), h = candles.map(x => x.high), l = candles.map(x => x.low), c = candles.map(x => x.close), ts = candles.map(x => x.ts)
  const n = c.length, sec = TF_SEC[timeframe], dev = presetDev(sec), mv = presetMove(sec)
  let zzDir = 1, extP: number | null = null, extB = 0
  let pivH: number | null = null, pivHB = 0, pivL: number | null = null, pivLB = 0
  const shortS = newSetup(-1), longS = newSetup(1)
  const trades: WaveTrade[] = []
  let pending: { dir: number, kind: string } | null = null, pos: Pos | null = null
  let tr: Tr = { dir: 0, kind: "", stop: 0, two: false, tp1Hit: false, tgt1: 0, tgt2: null, be: 0, beDone: true }

  const closeLeg = (p: Pos, qty: number, price: number) => {
    p.pnl += (price - p.entry) * qty * p.dir - (p.entry * qty + price * qty) * fee; p.left -= qty; p.exitVal += price * qty
  }
  const finish = (p: Pos, exitTs: number): WaveTrade => ({
    entry_ts: p.entryTs, exit_ts: exitTs, side: p.dir === 1 ? "long" : "short", entry: p.entry, exit: p.exitVal / p.qty,
    qty: p.qty, pnl: p.pnl, reason: p.legs.join("+"), kind: p.kind,
  })

  const process = (s: Setup, i: number, inPos: boolean, blocked: boolean): boolean => {
    if(!(s.active && i > s.startB)) return false
    const d = s.dir
    const hiX = d === 1 ? h[i] : l[i], loX = d === 1 ? l[i] : h[i]
    const ext2 = d === 1 ? Math.min(l[i], l[i-1]) : Math.max(h[i], h[i-1])
    const body = Math.abs(c[i] - o[i]), rng = h[i] - l[i], minBody = Math.max(body, rng * 0.05)
    const upW = h[i] - Math.max(o[i], c[i]), loW = Math.min(o[i], c[i]) - l[i]
    const engulf = d === 1 ? (c[i] > o[i] && c[i-1] < o[i-1] && c[i] >= o[i-1] && o[i] <= c[i-1])
                           : (c[i] < o[i] && c[i-1] > o[i-1] && c[i] <= o[i-1] && o[i] >= c[i-1])
    const pin = d === 1 ? (rng > 0 && loW >= PIN_RATIO * minBody && loW >= rng * 0.5 && upW <= loW * 0.5)
                        : (rng > 0 && upW >= PIN_RATIO * minBody && upW >= rng * 0.5 && loW <= upW * 0.5)
    const zFar = lvl(s, ZONE_FROM), zNear = lvl(s, ZONE_TO)
    const canEnter = (engulf || pin) && !inPos && !blocked && ts[i] >= startTs
    let kill = false, kind = ""
    if(!above(loX, s.p0, d)) kill = true
    else if(s.phase === 1){
      if(!s.touched && above(hiX, s.p1, d)) s.p1 = hiX
      else {
        if(!above(loX, zFar, d)) s.touched = true
        if(s.touched && (s.aExt === null || !above(loX, s.aExt, d))) s.aExt = loX
        if(s.touched && above(hiX, s.p1, d)){ s.phase = 2; s.startB = i; s.bExt = hiX }
        else if(s.touched && canEnter && !above(ext2, zFar, d) && above(c[i], zNear, d)) kind = "Regular Flat"
      }
    } else {
      if(!above(lvl(s, MAX_B), hiX, d)) kill = true
      else {
        if(above(hiX, s.bExt!, d)) s.bExt = hiX
        if(s.cExt === null || !above(loX, s.cExt, d)) s.cExt = loX
        if(canEnter){
          if(!above(s.cExt, s.aExt!, d)) kind = "Expanded Flat"
          else if(FIBS.some(f => !above(ext2, lvl(s, f), d) && above(c[i], lvl(s, f), d))) kind = "Running Flat"
        }
      }
    }
    let entered = false
    if(kind){
      const flat = s.phase === 2
      tr = { dir: d, kind, stop: ext2 * (1 - d * STOP_BUF / 100), two: flat, tp1Hit: false,
        tgt1: flat ? lvl(s, TP1) : lvl(s, TARGET), tgt2: flat ? lvl(s, TP2) : null, be: flat ? s.bExt! : s.p1, beDone: false }
      s.active = false; entered = true
    }
    if(s.active && i - s.startB > MAX_BARS) kill = true
    if(kill && s.active) s.active = false
    return entered
  }

  for(let i = 0; i < n; i++){
    // fills inside candle i (orders placed at candle i-1's close)
    if(pending){
      const qty = amount * leverage / o[i]
      pos = { dir: pending.dir, entry: o[i], qty, left: qty, pnl: 0, exitVal: 0, entryTs: ts[i], kind: pending.kind, legs: [] }
      pending = null
    }
    if(pos){
      const d = pos.dir
      const path = (h[i] - o[i]) < (o[i] - l[i]) ? [o[i], h[i], l[i], c[i]] : [o[i], l[i], h[i], c[i]]
      for(let seg = 0; seg < 3 && pos; seg++){
        const a = path[seg], b = path[seg + 1], lo = Math.min(a, b), hi = Math.max(a, b)
        const orders: [string, number][] = [["SL", tr.stop]]
        if(tr.two){ if(!tr.tp1Hit) orders.push(["TP1", tr.tgt1]); orders.push(["TP2", tr.tgt2!]) }
        else orders.push(["TP", tr.tgt1])
        const hits: [number, string, number][] = []
        for(const [name, px] of orders){
          const isStop = name === "SL"
          const trig = isStop ? ((d === 1 && b < a) || (d === -1 && b > a)) && lo <= px && px <= hi
                              : ((d === 1 && b > a) || (d === -1 && b < a)) && lo <= px && px <= hi
          const gap = isStop ? (d === 1 ? a <= px : a >= px) : (d === 1 ? a >= px : a <= px)
          if(gap) hits.push([0, name, a])
          else if(trig) hits.push([Math.abs(px - a), name, px])
        }
        hits.sort((x, y) => x[0] - y[0])
        for(const [, name, px] of hits){
          if(!pos) break
          if(name === "TP1"){ closeLeg(pos, pos.qty * TP1_PCT / 100, px); pos.legs.push("TP1"); tr.tp1Hit = true }
          else { closeLeg(pos, pos.left, px); pos.legs.push(name); trades.push(finish(pos, ts[i])); pos = null }
        }
      }
    }
    // script at candle i's close
    let newLow = false, newHigh = false, newLowP = 0, newLowB = 0, newHighP = 0, newHighB = 0
    if(extP === null){ extP = h[i]; extB = i }
    else if(zzDir === 1){
      if(h[i] >= extP){ extP = h[i]; extB = i }
      else if(l[i] <= extP * (1 - dev / 100)){
        newHigh = true; newHighP = extP; newHighB = extB
        pivH = extP; pivHB = extB; zzDir = -1; extP = l[i]; extB = i
      }
    } else {
      if(l[i] <= extP){ extP = l[i]; extB = i }
      else if(h[i] >= extP * (1 + dev / 100)){
        newLow = true; newLowP = extP; newLowB = extB
        pivL = extP; pivLB = extB; zzDir = 1; extP = h[i]; extB = i
      }
    }
    const start = (s: Setup, p0: number, p1: number) => Object.assign(s, { active: true, phase: 1, touched: false, p0, p1, aExt: null, bExt: null, cExt: null, startB: i })
    if(newLow && !shortS.active && pivH !== null && pivHB < newLowB && (pivH - newLowP) / pivH * 100 >= mv) start(shortS, pivH, newLowP)
    if(newHigh && !longS.active && pivL !== null && pivLB < newHighB && (newHighP - pivL) / pivL * 100 >= mv) start(longS, pivL, newHighP)

    const inPos = pos !== null
    const enteredShort = process(shortS, i, inPos, false)
    const enteredLong = process(longS, i, inPos, enteredShort)
    if((enteredShort || enteredLong) && i + 1 < n) pending = { dir: tr.dir, kind: tr.kind }

    // breakeven at the close (takes effect from the next candle)
    if(pos && !tr.beDone){
      const d = pos.dir
      if(above(d === 1 ? h[i] : l[i], tr.be, d)){ tr.stop = pos.entry; tr.beDone = true }
    }
  }
  if(pos){ closeLeg(pos, pos.left, c[n-1]); pos.legs.push("close"); trades.push(finish(pos, ts[n-1])) }
  return trades
}
