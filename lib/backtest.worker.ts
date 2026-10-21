// Runs the backtest engine off the main thread so long ranges don't freeze the page.
import { runEngine, type Candle, type Strategy } from "./strategy-engine"
import { runWaveFlats } from "./wave-flats"
import { runTrendDaily } from "./trend-daily"

self.onmessage = (e: MessageEvent<{ candles: Candle[], ids: Strategy[], amount: number, leverage: number, startTs: number, timeframe: string, funding?: number[] }>) => {
  const { candles, ids, amount, leverage, startTs, timeframe, funding } = e.data
  try{
    const solo = ids as string[]
    const trades = solo.includes("trend_daily") ? runTrendDaily(candles, funding, amount, leverage, 0.0004, startTs)
      : solo.includes("wave_flats") ? runWaveFlats(candles, timeframe, amount, leverage, 0.0004, startTs)
      : runEngine(candles, ids, amount, leverage, 0.0004, undefined, startTs)
    self.postMessage({ ok: true, trades })
  }
  catch(err){ self.postMessage({ ok: false, error: String(err) }) }
}
