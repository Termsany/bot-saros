# The momentum day experiment on Demo: Wednesday open, 6 days held

> **Superseded 2026-11-11:** the owner moved every momentum_ls bot to Wednesday-6 without this Demo step
> (docs/momentum-wednesday.md). This unit now runs the same rule as the real bot.

**Owner's decision, 2026-11-06.** It tests on Binance Demo the best variant of research/README.md §23 that held up in
both periods: momentum_ls opening on **Wednesday 00:00 UTC** and closing after **6 days** (Tuesday 00:00), flat until
the next Wednesday. **The real bot doesn't change:** `raqm-live@momentum_ls` keeps Monday and the full week. `bot.py`
refuses `--mom-weekday` / `--mom-hold` on the real account.

| backtest, $26 ×2, 2019 → 2026-10 | net | worst DD | PF (2024 →) | Sharpe < 2024 | Sharpe 2024 → |
|---|---|---|---|---|---|
| Monday, 7 days (the real bot) | +$1,943 | $476 | 1.15 (1.20) | 0.60 | 1.15 |
| **Wednesday, 6 days (this test)** | +$2,527 | $323 | 1.20 (1.27) | 0.83 | 1.34 |

## How it runs
- Its own unit, `raqm-demo-momwed.service`: the Demo keys (`.env.live`) and the Demo ledger (`/opt/raqm-risk-demo`).
  It has its own status folder (`/opt/raqm-ipc/momentum_wed`) and its own state (`state/demo-momentum_wed.json`).
- It trades as `momentum_ls` on the Demo ledger. `raqm-demo@momentum_ls` stays masked, and the unit conflicts with it
  (only one momentum_ls on Demo at a time).
- The first basket opens at its first cycle (no rebalance yet means now), whatever the day. It closes 6 days later,
  and from then on it lines up on Wednesdays by itself.
- The watchdog watches it like the other Demo bots (`down:demo:momentum_wed`, `stale:…`, stops, reviews).

## Starting it (each step the owner's go)
Not with Tuesday's deploy (docs/after-rebalance-1.md): one change at a time. After that deploy is checked:
1. Merge this PR (CI green), then `setup-live.sh` with its commit. It installs the unit and makes its status folder,
   and it doesn't start it. `bot.py` and `bots/momentum_ls.py` change, so the readiness evidence is bound to the new
   commit again (after-rebalance-1 §6), by the owner.
2. Dashboard → التداول الحقيقي → **Demo**: switch **momentum_ls** on. It has been off on Demo since 2026-11-03
   (demo_selection #18), and without it the risk gate refuses every entry. The row shows "not running": that row reads
   `/opt/raqm-ipc/momentum_ls`, the real bot's folder. The experiment writes to its own folder.
3. `systemctl enable --now raqm-demo-momwed`.
4. Check after one cycle: `journalctl -u raqm-demo-momwed -n 30`, its 10 legs, each with its stop on Binance Demo.
   The Demo plan (5,000 / $40, 7 strategies on) gives each strategy 10 slots: exactly one basket.

## What it measures, and when to decide
- **Execution first:** each Tuesday's close leaves no order on the coins and no recovery, and each Wednesday opens
  10 legs with stops. That's the same checklist as the real Monday rebalance (docs/live-small-size-plan.md §1).
- **Results:** at least 8 weeks (80 legs) before any conclusion. Compare against the backtest's per-leg numbers, not
  against one good or bad week: about 70% of every variant's profit comes from its 10 best weeks (§23).
- **The real bot moves only if both hold:** the execution is clean, and Wednesday-6 on Demo isn't worse than
  Monday-7 on the real account over the same weeks. Then it's a planned change: the real unit gets
  `--mom-weekday 2 --mom-hold 6` (that needs a code change, since today those options are refused on real money),
  the readiness evidence is bound again, and the bot restarts between cycles.

## Stopping it
`systemctl disable --now raqm-demo-momwed`. Its open Demo legs stay on Demo with their stops: close them from Binance
Demo or by starting it again until its next close.
