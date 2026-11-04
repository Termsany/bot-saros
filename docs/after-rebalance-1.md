# After the first real rebalance: one update of the real bot's folder

The first real rebalance is Monday 2026-11-09. Until it is checked, nothing in `/opt/raqm-live` changes. After it,
one `setup-live.sh` brings in everything that waited for it:
- **PR #89:** each strategy in its own file under `bots/`; the order path stays shared in `bot.py`.
- **The watchdog's vault alert (#109).**
- **The provisioner reading the site's tester approvals (#114).**

Do it on a weekday, away from 00:00 UTC (the daily close) and never on a Monday.

## 1. Monday: the rebalance is good
- **The Telegram messages at 00:20 UTC (02:20 Cairo):**
  - "🔄 تشييك التبديل الحقيقي" is all ✅;
  - the costs message follows it.
- **Any ❌:** stop here. Find out why, and fix that first.

## 2. Merge PR #89
- CI must be green: backend, frontend, e2e and secret-scan.
- Merging changes nothing on the server.

## 3. Install, without restarting anything
```bash
cd /root/raqm-src && git fetch -q origin && git checkout -q --detach origin/main
sudo deploy/vps/setup-live.sh "$(git rev-parse HEAD)"
```
- `setup-live.sh` installs `bot.py`, `bots/`, the scripts and the tools.
- **The running bots keep the code already in their memory.**
- The paper bots in `/opt/raqm-bot` need `bots/` copied next to `bot.py`, as in `deploy/vps/README.md`. A `bot.py` without `bots/` fails at import.

## 4. Demo first: restart the 6 Demo bots by name, never `raqm-demo@*`
```bash
for s in trend_daily ratio_trend vol_breakout trend_breakout rsi2_pullback listing_short; do systemctl restart raqm-demo@$s; done
```
- **Leave `raqm-demo@momentum_ls` masked.** Its unit conflicts with the real one.
- **Wait one cycle, then check each bot:**
  - active;
  - its `live_status.json` fresh;
  - `entry_block` empty;
  - no review.
- Any problem: roll back (step 8).

## 5. Bind the readiness evidence to the new commit
- The preflight compares the trading files with the reviewed commit, so it turns red after step 3. That is expected.
- The owner confirms the review of the new commit, by the same people as before, named honestly (`set_reviewers.py`). Then `reviewed_commit_sha` and `READINESS_EXPECTED_COMMIT_SHA` move to the new commit.
- `live_preflight.py` is 19/19 again before step 6.

## 6. The real bot
- Restart `raqm-live@momentum_ls` between cycles.
- Run `rebalance_check.py` without `--rebalance-day`. It must show:
  - the basket 5 + 5;
  - each leg's quantity equal to Binance's;
  - each leg's stop on Binance;
  - nothing on Binance the bot doesn't hold.
- The watchdog shows 0 problems.

## 7. Testers
- `provision_users.py --dry-run`: read what it would do.
- Then `systemctl enable --now raqm-users-provision.timer`.
- Testers come from the owner's gift invitations. Each one saves their own Binance Demo key on their own page.

## 8. Rolling back
- `setup-live.sh <the previous commit>`, then the same restarts: Demo first, the real bot last.
- The previous commit is in `/opt/raqm-live/DEPLOYED_COMMIT` before step 3.
