# Strategy research

How the numbers on the site are produced, and why the engine settings are what they are.

## Market data: download once, then only what's new

Every study reads `universe_daily.pkl` (daily candles of every Binance USDT-M perpetual since 2019, delisted
included) and `universe_funding.pkl` (real funding per coin per day) from `$RAQM_RESEARCH_CACHE`, or
`research/.cache` when it isn't set. The full history was downloaded once on the server (fast connection), in
`/opt/raqm-data/research`. Copy it once to a PC:

```bash
mkdir -p research/.cache && scp root@bot.da3m.io:/opt/raqm-data/research/universe_*.pkl research/.cache/
```

Then, before a backtest, add only the days since the last update (a few minutes, a little data):

```bash
python research/universe_data.py && python research/funding_store.py
```

Without a copy the same two commands build everything from scratch (about 10 minutes of candles, longer for funding).

**Bybit** (a second exchange, November 2026): `bybit_daily.pkl`, `bybit_funding.pkl`, `bybit_meta.pkl` — every crypto
USDT perpetual Bybit lists or has closed (835, 318 delisted; stocks, ETFs, commodities and forex left out), daily
candles and real funding since 2020, in the same folder on the server. Copy, or refresh (resumable, only what is
missing; ~40 minutes from scratch on the server at `RAQM_BYBIT_PAUSE=0.04`):

```bash
scp root@bot.da3m.io:/opt/raqm-data/research/bybit_*.pkl research/.cache/
python research/bybit_data.py
```

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

### Which coins: top N by volume (October 2026)

The fixed 8 coins were picked today — coins that survived and grew — so their numbers flatter the strategy.
`research/universe_study.py` re-runs the daily trend (×2, $20) on **every** Binance USDT-M perpetual since 2019,
delisted ones included (133 of them), allowing new entries each day only for the top N by 30-day average USDT
volume among coins with ≥150 days of history. Funding: the daily median of the 8 coins' real funding.

| coins | trades | PnL | max DD | Sharpe before 2024 | Sharpe 2024 → | most open at once |
|---|---|---|---|---|---|---|
| fixed 8 (hindsight) | 630 | +3,727 | 128 | 0.71 | 1.29 | 8 |
| top 5 | 466 | +515 | 156 | 0.50 | 0.92 | 10 |
| **top 10** | 911 | +1,427 | 343 | 0.86 | **1.07** | 20 |
| top 15 | 1,379 | +1,753 | 526 | 1.00 | 0.79 | 27 |
| top 20 | 1,822 | +1,924 | 550 | 1.05 | 0.79 | 38 |
| top 30 | 2,673 | +4,058 | 768 | 0.80 | 0.55 | 47 |

The edge without hindsight is smaller but still there. Top 10 is what the VPS bot runs (`deploy/vps/`):
best out-of-sample Sharpe and far smaller drawdowns than 15+; 2022 and 2023 were losing years for every variant.
The bot ranks Bybit's crypto perpetuals the same way (stocks, ETFs, commodities, forex and stablecoins excluded).

## Short side (October 2026)

`research/short_study.py` — every Binance USDT-M perpetual since 2019 (delisted included), real per-coin funding
(`research/universe_funding.py`: shorts receive positive funding, pay negative), fees, $20 × 2; chosen before 2024.

| | trades | PnL | max DD | Sharpe before 2024 | Sharpe 2024 → | 2022 | 2024 |
|---|---|---|---|---|---|---|---|
| long trend, top 10 (the bot) | 911 | +1,672 | 312 | 0.85 | 1.33 | −225 | +329 |
| 1. bear-trend short (2 of 3 down + BTC < 200d) | 426 | +105 | 274 | 0.62 | **−0.23** | +217 | −159 |
| 2. new-listing short (30 d after listing, hold 90, stop 40%) | 576 | +1,099 | 920 | 1.17 | 0.73 | +138 | −493 |
| 2. same, at most 10 open (what runs on paper) | 250 | +729 | 354 | 0.61 | 1.25 | +138 | −31 |

