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

## Wave Flats (added October 2026)

Port of the Pine Script "Wave Flats - Regular / Running / Expanded" with its default inputs, **without** the
higher-timeframe filter (owner's choice). Own entries, stops and targets, so it always runs alone:
`strategies_wave.py` (bot + server backtest) and `lib/wave-flats.ts` (browser backtest).
Fills follow TradingView's broker emulator (entry at the next open; stops/targets inside the candle).

```bash
python research/wave_parity_export.py && node research/wave_parity.ts   # browser = Python trade by trade, live signal = backtest entry
```

Results ($20 × 5, fees 0.04% per side):

| data | trades | win rate | PF | PnL |
|---|---|---|---|---|
| site's 8 sets (2,000 candles, table above) | 45 | 13.3% | 0.73 | −19.6 USDT |
| 8 coins × 1h (8,000 candles) | 221 | — | — | −45.7 USDT |
| 8 coins × 4h (5,000 candles) | 210 | — | — | −37.1 USDT |
| all 16 long sets | 431 | 11.8% | 0.90 | −82.8 USDT |
| same, with the higher-timeframe filter on | 229 | 9.2% | 0.75 | −99.3 USDT |

Most trades are Regular Flats; 379 of 431 ended at the stop. It does not have an edge on this data —
the bot runs it in paper mode only (LIVE is refused), and partial take-profit is not placed as exchange orders yet.

## Daily trend following + volatility sizing (October 2026)

Literature: Moskowitz, Ooi & Pedersen (2012) "Time Series Momentum" (JFE); Liu & Tsyvinski (2021)
"Risks and Returns of Cryptocurrency" (RFS); Moreira & Muir (2017) "Volatility-Managed Portfolios" (JF).

- **Data:** Binance USDT-M daily candles + real funding, 8 coins (BTC ETH SOL XRP BNB DOGE ADA LINK), 2019/2020 → Oct 2026.
- **Rules:** signal at the daily close = average sign of the 20/60/120-day returns; long only (negative = flat);
  size $100 × min(1, 80% / 30-day volatility); resize only on >25% change; fees 0.04% on every change + funding.
- **Selection:** 32 variants (lookback × long-only/long-short × size) ranked by median Sharpe on the first 60% of
  each coin; the same family wins with a 50/50 or 70/30 split too.

```bash
python research/trend_data.py && python research/trend_study.py && python research/voltarget_study.py
```

Out-of-sample (last 40% ≈ 2024 → Oct 2026): positive on 8/8 coins, median Sharpe 0.59 (buy-and-hold 0.20),
median max drawdown 46 USDT vs 110 for buy-and-hold, about 28% average exposure. It earns less than holding in
a strong bull run (SOL, XRP) and much more in falls (DOGE, ADA, LINK).

8-coin portfolio, whole period:

| | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 | total | max DD | Sharpe |
|---|---|---|---|---|---|---|---|---|---|---|
| trend, volatility-sized | +508 | +898 | −71 | +321 | +477 | +18 | +18 | +2,168 | 275 | 1.39 |
| trend, fixed size | +550 | +1,584 | −96 | +331 | +514 | −21 | +17 | +2,879 | 332 | 1.37 |
| buy-and-hold | +862 | +2,478 | −643 | +824 | +730 | −56 | −56 | +4,090 | 1,036 | 0.96 |

Caveats: most of the profit is from 2020–2021 and 2023–2024; 2025–2026 is about flat. Positions last weeks,
so at 5× a 20% move against the position would liquidate the $20 margin — this needs 1–2× leverage.

**Volatility sizing on the current 1h/4h strategies: not adopted.** Re-sizing each trade by recent volatility
improved PnL/drawdown on 4/15 strategies over the whole period and 11/15 out-of-sample; it cut Dow and Ichimoku
by more than half, because the 6% targets are reached mostly when volatility is high.

### In the bot and on the site: `trend_daily`

The study rebalances every day; the bot trades it as plain trades so it can be run and checked:
on when the close is above the close 20/60/120 days ago for at least 2 of the 3; buy at the next open with
size = margin × leverage × min(1, 80% / 30-day volatility), fixed for the trade; sell at the next open once it
is off; protective stop at entry × (1 − 0.8 / leverage), before the margin would be liquidated. Long only.
`strategies_trend.py` (bot + server backtest) = `lib/trend-daily.ts` (browser), checked by
`python research/trend_parity_export.py && node research/trend_parity.ts`. LIVE is refused for now (paper first).

Same 8 coins, $20 margin, fees + funding (first 60% / last 40% as above):

| leverage | trades | PF | PnL | last 40% | coins positive (last 40%) | median max DD |
|---|---|---|---|---|---|---|
| ×1 | 630 | 6.78 | +1,912 | +172 | 8/8 | 10 |
| **×2** (site numbers) | 630 | 6.58 | +3,803 | +324 | 8/8 | 24 |
| ×3 | 632 | 6.57 | +5,713 | +500 | 8/8 | 32 |
| ×5 | 652 | 6.16 | +9,436 | +838 | 8/8 | 49 |

The protective stop hit 2 times in 630 trades. PF is inflated by a few huge trends — DOGE in 2021 alone is
+2,247 of the +3,803 at ×2; without DOGE it is +1,557. Win rate is about 33%: many small losses, few big wins.
