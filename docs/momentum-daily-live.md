# momentum_ls on real money: a new basket every day

**Owner's decision, 2026-11-11:** every real account trades the daily momentum basket, with no Demo step first. That
covers the main account (`raqm-live@momentum_ls`) and every user's account (`raqm-user@…--momentum_ls`, the second
account included).

- **When:** every day at 00:00 UTC (02:00 Cairo).
- **What:** the bot ranks the top 50 by 30-day volume on their last 2 weeks' return. It holds long the strongest 5
  and short the weakest 5, with a 40% stop.
- **A coin still in the day's basket on the same side is kept:** no order for it, and its stop stays on Binance.
- **A coin that left is closed.** A coin whose side flipped is closed and reopened on the new side. A new coin is
  opened.

| backtest 2019 → 2026-10, $20 ×2 | legs | net | worst DD | Sharpe < 2024 | Sharpe 2024 → |
|---|---|---|---|---|---|
| weekly, Monday (until now) | 3,410 | +$2,200 | $307 | 0.55 | 0.92 |
| **daily, keeping the coins still in it** | 6,094 | **+$3,035** | **$439** | 1.16 | 0.91 |

The worst drawdown is higher than the weekly bot's. Measured on paper since 2026-11-11 (`raqm-momentum-daily`).

## What changed in the code
- `bot.py --mom-daily` is allowed on real money. On a live rebalance (`bots/momentum_ls.py`), the exit basket holds
  only the coins that left or flipped, and the entry basket holds only the new ones. When nothing changed, no order
  is sent and the day is recorded as done.
- `scripts/provision_users.py`: every user's momentum_ls unit gets `--mom-daily` (`EXTRA_ARGS`).
- The rebalance check (`raqm-rebalance-check.timer`) runs every day at 00:20 UTC.
- realbot.da3m.io shows the next day as the next rebalance.
- The paper weekly bot keeps Wednesday-6 (docs/momentum-wednesday.md).

## Steps (each the owner's)
1. Deploy the live code: `sh /root/raqm-src/deploy/vps/deploy.sh <sha> live`.
   - **Users' accounts:** the users' provisioner runs every minute. Within a minute it rewrites each user's
     momentum_ls unit with `--mom-daily`. A bot that holds nothing restarts at once, and the second account holds
     nothing today. A bot with positions waits until it is flat.
   - **The second account's ledger:** the same run moves its limits to the users' 20% daily loss and 45% drawdown
     (PR #199).
2. **Main account:** add `--mom-daily` to its options file `/opt/raqm-live/strategies/momentum_ls.env`, as root:
   `RAQM_ARGS=--leverage 2 --amount 50 --poll 60 --mom-daily`
3. Bind the readiness evidence to the new commit again. `bot.py`, `bots/momentum_ls.py` and `risk_manager.py`
   changed.
4. Restart the main bot between cycles: `systemctl restart raqm-live@momentum_ls`. Check the first line of
   `journalctl -u raqm-live@momentum_ls -n 5`: it must say "سلة جديدة كل يوم 00:00 UTC" ("a new basket every day").

## Before either account opens anything
Both accounts have entries blocked today. Until each is cleared, its bot opens nothing (exits still run):
- **Main account:** the kill switch tripped at an 81% "drawdown" that was really withdrawals. Rebase the high-water
  mark with `rebase_hwm.py`, reset the kill switch from the dashboard, and deal with AIN and IDOL, which were
  opened by hand.
- **Second account:** the kill switch tripped on a 1.27% daily loss under the old 1% limit. CYS, MYX, ON and UAI
  are open on the account, and the bot didn't open them.

## Going back to weekly
- **Main account:** remove `--mom-daily` from the `.env` file and restart.
- **Users:** remove it from `EXTRA_ARGS`, merge, and deploy `live`.