1. **Not adopted:** it pays in a crash (2022) and loses out-of-sample.
2. **Promising, risky:** all 18 variants were positive overall and out-of-sample, but drawdowns are large, 2024 lost
   (new coins rallied), most profit is 2025–2026, and stops on thin new coins can fill worse than the test assumes.
   Capping it at 10 open shorts cut the drawdown from 920 to 354. It runs as a separate paper bot on the VPS
   (`bot.py --strategy listing_short`, `deploy/vps/raqm-listing.service`, section on bot.da3m.io) before any decision.

### 3. Short when funding is extreme — not adopted

`research/funding_study.py` (Schmeling, Schrimpf & Todorov 2023, "Crypto Carry"): short a top-10 coin when its
average funding over 1/3/7 days is above 30/60/100% a year, cover when it falls below a third of that or after
10/30 days, optionally only if the price is below last week's. **35 of 36 variants lost money.** Very high funding
comes in the middle of strong rallies (2021: up to −650 in one year), not at their end; the in-sample pick made
+44 on 38 trades (noise). Funding above 30% a year happens on 8.5% of top-10 coin-days.

The useful result: the two strategies on paper complement each other —

| | PnL | max DD | Sharpe 2024 → | 2022 |
|---|---|---|---|---|
| long trend, top 10 | +1,672 | 312 | 1.33 | −225 |
| new-listing short, max 10 | +729 | 354 | 1.25 | +138 |
| **both (what runs now)** | **+2,401** | **265** | **1.79** | **−88** |

Together the drawdown is smaller than either alone: the short earns in falls, the long in rallies.

### 4. Pump fade and 5. cross-sectional momentum

`research/pump_momentum_study.py` — funding for the traded windows from Bybit (523) with Binance for the rest (76).

**Pump fade — not adopted** (Kamps & Kleinberg 2018): short a top-100 coin after a day up ≥30/50% on ≥3/5×
its volume. 9 of 48 variants made money, none after a +30% day; the in-sample pick made +114 with out-of-sample
Sharpe 0.13. Pumped coins tend to keep rising — in line with MAX momentum in crypto (Li, Urquhart, Wang & Zhang 2021).

**Cross-sectional momentum — works as long/short only** (Liu, Tsyvinski & Wu 2022): every 7 days rank the top 50
by volume on the last 1/2/4 weeks' return. Shorting only the weakest 5 lost before 2024 and won after (unstable);
long the strongest 5 + short the weakest 5 made money in all 3 variants. In-sample pick (2 weeks):
+1,831, max DD 243, Sharpe 0.67 before 2024 / 1.30 after, every year positive except 2022 (−80).

| | PnL | max DD | Sharpe < 2024 | Sharpe 2024 → | 2022 |
|---|---|---|---|---|---|
| the two paper bots (long trend + new listings) | +2,401 | 265 | 0.97 | 1.79 | −88 |
| **+ momentum long/short** | **+4,232** | 354 | **1.15** | **2.08** | −167 |

Runs as a third paper bot (`bot.py --strategy momentum_ls`, `deploy/vps/raqm-momentum.service`): ~10 trades a week,
~20 open at most, its long side can hold the same coins as the trend bot.

### 6. Buying the pump and 7. pairs trading — not adopted

`research/volume_pairs_study.py`.

**Pump continuation (long)** (Gervais, Kaniel & Mingelgrin 2001; Li, Urquhart, Wang & Zhang 2021): the pump-fade
events bought instead of shorted. 25 of 48 variants made money; the in-sample pick (+30% day, 5× volume, hold 7 d,
stop 40%) made +484, almost all in 2021, and lost out-of-sample (Sharpe −0.02). Some 3-day variants look good after
2024 but were not the in-sample pick. With the three paper bots: Sharpe after 2024 2.08 → 1.63, max DD 354 → 573.

