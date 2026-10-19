// Browser backtest: fetches the requested date range (+ history for the indicators) and runs the
// bot's own strategies and engine (lib/strategy-engine.ts, checked bar-for-bar against the Python bot).
import { runEngine, WINDOW, type Candle, type EngineTrade, type Strategy } from "./strategy-engine"

const TF_MS: Record<string, number> = { "15m": 15*60000, "1h": 3600000, "4h": 4*3600000, "1d": 86400000 }
const MAX_CANDLES = 12000   // ~4 months of 15m, or years of 4h — keeps the browser responsive
function toBybitInterval(tf: string){ const m: Record<string,string> = { "15m":"15","1h":"60","4h":"240","1d":"D" }; return m[tf]||"60" }

/** Candles covering [startMs, endMs], oldest first. Bybit, then Binance — both page by time. */
export async function fetchCandles(symbol: string, timeframe: string, startMs: number, endMs: number): Promise<Candle[]>{
  const sym = symbol.replace("/","")
  const tf = TF_MS[timeframe] || 3600000
  const want = Math.min(MAX_CANDLES, Math.ceil((endMs - startMs) / tf) + 1)
  const clean = (rows: Candle[]) => {
    const seen = new Set<number>()
    return rows.filter(c => c.ts >= startMs && c.ts <= endMs && !seen.has(c.ts) && seen.add(c.ts)).sort((a, b) => a.ts - b.ts).slice(-want)
  }
  // Bybit: newest first, up to 1000 per page — walk backwards from endMs
  try{
    const out: Candle[] = []; let end = endMs
    for(let page = 0; page < 20 && out.length < want; page++){
      const r = await fetch(`https://api.bybit.com/v5/market/kline?category=linear&symbol=${sym}&interval=${toBybitInterval(timeframe)}&start=${startMs}&end=${end}&limit=1000`)
      if(!r.ok) break
      const list = (await r.json())?.result?.list
      if(!Array.isArray(list) || !list.length) break
      for(const k of list) out.push({ ts: Number(k[0]), open: +k[1], high: +k[2], low: +k[3], close: +k[4], vol: +k[5] })
      const oldest = Number(list[list.length - 1][0])
      if(oldest <= startMs || list.length < 1000) break
      end = oldest - 1
    }
    if(out.length) return clean(out)
  }catch{}
  // Binance: oldest first, up to 1000 per page — walk forwards from startMs
  try{
    const out: Candle[] = []; let start = startMs
    for(let page = 0; page < 20 && out.length < want; page++){
      const r = await fetch(`https://api.binance.com/api/v3/klines?symbol=${sym}&interval=${timeframe}&startTime=${start}&endTime=${endMs}&limit=1000`)
      if(!r.ok) break
      const raw = await r.json()
      if(!Array.isArray(raw) || !raw.length) break
      for(const k of raw) out.push({ ts: Number(k[0]), open: +k[1], high: +k[2], low: +k[3], close: +k[4], vol: +k[5] })
      if(raw.length < 1000) break
      start = Number(raw[raw.length - 1][0]) + 1
    }
    if(out.length) return clean(out)
  }catch{}
  return []
}

/** Engine in a Web Worker (all 15 strategies take ~1.7 ms per candle); same thread if workers aren't available. */
function runInWorker(candles: Candle[], ids: Strategy[], amount: number, leverage: number, startTs: number): Promise<EngineTrade[]>{
  if(typeof Worker === "undefined") return Promise.resolve(runEngine(candles, ids, amount, leverage, 0.0004, undefined, startTs))
  return new Promise((resolve, reject) => {
    const w = new Worker(new URL("./backtest.worker.ts", import.meta.url))
    w.onmessage = (e) => { w.terminate(); e.data.ok ? resolve(e.data.trades) : reject(new Error(e.data.error)) }
    w.onerror = (e) => { w.terminate(); reject(new Error(e.message || "worker failed")) }
    w.postMessage({ candles, ids, amount, leverage, startTs })
  })
}

export async function runBacktestClient(opts: {
  symbol: string; timeframe: string; from: string; to: string;
  strategies: string[]; amount: number; leverage: number;
}){
  const tf = TF_MS[opts.timeframe] || 3600000
  const fromMs = Date.parse(opts.from), toMs = Date.parse(opts.to) + 86400000 - 1   // whole end day, like the server
  // WINDOW candles before the start so indicators are warmed up exactly like the live bot
  const candles = await fetchCandles(opts.symbol, opts.timeframe, fromMs - WINDOW * tf, toMs)
  const inRange = candles.filter(c => c.ts >= fromMs)
  if(!candles.length) return { ok:false, error: "مقدرناش نجيب الشموع من Bybit ولا Binance — جرّب تاني بعد شوية" }
  if(inRange.length < 20) return { ok:false, error: `الفترة قصيرة: ${inRange.length} شمعة بس — اختار مدة أطول أو فريم أصغر` }

  const trades = await runInWorker(candles, opts.strategies as Strategy[], opts.amount, opts.leverage, fromMs)
  const pnls = trades.map(t => t.pnl)
  const wins = pnls.filter(p => p > 0).length, losses = pnls.length - wins
  const sumWin = pnls.filter(p => p > 0).reduce((s, p) => s + p, 0), sumLoss = Math.abs(pnls.filter(p => p <= 0).reduce((s, p) => s + p, 0))
  let eq = 0, peak = 0, maxDD = 0
  for(const p of pnls){ eq += p; peak = Math.max(peak, eq); maxDD = Math.max(maxDD, peak - eq) }
  const truncated = candles.length >= MAX_CANDLES && candles[0].ts > fromMs - WINDOW * tf

  return {
    ok: true,
    data: {
      symbol: opts.symbol, timeframe: opts.timeframe,
      stats: {
        total: trades.length, wins, losses, win_rate: trades.length ? wins / trades.length * 100 : 0,
        pnl: eq, avg_win: wins ? sumWin / wins : 0, avg_loss: losses ? -sumLoss / losses : 0,
        profit_factor: sumLoss ? sumWin / sumLoss : sumWin ? 99 : 0, max_dd: maxDD,
      },
      trades: trades.map(t => ({ ...t, entry_ts: new Date(t.entry_ts).toISOString(), exit_ts: new Date(t.exit_ts).toISOString() })),
      candles: inRange.length,
      first: inRange[0]?.ts, last: inRange[inRange.length - 1]?.ts, truncated,
      // close per candle for the report's price chart (trades are plotted on it)
      prices: inRange.map(c => ({ t: c.ts, c: c.close })),
    }
  }
}
