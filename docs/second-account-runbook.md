# A second account for momentum_ls (owner, 2026-11-07)

**The owner's decision:** a second Binance sub-account of their own with **$300**, running momentum_ls at **$24
margin** with a **20% reserve**, from **Monday 2026-11-09**, next to the main account ($500, $26), which doesn't change.
The owner saw the backtest at this size: +$1,793 since 2019, worst drawdown $439 (146% of the capital), the kill
switch (45%) tripped 3 times, worst week −$100. One stop costs $19.2 (6.4%), all 10 at once $192 (64%). BTC is skipped
($48 a leg is under Binance's $50 minimum).

The copy runs the same bot.py as the main one, in its own unit `raqm-live-mom2@momentum_ls`, with its own keys
(LoadCredential), ceilings, ledger and activation (`/opt/raqm-risk-accounts/mom2`), status folder
(`/opt/raqm-ipc/acct-mom2/momentum_ls`) and state (`state/live-mom2-momentum_ls.json`). The main account's keys and
ledger are hidden from it. The account name is `mom2` below; any 2–16 lowercase letters/digits works.

## Sunday: install the new files only, restart nothing
Not `setup-live.sh` (that waits for after-rebalance-1). From `/root/raqm-src` at the merged commit, root:root 644:
| file | to |
|---|---|
| `backend/app/live_accounts.py` | `/opt/raqm-live/backend/app/` (new; bot.py doesn't import it) |
| `scripts/watchdog.py`, `backup.py`, `live_preflight.py`, `rebalance_check.py` | `/opt/raqm-live/scripts/` |
| `deploy/vps/tools/live_account.py` | `/usr/local/lib/raqm/` |

Back up each old copy first. The running bots keep their code in memory. Then run the watchdog and the backup once by
hand (no registry yet: nothing changes in what they watch), and `live_preflight.py --strategy momentum_ls` for the
main account.

**Readiness:** `live_accounts.py` is a new file in the folder the readiness evidence is bound to. If the preflight's
"readiness bound to the deployed code" line turns red, the owner confirms the review of the new commit (the same
reviewers, named honestly) and the binding moves, as after-rebalance-1 §6. The main bot keeps trading either way.
The line only says what was reviewed.

## Monday, after the 00:20 UTC check of the main rebalance is all ✅
1. **The owner, on Binance:** the sub-account, $300 in its USDT-M futures wallet, one-way mode, nothing else on it.
   An API key with futures on, withdrawals off, restricted to 148.230.113.18.
2. `sudo /opt/raqm-live/venv/bin/python -I /usr/local/lib/raqm/live_account.py add-copy mom2 momentum_ls`
3. **The owner writes** (root, 600):
   - `/etc/raqm-live/accounts/mom2/binance`: `BINANCE_API_KEY=` / `BINANCE_SECRET=`
   - `/etc/raqm-live/accounts/mom2/allow-live.env`:
     ```
     ALLOW_LIVE_TRADING=true
     BINANCE_LIVE_ACCOUNT=mom2
     RAQM_CAP_RISK_PER_TRADE_PCT=7
     RAQM_CAP_AGGREGATE_RISK_PCT=66
     RAQM_CAP_CORRELATED_RISK_PCT=35
     RAQM_CAP_DAILY_LOSS_PCT=20
     RAQM_CAP_DRAWDOWN_PCT=45
     ```
     A cap of exactly 6.4% would refuse every entry: per trade is $19.2 ÷ the equity, so 6.42% at $299. Hence 7 / 66 / 35.
4. **Its ledger, as raqmlive** (the bot's user creates it, mode 660). The API's dashboard per account comes with
   Tuesday's deploy. The values are the owner's: capital 300, margin 24, reserve 20 → 300 × 80% ÷ 24 = 10 trades, one
   basket. Limits per trade 7, aggregate 66, correlated 35, daily 20, drawdown 45.
5. **Its activation, as raqmlive, the owner's go:** `live_activation.activate` on
   `/opt/raqm-risk-accounts/mom2/live_activation.sqlite3`, environment live, account `mom2`, strategies `momentum_ls`,
   with the API's readiness evidence and `READINESS_EXPECTED_COMMIT_SHA`.
6. `sudo /opt/raqm-live/venv/bin/python -I /opt/raqm-live/scripts/live_preflight.py --strategy momentum_ls --account mom2`:
   every line ✅ (its key isn't the main one's, the unit is as written, its ledger and kill switch, one-way, withdrawals
   off, the basket fits its ceilings).
7. `systemctl enable --now raqm-live-mom2@momentum_ls`. With no rebalance yet, it opens its basket at its first cycle,
   at Monday's prices. Its next rebalance is Monday 2026-11-16.
8. Check it against its own account, read only:
   `sudo env BINANCE_ENV=live CREDENTIALS_DIRECTORY=/etc/raqm-live/accounts/mom2 /opt/raqm-live/venv/bin/python -E -s /opt/raqm-live/scripts/rebalance_check.py --strategy momentum_ls --account mom2`
   → 5 + 5, each quantity = Binance, each stop on Binance, nothing foreign. The watchdog then watches
   `raqm-live-mom2@momentum_ls` and the `mom2` kill switch on their own.

## Good to know
- Its Telegram messages look like the main bot's (same strategy name, same chat).
- Not yet for the copy: realbot.da3m.io, the Monday 00:20 automatic check (run step 8 after each rebalance), the
  dashboard's close buttons (close from Binance), and the weekly report. The dashboard shows it after Tuesday's API deploy.
- **Stop it:** `systemctl disable --now raqm-live-mom2@momentum_ls`. Its legs stay on Binance with their stops.
  `live_account.py remove-copy mom2 momentum_ls` once flat.