**Pairs trading, distance method** (Gatev, Goetzmann & Rouwenhorst 2006): every 6 months the closest-moving pairs
among the top 20 by volume, open at 1.5–2.5σ, close on convergence. 4 of 24 variants made money; the in-sample pick
lost out-of-sample (Sharpe −0.65) — on daily candles diverging coins tend to keep diverging. With the three bots:
Sharpe 2.08 → 1.64, max DD 354 → 514.

**So far:** on daily candles, what works follows trends and relative strength (trend long, momentum long/short),
plus the fading hype of new listings. Every reversal or mean-reversion idea (pump fade, pump buy timing, pairs,
extreme-funding short, bear-trend short) failed. The three paper bots together: +4,232, max DD 354, Sharpe 2.08
after 2024 — nothing tested so far improves that.

### 8–10. Risk-managed momentum, residual momentum, cross-sectional carry — not adopted

`research/momentum_carry_study.py` (top-50 funding: Bybit 312 windows, Binance 52). Baseline = the momentum paper bot
(2-week long/short): +1,877, max DD 242, Sharpe 0.68 before 2024 / 1.32 after.

| | PnL | max DD | Sharpe < 2024 | Sharpe 2024 → |
|---|---|---|---|---|
| momentum now | +1,877 | 242 | 0.68 | 1.32 |
| risk-managed (Barroso & Santa-Clara 2015), best: vol 26 w, max 1.5× | +1,699 | 252 | 0.77 | 1.29 |
| residual (Blitz, Huij & Martens 2011), best: 2 w, beta 60 d | +1,728 | 214 | 0.56 | 1.19 |
| carry (Schmeling et al. 2023): short highest / long lowest funding, 3 d | +1,018 | 353 | 1.00 | 0.23 |

- **Risk-managed momentum:** about the same out-of-sample, smaller average size — no real gain here.
- **Residual momentum:** smaller drawdown and a positive 2022, but weaker in both periods.
- **Carry:** all 3 variants positive overall, but most of it is 2021 (+573) and it lost in 2025; with the three bots
  it raised PnL (4,279 → 5,296) and lowered the out-of-sample Sharpe (2.09 → 1.88). The funding gap between coins
  has narrowed as the market matured.

The three paper bots stay as they are (+4,279, max DD 355, Sharpe 2.09 after 2024).

### 11–13. 52-week-high momentum, Donchian breakout, ratio trend — not adopted

`research/breakout_ratio_study.py` and `research/ratio_fairness.py`.

- **52-week-high momentum** (George & Hwang 2004): long the 5 top-50 coins closest to their high, short the 5 furthest.
  Weak: the in-sample pick (180-day high) made +427, Sharpe 0.28 / 0.42 — clearly worse than plain momentum.
- **Donchian breakout** (Turtles; Hurst, Ooi & Pedersen 2017) on the top 10: all 6 long+short variants positive
  (pick: 55/10, stop 40% — +789, DD 191, Sharpe 0.73 / 0.91), but **all of it from the long side**; the short side
  lost or broke even in every variant. In practice a second long trend on the same coins.
- **Ratio trend** on the 10 pairs among BTC, ETH, SOL, BNB, XRP (long the first / short the second while their ratio
  is above its 50-day average): +2,472, DD 187, Sharpe 1.10 / 1.55 — and with the three bots Sharpe after 2024
  2.10 → 2.52. **But the five coins were picked today.** The fairness check — every week the top K by volume at
  that time — keeps an edge but much weaker:

| ratio trend | PnL | max DD | Sharpe < 2024 | Sharpe 2024 → |
|---|---|---|---|---|
| 5 majors picked today (hindsight) | +2,472 | 187 | 1.10 | 1.55 |
| top 5 by volume each week | +1,335 | 361 | 0.90 | 0.67 |
| top 7 by volume each week (in-sample pick) | +3,196 | 795 | 1.31 | 0.77 |
| three bots + top 7 | +7,485 | 863 | 1.65 | 1.61 (vs 2.10 now) |

The weekly top 5 included short-lived volume spikes (ARPA, LINA in 2023, PEPE in 2024–25). Hindsight roughly
doubled the apparent result — the reason every study here picks coins by what was known at the time.

