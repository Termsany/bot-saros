# Roadmap (from 2026-11-03, with momentum_ls live)

The rule for every step: **the real bot keeps running and is touched last.** A change reaches Demo first, is seen
working there, and only then the real bot, outside a rebalance. Each step ships as its own PR, merged after green CI.

Where things stand: [production-readiness.md](production-readiness.md). The small-size plan: [live-small-size-plan.md](live-small-size-plan.md).

Owner = only the owner can do it (keys, Binance, money, names). Claude = code, server, checks.

## A. Protect the live bot — now → Monday 2026-11-09

| # | Step | Who | Done when |
|---|---|---|---|
| A1 | ~~Demo measurement restarted~~ (6 strategies back on, 2026-11-03 21:55 UTC) | Claude, owner's go | ✓ every Demo bot's `entry_block` empty |
| A2 | ~~Close the leftover Demo `momentum_ls` legs~~ (9, not 10: closed 2026-11-03 ~22:02 UTC by the bot's own rebalance exit, net ≈ −2.3 USDT; no order left on them, Demo ledger holds only trend_daily 4 + ratio_trend 2) | Claude, owner's go | ✓ Demo account has only legs some bot owns |
| A3 | Revoke the old main-account API key on Binance | Owner | key gone from Binance's API list |
| A4 | Put real reviewer names in `readiness_evidence.json` | Owner | evidence names people, digest re-made |
| A5 | ~~Test that a live-bot problem reaches Telegram~~ (2026-11-03: the watchdog's own check and send on a copy of the real status with one stop marked unverified; alert + clear received by the owner) | Claude | ✓ message received and cleared |
| A6 | ~~Demo/real can't be mixed up on the dashboard~~: the card says which account it changes (red = real, blue = Demo), the confirm lists what starts **and what stops**, the 15 s refresh no longer wipes unsaved switches, a late answer for the other tab is dropped | Claude | ✓ PR merged |
| A7 | **Watch the first real rebalance** (Mon 00:00 UTC = 02:00 Cairo): old legs closed with fills/fees/funding, no old stop left, 10 new legs with stops, no recovery | Claude + owner | checklist in the plan §1 all ticked |

## B. Make it solid — 2026-11-09 → 2026-11-23 (rebalances 2 and 3)

| # | Step | Done when |
|---|---|---|
| B1 | PR #89 (one file per strategy): merge after A7, restart Demo bots **by name, never `raqm-demo@*`** (starting `raqm-demo@momentum_ls` stops the real bot: `Conflicts=`), run `demo_e2e`'s `cli` path, then restart the real bot on a weekday between rebalances | real bot runs the new code, positions untouched |
| B2 | CI runs `python bot.py` as `__main__` once against the fake exchange (the gap PR #89 showed) | a test fails if the entry point breaks |
| B3 | Real results per rebalance: fees, funding and slippage per leg vs the backtest, kept by the bot and shown on realbot.da3m.io / dashboard | each week's real costs readable without the server |
| B4 | Restore test: rebuild the real ledger + state from last night's backup on a scratch folder | restore proven, steps written down |
| B5 | Weekly Demo check of the 6 strategies against [demo-baseline.md](demo-baseline.md) | a line per strategy per week in production-readiness.md |

## C. The size decision — after the 3rd real rebalance (~2026-11-24)

About 30 closed real legs. Compare with the baseline (win rate ≈ 49 %, PF ≈ 1.2 net of real fees and funding;
read against the 7-weekday average, PF ≈ 1.15):
- **within it** → raise one step: $26 → $40 per leg, ceilings and capital recomputed, preflight 13/13, 3 more rebalances;
- **far below it** → switch `momentum_ls` off on real money (not re-tuned), back to Demo only.

Never more than one step up at a time, and never inside the week of a loss bigger than the basket's normal range.

## D. A second strategy on real money — from ~December

- The first Demo strategy to finish its sample within baseline goes next (most likely `trend_daily` or `ratio_trend`;
  `rsi2_pullback` and `listing_short` trade too rarely to be first).
- Its own sub-account and key, its own capital and ceilings — one bot per account keeps "no positions the bot didn't
  open" simple and one strategy's loss away from the other's.
- Same path as momentum_ls: preflight, smallest size, 3 rebalances / ~30 trades, then the size decision.

## E. Users — in parallel, Demo only

[phase2-design.md](phase2-design.md): a user's bot runs on the owner's order path, on the user's own Binance Demo key.
1. The first testers' user IDs into `/etc/raqm-users/allow.list` (owner gives them).
2. The provisioner starts `raqm-user@<uid>--<strategy>` from the dashboard's choice; per-user ledger, limits and
   kill switch; a user can only see and close their own bot.
3. Watch it with 2–3 testers for two weeks before opening it wider.

Real money for users is **not** on this roadmap: it needs the owner's own results first and a legal/terms review.

## F. Always on

- Each week: dependency and security updates (backend, frontend, bot) through PRs; secret-scan stays green.
- Each month: rotate the bot's API key (owner creates it, Claude installs nothing secret).
- Any recovery, stop missing on the exchange, or watchdog alert on the real bot: kill switch first, then find out why.
