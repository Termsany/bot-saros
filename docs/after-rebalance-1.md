# After the first real rebalance: one update of the real bot's folder and the API

The first real rebalance is Monday 2026-11-09. Until it is checked, nothing in `/opt/raqm-live` changes and the API
stays as it is. After it, one `setup-live.sh` and one manual API update bring in everything that waited:
- **PR #89:** each strategy in its own file under `bots/`; the order path stays shared in `bot.py`.
- **The watchdog's vault alert (#109).**
- **The provisioner reading the site's tester approvals (#114)**, and the users' real-money path (#135, #136).
  `provision_users.py` and `user_bots.py` were already installed on their own on 2026-11-05 (backups in
  `/root/provisioner-backup-20261105/`); `setup-live.sh` installs the same files again.
- **A live strategy on its own sub-account (#140, #141, #142):** `backend/app/live_accounts.py`, the root tool
  `/usr/local/lib/raqm/live_account.py`, the preflight, watchdog, backup and check per account, the dashboard per
  account (API), and the API unit's access to `/opt/raqm-risk-accounts`. Nothing changes for momentum_ls until a
  registry exists (`/etc/raqm-live/accounts.json`).

Do it on a weekday, away from 00:00 UTC (the daily close) and never on a Monday.

## 0. Before Monday
- The real account must hold enough for the new basket: per-trade risk is $20.8 ÷ the equity, under the 4.5% cap, so
  **below ≈ $462 of equity the rebalance's entries are refused** (2026-11-06: ≈ $489, after a −$20.79 stop on AIN).
- The kill switch clear (it was reset on 2026-11-06 after the $200 went back).

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
SHA=$(git rev-parse HEAD)
sh deploy/vps/deploy.sh "$SHA" --dry-run live paper    # write down each "previous" commit: the rollback (step 9)
sh deploy/vps/deploy.sh "$SHA" live paper
```
- `live` runs that commit's `setup-live.sh`: `bot.py`, `bots/`, the backend modules (now with `live_accounts.py`), the
  scripts and the tools. `paper` brings the same `bot.py` + `bots/` to `/opt/raqm-bot` and every own-folder paper bot
  (a `bot.py` without `bots/` fails at import). Every installed file is checked against git; any difference stops it (exit 5).
- **Nothing is restarted** (no `--restart`, no `--restart-demo`). The running bots keep the code already in their memory.
- `live` also rewrites `/opt/raqm-users/code`, the code every real-money user bot (`raqm-user@…`) runs. Those
  bots have `Restart=always`: any restart after this step loads the new code. Step 7b says how they're restarted.
  `deploy.sh` prints the restart command of each running `raqm-live@` / `raqm-user@` unit and never runs it.

## 4. The API: its code and its unit
The API's automatic update is frozen while live trading is on, so it gets the new commit by hand, after reading
`git diff <the API's commit>..<sha> -- backend/app`:
```bash
sh /root/raqm-src/deploy/vps/deploy.sh "$SHA" api
```
- It saves the old unit in `/var/lib/raqm-deploy/raqm-api.service.<time>`, installs the new one, `daemon-reload`, then
  `raqm-api-update --manual "$SHA"`, and checks the API's checkout and `backend/app` against git.
- The new unit adds `-/opt/raqm-risk-accounts` to `ReadWritePaths` (the "-" lets it start before that folder exists).
- Check: `https://api.da3m.io/api/health` answers. The dashboard's التداول الحقيقي tab shows momentum_ls, its capital
  ($500 / $26), its limits and a **قفل الطوارئ (الأساسي)** card that says "مش شغّال". There's no account picker yet,
  because no registry exists.

## 5. Demo first: restart the 6 Demo bots by name, never `raqm-demo@*`
```bash
sh /root/raqm-src/deploy/vps/deploy.sh "$SHA" live --restart-demo trend_daily,ratio_trend,vol_breakout,trend_breakout,rsi2_pullback,listing_short
```
- It installs again (idempotent), then restarts those six by name. It refuses `momentum_ls`, a pattern, a masked unit, and
  any strategy whose `raqm-live@` twin is running or enabled (`Conflicts=` would stop the real bot).
- **Leave `raqm-demo@momentum_ls` masked.** Its unit conflicts with the real one.
- **Wait one cycle, then check each bot:**
  - active;
  - its `live_status.json` fresh;
  - `entry_block` empty;
  - no review.
- Any problem: roll back (step 9).

## 6. Bind the readiness evidence to the new commit
- The preflight compares the trading files with the reviewed commit, so it turns red after step 3. That is expected
  (`bots/` and `backend/app/live_accounts.py` are new trading files).
- The owner confirms the review of the new commit, by the same people as before, named honestly (`set_reviewers.py`). Then `reviewed_commit_sha` and `READINESS_EXPECTED_COMMIT_SHA` move to the new commit.
- `live_preflight.py --strategy momentum_ls` passes every line again before step 7. It has one more line than the
  19 of before: "account — main".

## 7. The real bot
- Restart `raqm-live@momentum_ls` between cycles.
- Run `rebalance_check.py` without `--rebalance-day`. It must show:
  - the basket 5 + 5;
  - each leg's quantity equal to Binance's;
  - each leg's stop on Binance;
  - nothing on Binance the bot doesn't hold.
- The watchdog shows 0 problems.

## 7b. The users' real-money bots (the owner's second account first)
These run from `/opt/raqm-users/code`, which step 3 already updated. List the running ones:
```bash
systemctl list-units --type=service --state=running --no-legend 'raqm-user@*'
```
- **The restart is the owner's go:** real money. Do it between cycles, away from 00:00 UTC and never on the bot's
  rebalance day. One bot at a time, by its full instance name (`<uid>--<strategy>`), never `raqm-user@*`:
  ```bash
  systemctl restart 'raqm-user@<uid>--<strategy>'
  ```
- **Check it.** `rebalance_check.py` doesn't read user bots yet: their state is under `/var/lib/raqm-users/<uid>/` and
  their key is the user's own. So, read only:
  - `systemctl is-active` and `journalctl -u 'raqm-user@<uid>--<strategy>' --since -10min` show no traceback;
  - `tail -30 /var/lib/raqm-users/<uid>/state/<strategy>.log`: a new cycle, the same number of open positions as
    before the restart, no recovery or review line;
  - the positions and their stops match Binance on that account (the user's page, or the owner on Binance).
- A user bot whose kill switch is tripped stays tripped after the restart: resetting it is the owner's.
- Any problem: the owner decides whether to stop that bot (its stops stay on Binance) and looks at its positions
  there; then roll back (step 9).

## 8. Testers
- `provision_users.py --dry-run`: read what it would do.
- Then `systemctl enable --now raqm-users-provision.timer`.
- Testers come from the owner's gift invitations. Each one saves their own Binance Demo key on their own page.
- Real money for users stays off: root's `/etc/raqm-users/live.enabled` is the owner's to create, after the Demo test
  user (docs/users-real-money-plan.md).

## 9. Rolling back
- `deploy.sh <the previous commit> live paper` (the "rollback:" line step 3 printed; run it with the clone left at the
  new commit — a previous commit from before `deploy.sh` existed is deployed by the new `deploy.sh`), then the same restarts: Demo first
  (`--restart-demo …`), the real bot, then the users' bots (step 7b; the previous commit's code goes back to
  `/opt/raqm-users/code` too).
- The API: `deploy.sh <the previous commit> api` installs that commit's unit and code (the unit of step 4 is also saved in
  `/var/lib/raqm-deploy/raqm-api.service.<time>`).
- The previous commit is the one written down in step 3.

## Later: trend_daily on its own sub-account (docs/trend-daily-live-plan.md)
Not part of this update. It comes after the trend Demo gate (§1 of that plan), and every step is the owner's go:
1. The owner opens a second Binance sub-account (futures, one-way mode) and makes a key with withdrawals off,
   restricted to 148.230.113.18, futures on. They transfer its capital.
2. With `raqm-live@trend_daily` stopped and flat:
   `sudo /opt/raqm-live/venv/bin/python -I /usr/local/lib/raqm/live_account.py add trend trend_daily`.
3. The owner writes `/etc/raqm-live/accounts/trend/binance` and `/etc/raqm-live/accounts/trend/allow-live.env`
   (root, 600) themselves.
4. On the dashboard, account **trend**: its capital, limits and yes/no for trend_daily (the activation's name is `trend`).
5. `live_preflight.py --strategy trend_daily` passes every line; then the owner starts `raqm-live@trend_daily`.
6. Check it against its own account, read only:
   `sudo env BINANCE_ENV=live CREDENTIALS_DIRECTORY=/etc/raqm-live/accounts/trend /opt/raqm-live/venv/bin/python -E -s /opt/raqm-live/scripts/rebalance_check.py --strategy trend_daily`.