### 14. Betting against beta and 15. strategy momentum across the bots — not adopted

`research/bab_allocation_study.py`.

**Betting against beta** (Frazzini & Pedersen 2014): weekly, long the 5 lowest-beta top-50 coins and short the 5
highest (beta vs BTC, shrunk towards 1). All 4 variants made money; the pick (60-day beta, beta-balanced) +2,678,
DD 693, Sharpe 0.62 / 0.81 — but the long side made +2,818 and the short side −141: beta-balancing makes it net long
(2022: −206). With the three bots: Sharpe after 2024 2.09 → 1.63, DD 355 → 582.

**Strategy momentum across the paper bots** (Ehsani & Linnainmaa 2022): monthly weights from each bot's past 3/6/12
months (turn off losers, or 1.5×/0.5× the best/worst two). On the three core bots nothing beat equal weights after
2024 (2.09): e.g. turn off losers 12 months 1.91 with DD 269, tilt 3 months 1.80. The bots' good and bad spells are
too short — a bot is often cut just before it recovers. With the HIGH RISK ratio bot as a fourth, the best rotation
(tilt, 3 months: 1.73) beats the four at equal weights (1.61) but not the three alone.

**After 15 ideas:** the three core paper bots at equal weights (+4,285, max DD 355, Sharpe 2.09 after 2024) remain
the best combination tested; everything outside trend-following and relative strength failed on daily candles.

### 16–18. Hourly: intraday momentum, BTC lead-lag, funding-time effect — not adopted

`research/hourly_data.py` (hourly candles for the 106 coins ever in the top 10 — Bybit, Binance for the rest — and
exact-time funding) and `research/hourly_study.py`. Daily membership from the previous day's top 10.

| idea | variants positive | in-sample pick, Sharpe after 2024 |
|---|---|---|
| intraday momentum (Gao et al. 2018; Shen, Urquhart & Wang 2022) | 4 / 24 | −0.72 (and $476 of fees) |
| BTC → altcoin lead-lag | 1 / 8 | −0.56 |
| funding-time effect | 0 / 9 | −0.95 |

None improved the three core bots. On hourly candles the extra trades' costs eat any small edge.

### 19. Filters on the new-listing short — not adopted (November 2026)

`research/listing_improve_study.py`: the rule that runs (30 days after listing, hold 90, stop 40%, at most 10 open,
577 listings since 2021) with four filters fixed before any result, every combination (36): BTC regime (none / below
its 200-day average / 30-day return below 0), the coin's move since listing (none / below its listing open / not up
50%+), skip on negative 7-day funding, and a cover at −60%. Chosen on Sharpe before 2024, 60 trades at least.

| | trades | PnL | max DD | Sharpe < 2024 | Sharpe 2024 → | PnL 2024 → |
|---|---|---|---|---|---|---|
| **the rule that runs** | 251 | **+775** | 358 | 0.64 | **1.30** | **+529** |
| in-sample pick: skip coins up 50%+ since listing | 239 | +608 | 353 | 0.71 | 0.88 | +344 |
| BTC 30-day return below 0 | 152 | +498 | 238 | 0.56 | 0.92 | +344 |

- **0 of 36 variants beat the rule out-of-sample.** The rule stays as it is.
- The losses are the stops: 110 trades hit the 40% stop (−1,716); the 139 held 90 days made +2,451.
- Shorting new coins while BTC is below its 200-day average lost (92 trades, −51): in a falling market the new
  coins have often already fallen, and they bounce. Every BTC-below-200d variant lost before 2024.
- The BTC-30-day filter cut the drawdown (358 → 238) but also half the profit; it was not the in-sample pick.

### 20. The new-listing short on Bybit — weaker, and more fragile than Binance alone showed (November 2026)

`research/bybit_listing_study.py`: the exact rule (30 days after the first candle, hold 90, stop 40%, at most 10 open,
fees, real funding) on Bybit's 803 listings since 2021, 294 of them delisted. Nothing tuned on Bybit.

