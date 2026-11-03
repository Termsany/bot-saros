# momentum_ls: small-size real money (owner's decision, 2026-11-03)

The owner chose not to wait for the full Demo sample (about 30 closed trades, ~4 weekly rebalances). Instead:
**one clean Demo rebalance, then real money at the smallest size, and the first real weeks are the measurement.**

What one Demo week proves, and what it doesn't: one rebalance is one basket of 10 legs opened at the same moment in
the same market — one experiment, not ten. It **validates the execution** (close the old basket, its stops gone,
open the new one with stops, fees/funding/slippage close to the backtest, no recovery). It **does not show the
strategy is profitable** (backtest profit factor ≈ 1.2: a single week can go either way by chance). Size is what
bounds that risk, so the size stays at the minimum until the real sample exists.

## 1. The Demo gate — rebalance of 2026-11-10 00:00 UTC

The basket opened 2026-11-03 (10 legs, $40 margin, every leg's stop on the exchange — checked against Binance).
After the 2026-11-10 rebalance, on the Demo account:

- [ ] the 10 old legs closed, each with an exchange fill price, fees and funding recorded
- [ ] **none of the old legs' stops left on the exchange** (the bug PR #77 fixed)
- [ ] 10 new legs open, each with its own stop at 40%, exchange quantity = bot quantity
- [ ] no `recovery_required`, no watchdog alert, kill switch clear
- [ ] the week's fees + funding + slippage per leg not far above the backtest's (baseline: docs/demo-baseline.md)

Any box unchecked: stop here, find out why, fix it, and wait for the next rebalance.

## 2. The real account

- A **Binance sub-account used by the bot alone** — the bot blocks entries next to any position it did not open.
  Transfer only the capital for this.
- Futures in **one-way** mode.
- API key: futures on, **withdrawals off**, **restricted to the server's IP (148.230.113.18)**.
- Keys into `/opt/raqm-live/.env.real` (raqmlive, 600) — by the owner, not by an assistant.

## 3. Size and ceilings

Margin **$26 per leg** (the smallest that still meets Binance's $50 BTC minimum at x2 — the picks are the top 50 by
volume and can include BTC). Per leg at its 40% stop: 26 × 2 × 0.40 = **$20.8**; the whole basket at its stops:
**$208** — the most this size can lose in a week, whatever the capital. Capital needs at least 26 × 10 / 0.6 ≈ $434
with the 40% reserve.

The ceilings (`allow-live.env`) and the gate's limits are in % of the account's **equity on Binance**, not of the
dashboard's capital — so keep on the sub-account only the capital meant for the bot. Per-trade ≥ 2080 / equity,
aggregate ≥ 10 × that.

**Owner's choice: $500** (in `allow-live.env` since 2026-11-03, with ALLOW_LIVE_TRADING=false). $500 − 40% reserve =
$300 = 11 trades of $26, so the 10-leg basket fits. At this size one leg at its stop is **4.2%** of the account, the
whole basket at its stops **41.6% ($208)**, one side **20.8%**:

```
RAQM_CAP_RISK_PER_TRADE_PCT=4.5
RAQM_CAP_AGGREGATE_RISK_PCT=45
RAQM_CAP_CORRELATED_RISK_PCT=25
RAQM_CAP_DAILY_LOSS_PCT=20
RAQM_CAP_DRAWDOWN_PCT=45
```

(For $1,500 the same size would be 1.5 / 15 / 15 / 10 / 25.)

Dashboard, real account:
- التداول الحقيقي → فلوس حقيقية: capital = the sub-account's capital, manual margin **26**, only `momentum_ls` on.
- المخاطر (risk limits of the real ledger): the same numbers as the ceilings. The gate takes the **lower** of the
  dashboard's limit and root's ceiling, and the dashboard's defaults (0.25% per trade, 1% aggregate) refuse a
  momentum_ls basket.

The preflight checks the basket against both at that margin (per leg, whole basket, and one side against the
correlated limit) and names which one binds.

## 4. Go live

1. `sudo /opt/raqm-live/venv/bin/python -I /opt/raqm-live/scripts/live_preflight.py --strategy momentum_ls`
   must print **13/13** (it also checks the key's withdrawal/IP restrictions on Binance itself).
2. `readiness_evidence.json` (schema v2, in `/opt/raqm-api/app/`) is the owner's signed-off record: what was
   validated, for the deployed commit, by whom. It is the owner's to write and vouch for — the preflight only
   checks its form, its commit and its digest. Digest of a drafted file:
   `/opt/raqm-api/venv/bin/python -c "import json,sys; sys.path.insert(0,'/opt/raqm-api/app/backend'); from app.testnet_readiness import evidence_artifact_sha256 as d; print(d(json.load(open('/opt/raqm-api/app/readiness_evidence.json'))))"`
3. Start only `raqm-live@momentum_ls`; stop `raqm-demo@momentum_ls` (the unit conflicts with it anyway).
4. Watch the first real rebalance as it happens: 10 legs, 10 stops on Binance, sizes ≈ $52 each.

## 5. The real measurement

- Size stays at $26 per leg for **at least 3 rebalances** (~30 closed legs).
- After them: compare with the baseline (win rate ≈ 49%, profit factor ≈ 1.2, net of real fees and funding).
  Within it → the owner may raise the size step by step. Far from it → switch the strategy off; it is not re-tuned.
- Any recovery, a stop missing on the exchange, or a watchdog alert at any point: kill switch, then find out why.
