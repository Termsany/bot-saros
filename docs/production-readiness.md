# Bot Saros production-readiness matrix

Status is **NO-GO**. Paper mode remains the only permitted operating mode for real money.

_Last updated 2026-10-29 after the third pre-production review (PR #29) and its deploy to the VPS._
Previous version: 2026-10-29 after PRs #21–#23 and the Demo run (recorded `dc4ecb9` as deployed; the VPS was actually
already on `e7a7bf9` by then — PR #28's second-review fixes). Before that: 2026-10-26 (28a8249), pre-PRs #12–#16.

## Where the roadmap stands

The live-trading roadmap runs **Phase 1 — real end-to-end validation on Binance's test environment (Futures Demo
Trading)** and **Phase 2 — per-user live infrastructure**. Phase 2 was built first, as library code only (PR #12).
**Phase 1 is done for every remaining strategy: all seven have been run end to end against the exchange.**
`ict` and `wave_flats` were dropped by the owner on 2026-10-29 (`RETIRED_STRATEGIES` in bot.py: refused by `--strategy`,
paper or live). The `ict` indicator ensemble still drives the dashboard's paper loop; it is not a live strategy.

## Strategy matrix

The seven names are in `LIVE_READY_STRATEGIES` (bot.py), so `--live` accepts them; that only means the
execution code is reachable, not that it is validated.

| Strategy | Paper bot on the VPS | Live execution path | Unit/integration tests (fake exchange) | Exchange end-to-end (Demo) | Status |
|---|---|---|---|---|---|
| `trend_daily` | Running | Hardened dedicated path (`_enter_trend_live`, `close_live_position`, `reconcile_live`) | Yes | **Done** (PR #16): entry + exchange stop, 4 concurrent positions capped by the aggregate risk gate, restart with no duplicates / no false recovery, out-of-band manual close detected with correct PnL. Demo account, no real funds | Blocked: final independent review, deploy of the reviewed code |
| `vol_breakout` | Running | Shared single-leg path | Yes | **Done** (2026-10-29, `scripts/demo_e2e.py`): entry, exchange stop, restart with no duplicates / no false recovery, exit with stop cancelled and risk released | Blocked: final review, deploy |
| `rsi2_pullback` | Running | Shared single-leg path | Yes | **Done** (2026-10-29, `scripts/demo_e2e.py`): entry, exchange stop, restart with no duplicates / no false recovery, exit with stop cancelled and risk released | Blocked: final review, deploy |
| `trend_breakout` | Running | Shared single-leg path | Yes | **Done** (2026-10-29, `scripts/demo_e2e.py`): entry, exchange stop, restart with no duplicates / no false recovery, exit with stop cancelled and risk released | Blocked: final review, deploy |
| `listing_short` | Running | Shared single-leg path | Yes | **Done** (2026-10-29, `scripts/demo_e2e.py`): entry, exchange stop, restart with no duplicates / no false recovery, exit with stop cancelled and risk released | Blocked: final review, deploy |
| `momentum_ls` | Running | `MultiLegExecutionEngine` basket with atomic leg-failure rollback | Yes | **Done** (2026-10-29, `scripts/demo_e2e.py`): entry, exchange stop, restart with no duplicates / no false recovery, exit with stop cancelled and risk released, on both legs | Blocked: final review, deploy |
| `ratio_trend` | Running | `MultiLegExecutionEngine` two-leg pairs with compensating exit | Yes | **Done** (2026-10-29, `scripts/demo_e2e.py`): entry, exchange stop, restart with no duplicates / no false recovery, exit with stop cancelled and risk released, on both legs; a leg rejected on purpose was unwound with its stop removed and no risk left | Blocked: final review, deploy |

## Bugs found by the Demo run (fixed in PR #19)

Fake-exchange tests passed for all of these; only the real exchange showed them.

- **Stops could not be cancelled on Binance.** Conditional orders live apart: a plain `cancel_order` answers -2011
  "Unknown order sent", so every exit ended in recovery. `cancel_oco_orders` now cancels through the view the order was
  found in (`{"trigger": True}`).
- **Exits crashed on missing fill data.** Binance Demo's order answer has no average price and no fee; the fills
  (`fetch_my_trades` by `orderId`) have both, often split in parts. `place_order` now completes the order from its fills.
- **A stop survived the unwind of a rejected basket leg** (found by the harness on a fake): a leftover reduceOnly stop
  would later close a new position on that coin. The unwind now cancels it.
- Out-of-band manual close on Binance was detected with the exchange price and the own stop cancelled.

## Shared safety baseline

- Central Risk Manager: transactional SQLite ledger; pre-trade limit check and reservation in one `BEGIN IMMEDIATE`
  transaction; exits release their reservation (two leaks fixed in PR #14).
- Missing, invalid or stale equity fails closed and engages the persisted kill switch.
- **Entry errors (fixed 2026-10-29):** an entry order that raises is written off — reservation rolled back — only when
  the position reads flat, the exchange confirms the order itself didn't fill (Binance "Order does not exist" -2013, or
  cancelled / rejected / expired with nothing filled, looked up by its client id with `origClientOrderId`), and the
  position is still flat on a second reading. Anything else (a fill, an open order, a failed lookup) is recovery: the
  reservation stays, `recovery_required` is recorded and new entries stop. Same standard the close path already applies
  (`_authoritative_close_fill`). Covers `_enter_trend_live` and the shared `_single_leg_live_entry`;
  `backend/tests/test_entry_error_evidence.py` (11 tests; 4 of them fail if the old single-reading behaviour is put back).
- The order lookup by client id (`_fetch_order_by_cid`) now sends `origClientOrderId`; before, ccxt sent our id as
  Binance's `orderId` and the lookup after a timeout could never find the order.
- Close path: never believes a flat exchange without authoritative fill, fee and funding evidence.
- Restart: positions reload without false recovery (PR #15); reconciliation blocks new entries on exchange/local mismatch.
- Real-orders service isolated from the paper bots: user `raqmlive`, root-owned code copy in `/opt/raqm-live`, keys
  readable by that user only, `--expect-env` refuses any other `BINANCE_ENV` (deploy/vps/setup-live.sh).
- The dashboard loop never runs real orders (`/api/bot/start`, the restart resume and `bot_loop` all refuse).
- `ALLOW_LIVE_TRADING` is off on the VPS (checked 2026-10-29); `raqm-trend-demo.service` is installed but disabled.

## Per-user live trading (Phase 2, PR #12)

Built: encrypted per-user key vault, audited consent record, `trend_daily` per-user execution with percent-of-equity
sizing (fail-closed on missing equity), scheduler with per-user failure isolation, non-reentrant lock, restart
reconciliation and kill-switch polling, `/settings/live` UI. **Not wired:** `backend/app/user_live_scheduler.py` is not
started by any service, cron or startup path. It must not be until Phase 1 is complete for the strategies it runs.

## Pre-production review (2026-10-29)

An independent review of `main` at 9088004 (three reviewers: single-leg path, basket engine, safety gates) found
15 defects, all reproduced before fixing. The fake-exchange tests had passed through all of them. Fixed in
PR #21 (order path), PR #22 (baskets, risk ledger) and PR #23 (history paging, fees, coin sharing, deploy script). The
critical one: in live mode the cycle handed six strategies a **keyless** exchange client, so they could not trade at
all. The adapter-level Demo run could not see this, because it called the adapters directly.

## Second pre-production review (2026-10-29, PR #28)

A second independent review of the fixed head found 8 more code defects (fixed in PR #28) and 4 server-security
problems (fixed in PR #26 and #27): entry-failure recovery now requires exchange evidence and a second read before
releasing a reservation (mirroring the close path), and the `backend/app` files the real-orders bot needs were
missing on the server.

## Third pre-production review (2026-10-29, PR #29)

A third independent review of the PR #28 head found 7 more problems (3 high, 4 medium) plus 2 small ones, all
reproduced with a failing test before fixing, all re-verified by a separate reviewer who reverted each of the 4
highest-stakes fixes one at a time and confirmed the matching test fails without it:
- `_protect_pending` left a stale emergency stop live on the exchange after the position it protected went flat
  (dropped its own bookkeeping without cancelling the order), and acted on a single flat reading instead of the
  2-reading rule the sibling reconciliation loop already uses. Both fixed together.
- The bot and the API could not reliably read/write each other's shared files: `_write_json_atomic` never set
  group-read/write bits (tempfile default), and `raqm`/`raqmlive` were never added to the `raqmapi` group despite
  the shared folders already being correctly set up otherwise. Both fixed; applied on the VPS via the updated
  `setup-paper-ipc.sh`/`setup-live.sh` (`usermod -aG`).
- The auto-update freeze (stops GitHub-triggered updates once a real-money bot exists) scanned a whole service file
  for `--expect-env demo`, so a leftover comment in a copied unit file could hide a genuine real-money bot from it.
  Scoped to the `ExecStart=` line only.
- A crash-retry basket could reuse a stale order-number token minted before the pending-execution cleanup ran.
- `--manual` deployed whatever was on `main`'s tip at that moment, not the commit actually reviewed. Now requires
  `raqm-api-update --manual <40-hex-sha>`, checked reachable on `main`.
- `setup-live.sh`'s key extraction could silently produce an empty file and install it over real, existing keys on
  a re-run. Now aborts before overwriting an existing key file with an empty/incomplete extraction.
- `_protect_pending` treated an inconclusive exchange read the same as "confirmed absent," risking a duplicate stop.

Demo run after the fixes (`scripts/demo_e2e.py`, 18 scenarios, all passed, nothing left open):
- the 8 adapter scenarios again;
- `loop:` vol_breakout / rsi2_pullback / trend_breakout through their own `run_once_*` on the exchange that
  `strategy_exchange()` hands them: entry from a signal, size = margin × leverage once, stop on the exchange, no
  duplicate on the next cycle, exit on the next day's signal, flat, stop gone, risk released;
- `cli:` every strategy's real command line (`bot.py --live --expect-env demo --once`) with a tripped kill switch:
  keys, equity and reconciliation on the Demo account, nothing traded. This stops at the kill switch, so it does not
  exercise the basket strategies' signal code.

Open items from the review:
- ~~while an entry block is set, the portfolio `run_once_*` return early and skip their signal exits too~~ — fixed
  (PR #25): a block stops entries only; a position that is itself in recovery is left to a person;
- ~~the equity freshness check is a no-op~~ — fixed: a missing/stale/future equity timestamp is refused (gate) and trips
  the kill switch (equity update). Every live entry and the per-user tick now carry the observation time;
- ~~live activation readiness is self-declared and the risk allocation is not enforced as a cap~~ — fixed: readiness
  is derived server-side from `readiness_evidence.json` (verified provenance) and the server live switch; allocation is
  split server-side and enforced by the risk gate as each strategy's open-risk cap (a share of the account's aggregate
  risk budget). The legacy generic entry path also checks the activation gate now.

## Deployment (2026-10-29)

`da39663` (PR #29, third review) runs on the VPS:
- the 7 paper bots;
- the API (`RAQM_RISK_DIR=/opt/raqm-risk`, shared with the live bot);
- the real-orders copy in `/opt/raqm-live`, installed by `setup-live.sh da39663…` from a root-owned clone.

`raqm` and `raqmlive` are now both members of the `raqmapi` group (`usermod -aG`, applied by the updated setup
scripts), closing the cross-process file-access gap the third review found.

`raqm-trend-demo.service` is installed but disabled, and `ALLOW_LIVE_TRADING` is off.

## Required sequence before any Live GO

1. ~~Shared execution interface for the nine strategies~~ — done: shared single-leg entry/exit and the multi-leg engine.
2. ~~Live adapters for the single-leg strategies~~ — done (PR #14).
3. ~~Compensating-exit / restart / reconciliation adapters for `momentum_ls`, `ratio_trend`, `listing_short`~~ — done in
   code and fake-exchange tests; still needs step 4 on a real exchange.
4. ~~Demo end-to-end validation for every adapter~~ — done for all seven (`ict` and `wave_flats` dropped).
   Each run should cover: entry, protective order on the exchange, signal exit, a forced restart mid-position, an
   out-of-band manual close, and for the multi-leg strategies a leg that fails on purpose.
5. Fail-closed administrator / strategy / account activation workflow and audit trail — partial: per-user consent and
   audit exist (PR #12); the scheduler that would act on them is not wired.
6. Fresh independent review of the exact final head — first pass done (9088004, fixed in #21–#23); a second pass on
   the fixed head is next.

Then: deploy the reviewed head to the VPS paper bots, watch it, and only after that consider real money, one strategy
at a time, small size.

No step authorizes live trading by itself.