| | trades | PnL | max DD | Sharpe < 2024 | Sharpe 2024 → |
|---|---|---|---|---|---|
| Binance, every listing (the rule that runs) | 251 | +775 | 358 | 0.64 | 1.30 |
| Bybit, every listing | 275 | +301 | 390 | −0.26 | 0.80 |
| Bybit, coins also on Binance | 263 | −96 | 429 | −0.17 | −0.07 |
| Bybit, coins never on Binance (≥ $1M a day) | 114 | +606 | 161 | 0.57 | 1.16 |

- **The same coins, two exchanges:** the coins on both made +630 with Binance's listing dates and −96 with Bybit's.
  Not a matter of who listed first (Bybit first or the same week: −12). With at most 10 open, which listings get a
  slot decides much of the result — the edge is real on average but noisier than one exchange's history shows.
- On Binance, its 39 listings that Bybit never had lost (−194); on Bybit, the coins Binance never had made +606
  (mostly 2025–2026, 114 trades). Small samples, likely luck of the period.
- **Not adopted:** no Bybit bot. For the listing short on Binance it means caution before real money — its
  backtest result depends on which coins fill the 10 slots, so the paper and Demo sample matters more.

### 21. The ratio trend: tested, netted per coin, and as live runs it (November 2026)

`research/ratio_netting_study.py` (docs/ratio-trend-live-plan.md §1): the bot's rule (every pair among the weekly top
7 by volume, ratio vs its 50-day mean) at the real account's $26 margin ×2 per unit, 2020-01 → 2026-10, fees and
real funding, a daily model (each unit's notional reset daily).

| | PnL | worst DD | Sharpe < 2024 | Sharpe 2024 → | margin used | 2022 | 2026 |
|---|---|---|---|---|---|---|---|
| PAIRS: the tested strategy, 21 pairs, no stop | +1,949 | 1,406 (54 units) | 0.70 | 0.19 | ~$588 | −439 | +29 |
| NETTED: one position per coin (+6 … −6 units) | +2,011 | 1,400 | 0.71 | 0.20 | ~$588 | −429 | +37 |
| NETTED + 40% stop per coin | **+2,455** | **1,273 (49 units)** | 0.59 | **0.64** | ~$582 | −387 | +772 |
| LIVE NOW: coin-disjoint pairs only | +219 | 246 | 0.51 | 0.10 | ~$149 | −101 | +8 |

- **Netting works:** the same PnL as the 21 pairs, with 20% less in fees.
- **The stop matters:** in 2026 pump coins entered the top 7 (SIREN +269% in one day on 2026-04-04 while the
  basket was short 6 units: −$839 that day without a stop). With the stop, 2026 is +772. Without the stop, 2026 is
  flat, though one coin (LAB) alone made +856 in it: the year rests on a few coins either way.
- **The drawdown is the problem:** about 49 units ($1,273 at $26), lasting from 2021-11 to 2023-08. That's roughly 3×
  momentum's and trend_daily's, for a Sharpe after 2024 (0.64) below both.
- **What runs live now** (coin-disjoint pairs) is a quarter of the size, and its edge after 2024 is near zero.
- Weaker than docs/demo-baseline.md (PF 1.37, DD 39.7 margins), which used fixed quantities from entry and a
  different start date. The ranking is the same.

### 22. momentum_ls with the weekend off — not adopted (November 2026)

`research/momentum_hold_days_study.py`: the live rule (Monday 00:00 UTC entry, top 50, 5 + 5, stop 40%), $26 ×2,
2019 → 2026-10, fees and real funding. Only the exit day changes; the basket is flat until the next Monday.

| hold | net | worst DD | PF (2024 →) | Sharpe < 2024 | Sharpe 2024 → |
|---|---|---|---|---|---|
| 7 days, Monday → Monday (runs) | **+$1,943** | $476 (18.3 margins) | 1.15 (1.20) | 0.60 | **1.15** |
| 5 days, close end of Friday | +$1,809 | **$269** (10.3) | 1.16 (1.19) | **0.79** | 1.00 |
| 4 days, close end of Thursday | +$1,496 | $359 (13.8) | 1.15 (1.20) | 0.64 | 1.01 |
| 3 days, close end of Wednesday | +$1,238 | $291 (11.2) | 1.14 (1.19) | 0.56 | 0.96 |

- A shorter week makes less (Thursday −23%) for the same profit factor. It cuts the drawdown, mostly 2022's.
- Closing at the end of Friday has the best drawdown and the best Sharpe before 2024. After 2024, the period not used
  to pick anything, the full week is best (1.15 against 1.00). The drawdown gain rests mostly on one bad year (2022),
  so it isn't evidence enough to change a live rule during its first measured weeks.

### 23. momentum_ls: every open day × every hold — Wednesday stands out, not adopted yet (November 2026)

`research/momentum_day_grid_study.py`: the live rule on all 49 combinations (open Monday … Sunday, hold 1–7 days, flat
until the next open), $26 ×2, fees and real funding. To keep a choice out of luck, a variant is picked on before 2024 only
and judged on 2024 → 2026-10.

| | net | worst DD | PF (2024 →) | Sharpe < 2024 | Sharpe 2024 → | 2022 | 2024 |
|---|---|---|---|---|---|---|---|
| Mon, 7 days (runs) | +$1,943 | $476 | 1.15 (1.20) | 0.60 | 1.15 | −259 | −37 |
| **Wed, 3 days** (best before 2024) | +$1,932 | **$160** | 1.21 (1.23) | 1.12 | 1.10 | +195 | +237 |
| Wed, 6 days | +$2,527 | $323 | 1.20 (1.27) | 0.83 | 1.34 | −91 | +485 |
| Wed, 7 days | +$2,368 | $312 | 1.18 (1.24) | 0.73 | 1.22 | −97 | +359 |
| Sun, 7 days (best after 2024) | +$2,933 | $442 | 1.22 (1.42) | 0.31 | 1.48 | −228 | +222 |

- **Across all 49 the two periods agree only weakly** (rank correlation of Sharpe +0.22). Most of the differences
  between days are timing luck, as §22 and docs/live-small-size-plan.md found for the full week.
- **Wednesday is the exception:** every Wednesday hold is good in both periods (Sharpe 0.73–1.12 before 2024,
  0.95–1.34 after). Wednesday-3 makes the same as the live rule with a third of its drawdown, and it was positive in
  every year 2020–2026 (2022 +195, 2024 +237, where Monday lost). Thursday is the weakest in both.
- **Sunday** is the best after 2024 and among the worst before: chosen on its recent numbers it would be hindsight.
- Every variant takes about 70% of its profit from its 10 best weeks.
- **Not adopted now:** the live rule stays Monday through its first real rebalances (one change at a time, and a
  change needs a code change and a restart). Worth revisiting after them: Wednesday-6 or Wednesday-3.

### 24. The ratio trend: which coins? No fair rule is good in both periods (November 2026)

`research/ratio_universe_study.py` (owner, 2026-11-07: "must the pairs be among high-volume coins?"): the bot's rule,
netted per coin with a 40% stop, $26 ×2 per unit, 2020-01 → 2026-10, fees and real funding. Every universe is
re-picked weekly by a rule known at the time; only "5 majors" is hindsight.

| universe | PnL | worst DD | PnL/DD | Sharpe < 2024 | Sharpe 2024 → | 2022 | 2026 |
|---|---|---|---|---|---|---|---|
| 5 majors (hindsight) | +1,428 | 236 | 6.05 | **1.13** | 0.65 | +135 | −108 |
| 30-day volume, top 7 (runs now) | **+2,455** | 1,273 | 1.93 | 0.59 | 0.64 | −387 | +772 |
| 90-day volume, top 5 | +568 | 327 | 1.73 | 0.64 | −0.12 | +195 | −178 |
| persistent top 7 (in the top 10 in 8 of the last 12 weeks) | +1,708 | **588** | **2.91** | 0.14 | **1.27** | −62 | +834 |
| 180-day volume, top 7 | +903 | 798 | 1.13 | 0.14 | 0.63 | −118 | −47 |
| 365 days of history, top 7 | +1,061 | 885 | 1.20 | 0.40 | 0.20 | −94 | −301 |

(13 universes in the script's output; each top 5 version makes less than its top 7.)

- **Volume matters, but no volume rule rescues the strategy.** Picked before 2024, the best fair rules are the one
  that runs now (0.59) and 90-day top 5 (0.64); after 2024 the second loses.
- **Persistent top 7** halves the drawdown (588 vs 1,273) for 70% of the PnL and has the best Sharpe after 2024. But
  its Sharpe before 2024 is 0.14: choosing it would be choosing on the period kept for checking. Worth a forward
  test, not real money.
- Even the hindsight majors are weak after 2024 (0.65, 2026 −108): the edge itself has faded, not only the coin pick.
- 13 universes were tried, so the best number in each column is partly luck.
- **Decision:** the ratio trend stays off real money. If tested further, persistent top 7 on Demo.

### 25. The ratio trend without BTC and ETH: better, and it fits a small account, but the drawdown stays (November 2026)

`research/ratio_universe_study.py --no-btc` (owner, 2026-11-07: "can the ratio trend run on a small account?").
Binance's smallest futures order (checked 2026-11-07): BTC $50, ETH $20, 653 other USDT perpetuals $5. With BTC in,
a unit can't go below $25 margin at ×2 (why the Demo bot runs $26). Without BTC and ETH, the next coins in line by
volume come in. Same strategy and costs as §24, $26 ×2 per unit.

| universe | PnL | worst DD | Sharpe < 2024 | Sharpe 2024 → | 2022 | 2026 | max units | DD units |
|---|---|---|---|---|---|---|---|---|
| 30-day volume, top 5 | +296 | 829 | 0.15 | 0.13 | −407 | +176 | 12 | 32 |
| … no BTC/ETH | +1,493 | 690 | **0.59** | 0.59 | −226 | +455 | 12 | 27 |
| 30-day volume, top 7 (runs now) | +2,455 | 1,273 | 0.59 | 0.64 | −387 | +772 | 24 | 49 |
| … no BTC/ETH | **+3,324** | 1,301 | **0.62** | **0.86** | −216 | +1,172 | 24 | 50 |
| persistent top 7 | +1,708 | 588 | 0.14 | 1.27 | −62 | +834 | 24 | 23 |
| … no BTC/ETH | +2,718 | 1,089 | 0.24 | 1.74 | −578 | +1,446 | 24 | 42 |

- **Taking BTC and ETH out helps in every version.** "30-day top 7, no BTC/ETH" has the best Sharpe before 2024 of
  any fair universe (0.62), and it holds after (0.86). Picked by the rule of §24 (judge before 2024), it would be
  chosen. But 17 universes have now been tried on the same data.
- **It fits a small account.** Capital ≈ (max units + drawdown units) × unit margin. At $4 a unit ($8 notional, above
  the $5 minimum): (24 + 50) × $4 ≈ **$300**. The PnL scales with the unit: about +$510 over 6.8 years at $4.
- **The drawdown is the catch.** 50 units is about two thirds of that capital (momentum's worst is 18 margins),
  lasting from 2021-11 to 2023-08. One coin can carry up to 6 of the 24 units.
- Not every $5 coin can take an $8 order: a coarse quantity step on a high-priced coin raises its real minimum. A
  live version must check each coin's step size before it trades.
- **Decision:** still not real money. The fair candidate worth a forward test is "30-day top 7, no BTC/ETH" on
  Demo at $4 a unit.

### 26. 5–15 minute strategies — none survives costs, not adopted (November 2026)

`research/m5_data.py` (5-minute candles since 2021 for the 102 coins ever in the top 10 by 30-day volume, delisted
included, from Binance's monthly files; kept on the server in `/opt/raqm-data/research/m5`, 1.3 GB, rerun adds only
new months) and `research/intraday_study.py`. Each day the previous day's top 10; $100 notional a trade; taker 0.05%
+ 0.02% slippage a side, maker 0.02% (limit fills only when the next bar trades through the price). 24 variants fixed
before any result:

| family | variants | best gross edge / trade | variants positive after 2024 | in-sample pick, Sharpe after 2024 |
|---|---|---|---|---|
| A. 15m Bollinger reversal, limit in (short-term reversal) | 12 | +5.4 bps | 0 / 12 | |
| B. 15m channel breakout, trailing ATR stop (intraday momentum) | 8 | −4.4 bps | 0 / 8 | |
| C. 5m shock reversal after a 4–6σ move, limit in | 4 | +11.4 bps | 1 / 4 | **0.02** (+$8 on 4,100 trades) |

- **The edge before costs is a few basis points.** Almost every variant's gross edge is below the cheapest possible
  round trip (maker both sides, 4 bps); a realistic one (maker in, taker out) costs 9 bps, taker both sides 14.
- Breakouts lose even before costs (whipsaws on 15m); reversals make 1–5 bps gross, and the costs turn it into a loss.
- The one survivor (C, 6σ, out after 15 minutes) earned 2.4 bps net in all, Sharpe 0.42 before 2024 and 0.02 after,
  and its limit fills are optimistic (a shock fills the queue first). It is noise, not an edge.
- With §16–18 (hourly), the answer is the same at every short timeframe we tried: the edge lives on daily and
  weekly holds (momentum, trend), where a move is much bigger than the fees.

### 27. Hourly strategies that hold hours to days — none holds out-of-sample, not adopted (November 2026)

`research/hourly_trend_study.py`, on hourly candles made from §26's 5m store (cached in
`/opt/raqm-data/research/h1`). The previous day's top 10; taker 0.05% + 0.02% slippage a side **and each coin's real
funding for the time held**; an account of at most 5 positions, each 40% of equity as notional, compounding. 20
variants fixed before any result:

| family | variants | win % | profit factor | gross / funding / net bps a trade | positive after 2024 |
|---|---|---|---|---|---|
| P. trend pullback (daily trend + hourly RSI dip, out at RSI 50 / 4 ATR stop / T hours) | 8 | 53–60 | 0.87–0.95 | +1 to −20 / 3–5 / −11 to −30 | 0 / 8 |
| Q. 72h / 168h channel breakout, trailing ATR | 8 | 37–40 | 0.91–1.03 | −5 to +42 / 2–15 / −22 to +13 | 2 / 8 |
| R. volatility squeeze breakout, trailing ATR | 4 | 38–39 | 0.98–1.09 | +10 to +29 / 1–5 / −6 to +11 | 0 / 4 |

- **In-sample pick** (R, 3 ATR trail, with the trend: Sharpe 0.85 before 2024) → **Sharpe −0.34, −46% after 2024.**
- The two variants positive after 2024 (Q 168h, 8 ATR) were negative before it: Sharpe −0.13 / −0.08.
- **A high win rate isn't profit.** The pullbacks win 53–60% of trades, but the average loss (−4.6 to −5.5%) is
  bigger than the average win (+3.1 to +3.7%), so every variant loses.
- The long breakouts do have a gross edge (+24 to +42 bps), but it is the daily trend seen hour by hour: holds of
  5–6 days, where funding (up to 15 bps) and fees take most of it. The daily trend bot already trades that move.
- Capital is not the obstacle: at $200 a position is $80 (over the $5 minimum); at $10,000 it is $4,000, a median
  0.01% of the signal hour's volume. The problem is the edge, not the account size.

## The site now shows only the four paper bots

`research/bots_stats.py` writes `lib/bot-stats.json` (the numbers the site shows); the dashboard's live section and
the home page read the bots' files on https://bot.da3m.io (CORS allowed in `deploy/vps/nginx-bot.da3m.io.conf`).
The old score strategies, Wave Flats and their numbers (`lib/strategy-stats.json`) are no longer shown.
