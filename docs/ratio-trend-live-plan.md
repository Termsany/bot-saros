# ratio_trend: real money next to momentum_ls (plan, 2026-11-05)

**Status: a plan, nothing done; a code change comes first.** The owner asked (2026-11-05) to prepare `ratio_trend`
for real money on the same account as `momentum_ls`. Nothing here starts before the first real momentum rebalance
(Monday 2026-11-09) is verified and `docs/after-rebalance-1.md` is through. Every step that touches the real account
is the owner's go.

## What the evidence says today

| source | what it ran | result |
|---|---|---|
| backtest (docs/demo-baseline.md) | every pair among the weekly top 7 by volume, long the stronger / short the weaker while the ratio is above its 50-day mean | PF 1.37 (1.31 since 2024), 31% wins, **worst drawdown 39.7 margins**, the largest of the seven bots (momentum 12.1) |
| research/README.md §11–13 | the same, judged fairly (coins picked by what was known at the time) | edge kept but weak: Sharpe after 2024 0.67–0.77; marked **HIGH RISK, not adopted** |
| paper bot `raqm-ratio` (2026-10-30 →, $100 margin per leg, 21 pairs) | the full strategy | 42 closed, 6 won, 36 lost, **−$346.68** (−3.5 margins in a week, realised only) |
| Demo `raqm-demo@ratio_trend` | the live path | 8 legs closed, **none by the strategy's own rule** (5 by hand from the site or Binance, 1 orphan exit, 1 stop); at most 2 pairs open at once. Its +$3.38 measures nothing |

A trend strategy loses often and wins big, so one bad week on paper is no proof; 6 wins in 42 against an expected
31% happens about 1% of the time, but the paper week's open pairs aren't counted. The Demo run is the real problem: the live
execution of this strategy has not been measured at all.

## 1. The blocker: the live path is not the tested strategy

The strategy wants all 21 pairs of 7 coins, so each coin is in 6 pairs at once (e.g. long BTC against ETH, short
BTC against HYPE). The live path keeps **one position per coin** (`state["positions"][symbol]`), and Binance in
one-way mode holds one net position per coin per account. A second pair that needs a coin already held can't open.
So live runs at most 3 coin-disjoint pairs, whichever signalled first, not the 21 the backtest measured.

**The fix (code, Demo first):** trade the strategy's **net position per coin**, the sum of its pair legs. With the
ratios ordered, the 7 coins come out at +6, +4, +2, 0, −2, −4, −6 margins. That's a weekly/daily target basket like
momentum's, with one position and one stop per coin, and it has the same PnL as the 21 pairs, minus the fees of
the legs that cancel out. Then:
- a backtest check that the netted version reproduces the baseline (`research/baseline_stats.py`);
- unit tests on the netting and on a flip;
- `scripts/demo_e2e.py` for the netted basket;
- a Demo gate (§3).

## 2. One account, three bots: the coin collisions

On one Binance account a coin has one net position, and the risk gate refuses a second strategy on a coin another
already holds ("strategy conflict"). ratio_trend's 7 coins are the top of the volume list, the same coins
trend_daily trades (top 10) and often some of momentum's 50. On a shared account the first bot to take a coin keeps
it, and the others skip it, so none of them runs as tested. Options:

| | how | cost |
|---|---|---|
| **A — recommended: its own sub-account** | a second Binance sub-account and key for ratio_trend only | code: the bot has one live ledger and one key set today (the same blocker as trend_daily option B) |
| B — same account, ratio_trend instead of trend_daily | never run both | trend_daily has the stronger evidence (PF 2.2) |
| C — same account, accept the skips | first come first served | the result can't be compared with any backtest |

## 3. The Demo gate (after §1 is built)

- [ ] a full netted basket opened: 6 coins with a position (one is 0), each quantity = the target, each stop on Binance
- [ ] at least one change made by the strategy's own rule (a ratio crossing its mean), the old stops cancelled
- [ ] no `recovery_required`, no watchdog alert, no refusal the real plan would not also give
- [ ] two weeks without a hand close (hand closes are what made the current Demo run unreadable)
- [ ] fees + funding per change not far above the backtest's

## 4. Size: what the tested drawdown means in dollars

At momentum's $26 margin per unit, the netted basket holds up to 24 margins: $624 margin, $1,248 notional at x2.
The backtest's worst drawdown, 39.7 margins, is **≈ $1,032**. The account's drawdown limit is 45% (it trips the kill
switch), so the drawdown alone needs ≈ $2,300 of capital, ≈ **$3,000** with momentum's basket (and its own $208 at
every stop) on the same account. Smaller is possible only with a smaller unit, and BTC's $50 minimum at x2 ($25
margin) sets the floor: a unit of $13 can't hold BTC at ±1 unit, and BTC is always one of the 7.

| capital | unit | ratio worst DD (39.7 units) | % of capital | fits the 45% limit? |
|---|---|---|---|---|
| $1,000 | $26 | $1,032 | 103% | no |
| $3,000 | $26 | $1,032 | 34% (+ momentum) | yes, barely |

## 5. The stop rule (agreed before the first real trade)

- **Switched off, not re-tuned,** when its realised loss reaches the backtest's worst drawdown in dollars, or after
  30 strategy-closed trades its PF is under 1.
- Any recovery, a stop missing on the exchange, or a watchdog alert: kill switch, then find out why.

## 6. Order

1. Monday 2026-11-09: momentum's first real rebalance verified; `docs/after-rebalance-1.md`.
2. The netting code (§1) and the account decision (§2): the owner picks A, B or C.
3. Demo gate (§3), two weeks at least.
4. The owner adds the capital (§4); ceilings and dashboard limits recomputed with the preflight's own arithmetic.
5. `live_preflight.py --strategy ratio_trend` passes; readiness evidence names ratio_trend; owner's go.

`trend_daily` (docs/trend-daily-live-plan.md) needs none of §1 and has the stronger evidence. If only one of the two
goes next, it should be trend_daily.
