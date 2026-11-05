# trend_daily: small-size real money, next to momentum_ls (plan, 2026-11-05)

**Status: a plan, nothing done.** Not before the first real momentum rebalance (Monday 2026-11-09) is verified and
`docs/after-rebalance-1.md` is through. Every step that touches the real account is the owner's go.

## Why this bot

Of the seven strategies, `trend_daily` has the strongest evidence (research/README.md, "Daily trend following"):
backtest profit factor **2.2** (2.26 since 2024), out-of-sample Sharpe **1.33**, every Binance USDT-M coin in the
top 10 by volume since 2019, fees and real funding. It is long-only and follows trends, so it complements
`momentum_ls` (long/short, relative strength): together the research's drawdown was smaller than either alone.

What it is **not** yet: measured. On Demo it has 1 of its 30 own trades (docs/demo-baseline.md rule; the Demo risk
gate refused every entry from 2026-11-04 to 2026-11-05 — fixed). On paper it closed 7 of 7 at a loss (−$53, 8 still
open): with a 30% win rate, 7 losses in a row happen about 8% of the time, but it is no evidence either way. As with
momentum (docs/live-small-size-plan.md), the first real weeks are the measurement, so the size stays at the minimum.

| backtest (docs/demo-baseline.md) | trades/month | win rate | avg win / loss (of margin) | PF | worst DD | most open |
|---|---|---|---|---|---|---|
| trend_daily | 11.4 (12.1 since 2024) | 30.4% | +55.5% / −11.0% | 2.2 | 15.6 margins | 20 |

A trend bot wins rarely and big: long losing streaks are normal and are not, alone, a reason to stop it.

## 1. The Demo gate (the week after 2026-11-09)

The Demo trend bot must show the execution works before real money, on its own trades:

- [ ] `manual_hold` cleared on Demo for the coins closed on 2026-11-03/04 (HYPE, NEAR, ZEC, 1000PEPE, BNB — they
      were closed outside the bot and are held off re-entry); the cause of the 2026-11-04 00:04 closes known
- [ ] at least one entry with its stop on the exchange (quantity and stop price checked on Binance)
- [ ] at least one exit by the strategy's own rule ("trend stopped"), its stop cancelled on the exchange
- [ ] no `recovery_required`, no risk-gate refusal that the plan below would not also give, no watchdog alert
- [ ] fees, funding and slippage per trade not far from the backtest's

Any box unchecked: stop, find out why, fix it, wait another week.

## 2. The account: the same sub-account, more capital

The account's capital plan is **one margin and one count for every strategy on it**, and the count is split evenly
between the strategies that share it (`risk_manager.capital_plan`, `strategy_slots`). momentum_ls needs its 10 legs,
so with two strategies the plan must allow at least 20 trades:

  max open = capital × (1 − 40% reserve) ÷ margin ≥ 20  →  at $26 margin, capital ≥ **$867**

Today's $500 allows 11, which momentum alone needs. Options:

| | capital | margin | max open (each) | one stop | every stop at once |
|---|---|---|---|---|---|
| **A — recommended: same sub-account, owner adds $500** | **$1,000** | $26 | 23 (11 each) | $20.8 = 2.1% | 20 × 20.8 = $416 = 41.6% |
| B — a second sub-account for trend alone | needs code: the bot has one live ledger and one key set | — | — | — | — |
| C — lower margin on $500 | not possible: the margin is shared, momentum needs $26 (BTC's $50 minimum at x2) | — | — | — | — |

**A** it is, unless the owner decides otherwise. The transfer is the owner's, on Binance.

At $26 the trend bot's notional is $52 × its volatility size (≤ 1): when the size factor is below ~0.96, BTC's $50
minimum can't be met and the bot skips BTC (the plan's rule: coins whose minimum order is above the size are
skipped). The other top-10 coins have $5–$20 minimums.

## 3. Ceilings and limits for $1,000

`allow-live.env` (root) and the real ledger's limits on the dashboard (التداول الحقيقي → المخاطر), the gate taking the
lower of the two:

```
RAQM_CAP_RISK_PER_TRADE_PCT=2.5       # one stop 2.08%
RAQM_CAP_AGGREGATE_RISK_PCT=45        # both bots at every stop 41.6%
RAQM_CAP_CORRELATED_RISK_PCT=35       # every long at its stop: 10 trend + 5 momentum = 31.2%
RAQM_CAP_DAILY_LOSS_PCT=20
RAQM_CAP_DRAWDOWN_PCT=45
```

Dashboard, real account: capital **1000**, manual margin **26** (unchanged), `momentum_ls` and `trend_daily` on.
These are the go-live values; recheck them with the preflight's own arithmetic before writing them.

## 4. The stop rule (agreed before the first real trade)

- **Size:** $26 until 30 closed trend trades (~3 months at 11 a month).
- **Switched off, not re-tuned,** when either: its realised loss reaches **$400** (≈ the backtest's worst drawdown,
  15.6 margins × $26), or after 30 trades its profit factor is under 1. A drawdown inside $400 is the strategy
  working as tested and is not a reason to stop it.
- Any recovery, a stop missing on the exchange or a watchdog alert at any point: kill switch, then find out why.
- After 30 trades within the baseline: the owner may raise the size step by step.

## 5. Go live (owner's go at each step)

1. §1 all checked; PR #89 merged and `setup-live.sh` run as `docs/after-rebalance-1.md` says.
2. The owner transfers the capital to the sub-account (§2).
3. `allow-live.env` and the dashboard limits as in §3; `ALLOW_LIVE_TRADING` stays as it is for momentum.
4. `sudo /opt/raqm-live/venv/bin/python -I /opt/raqm-live/scripts/live_preflight.py --strategy trend_daily` passes;
   then again with `--strategy momentum_ls` (the new plan must still fit its basket).
5. `readiness_evidence.json`: the owner's record now names trend_daily too (the preflight checks its form, commit
   and digest — see docs/live-small-size-plan.md §4).
6. The admin page, real account: add `trend_daily` to the activation (account name unchanged).
7. Stop `raqm-demo@trend_daily`, start `raqm-live@trend_daily` — the Demo trend measurement ends there.
8. Watch the first real daily close (00:00 UTC): entries sized ≈ $52 × size factor, each with its stop on Binance;
   momentum's 10 legs untouched.
