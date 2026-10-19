// Runs the backtest engine off the main thread so long ranges don't freeze the page.
import { runEngine, type Candle, type Strategy } from "./strategy-engine"

self.onmessage = (e: MessageEvent<{ candles: Candle[], ids: Strategy[], amount: number, leverage: number, startTs: number }>) => {
  const { candles, ids, amount, leverage, startTs } = e.data
  try{ self.postMessage({ ok: true, trades: runEngine(candles, ids, amount, leverage, 0.0004, undefined, startTs) }) }
  catch(err){ self.postMessage({ ok: false, error: String(err) }) }
}
