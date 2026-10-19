// Runs the backtest engine off the main thread so long ranges don't freeze the page.
import { runEngine, type Candle, type Strategy } from "./strategy-engine"
import { runWaveFlats } from "./wave-flats"

self.onmessage = (e: MessageEvent<{ candles: Candle[], ids: Strategy[], amount: number, leverage: number, startTs: number, timeframe: string }>) => {
  const { candles, ids, amount, leverage, startTs, timeframe } = e.data
  try{
    const trades = (ids as string[]).includes("wave_flats")
      ? runWaveFlats(candles, timeframe, amount, leverage, 0.0004, startTs)
      : runEngine(candles, ids, amount, leverage, 0.0004, undefined, startTs)
    self.postMessage({ ok: true, trades })
  }
  catch(err){ self.postMessage({ ok: false, error: String(err) }) }
}
