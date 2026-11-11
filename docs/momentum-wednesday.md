# momentum_ls moves to Wednesday, 6 days held

**Owner's decision, 2026-11-11.** Every momentum_ls bot opens its basket on **Wednesday 00:00 UTC** (02:00 Cairo) and
closes it on **Tuesday 00:00 UTC**, 6 days later, then stays flat until the next Wednesday. Until now it opened on
Monday and held the full week.

| backtest, $26 ×2, 2019 → 2026-10 (research/README.md §23) | net | worst DD | Sharpe < 2024 | Sharpe 2024 → |
|---|---|---|---|---|
| Monday, 7 days (until now) | +$1,943 | $476 | 0.60 | 1.15 |
| **Wednesday, 6 days (from now)** | +$2,527 | $323 | 0.83 | 1.34 |

Not yet tested on Demo: the Wednesday Demo unit (docs/momentum-wed-demo.md) was never started. This is the owner's
call to move without that step.

## What changes
- `bots/momentum_ls.py` MOM: `weekday` 2, `hold_days` 6, and `catch_up_days` 1.
- **A missed Wednesday:** the bot can be down, or entries blocked (kill switch, positions the bot didn't open). It
  still opens on Thursday at the latest. After that it waits for the next Wednesday rather than open a basket for a
  few days.
- **A late basket keeps the week's close:** `mom_last` records the week's Wednesday (`momentum_slot`), so a Thursday
  basket still closes on Tuesday.
- The paper momentum bot moves too (same code). The crowd bot (`retail_fade`) keeps Wednesday and its full 7 days.
- The real-bot page (realbot.da3m.io) shows the next Wednesday.
- The rebalance check timer runs on Wednesdays at 00:20 UTC.
- `--mom-weekday` / `--mom-hold` remain Demo-only overrides.

## The switch (from the last Monday basket)
- Both real momentum bots hold nothing today (2026-11-11). The main account's last basket was 2026-11-03, the second
  account's 2026-11-09. Both have entries blocked (kill switch, foreign positions).
- **Deployed on Wednesday 11-11 or Thursday 11-12:** this week is still open, so a bot whose entries are allowed opens
  at once and closes on Tuesday 11-17. The paper bot does that too.
- **Deployed from Friday 11-13:** nothing opens until **Wednesday 11-18**. A Monday basket still open (paper) closes
  6 days after its Monday, on Sunday.

## Steps (each the owner's)
1. Merge the PR once CI is green.
2. Deploy: `sh /root/raqm-src/deploy/vps/deploy.sh <sha> --restart live paper:momentum`.
   - `live` runs setup-live: `/opt/raqm-live`, the users' code, the units (the rebalance-check timer moves to
     Wednesday), and realbot.da3m.io's page.
   - `--restart` restarts the paper momentum bot only. It never restarts a real one.
3. Bind the readiness evidence to the new commit again, because `bot.py` and `bots/momentum_ls.py` changed.
4. Restart the real bots between cycles:
   - `systemctl restart raqm-live@momentum_ls`
   - the second account's `raqm-user@…--momentum_ls`

   Until they restart, they keep running the old code (Monday) from memory.
5. Check after the first Wednesday:
   - `journalctl -u raqm-live@momentum_ls -n 30`, and the 10 legs with their stops.
   - On Tuesday: all 10 legs closed and no order left.
