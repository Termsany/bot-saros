# Strategy research

How the numbers on the site are produced, and why the engine settings are what they are.

## Method

- **Data:** last 2,000 closed candles from Bybit for BTC, ETH, SOL and XRP on 1h and 4h — 8 data sets
  (1h ≈ Jul–Oct 2026, 4h ≈ Nov 2025–Oct 2026).
- **Signals:** `backtest.score_at` on the last 300 candles at every bar — exactly what the live bot sees.
- **Trades:** `backtest.run_backtest` with the `CONFIG` in `backtest.py`: one position per symbol, fixed 3% SL / 6% TP,
  breakeven at 50% of the way to TP, ADX ≥ 10, range filter, fees 0.04% per side, $20 margin × 5.
- **Out-of-sample:** the last 40% of every set. Settings were picked on the first 60% only.

`bot.py`, `backtest.py` and `lib/strategy-engine.ts` (browser backtest) follow the same rules.
`research/parity.ts` checks the browser engine against Python on every signal of every candle and on trades/PnL.

```bash
python research/measure_strategies.py score BTC/USDT   # one per symbol, can run in parallel (~5 min each)
python research/measure_strategies.py report           # writes lib/strategy-stats.json
python research/parity_export.py && node research/parity.ts
```

## Findings (October 2026)

1. **The previous engine lost money.** The default 15-strategy mix lost on 5 of 8 sets; buy-and-hold made more.
   About 0.08 USDT of fees per trade and very frequent entries (|score| > 0.15, no pause) turned a small gross
   edge into a loss.
2. **The numbers shown before were not measured this way** (e.g. ICT "71% win rate, PF 3.32" came from 3 trades).
3. **The browser backtest did not run the named strategies** — most were stand-ins (ICT = RSI + SMA mix,
   Gann = always 0) and it ignored the chosen dates. Replaced by an exact port of the bot.
4. **`backtest.py` rounded S/R levels to 2 decimals** (the bot uses 6), which merged every level on coins under ~$5.
5. **Picking last period's winners did not work.** The 3 best strategies on the first 60% lost on the last 40%,
   about as much as the default mix. A "learning" ranking would need more data before it can be trusted.

## Engine change: entry threshold 0.35 + 3-candle cooldown

Grid on the first 60%: threshold 0.15 / 0.35 / 0.5 × cooldown 0 / 3 / 6 candles, same setting for every strategy.
Rule: highest median in-sample improvement across the 20 strategies tested (15 current + 5 candidates).

| | trades | total out-of-sample PnL (20 strategies) |
|---|---|---|
| before (0.15, no cooldown) | 18,059 | −621 USDT |
| **chosen (0.35, 3 candles)** | 12,999 | **−408 USDT** |

28% fewer trades and about a third less loss out-of-sample; 13 of 21 runs improved, 8 got worse.
It is a real but modest improvement — most strategies are still close to break-even.

Also tested and **not** adopted: ATR-based SL/TP (helped some strategies, hurt others), the higher-timeframe filter,
and 5 new strategies (SuperTrend ATR 10×3, Donchian 20 breakout, EMA 20/50 trend, RSI(2) pullback, MACD cross) —
none was consistently better on both periods.
