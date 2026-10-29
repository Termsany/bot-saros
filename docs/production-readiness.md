# Bot Saros production-readiness matrix

Status is **NO-GO**. Paper mode remains the only permitted operating mode for real money.

_Last updated 2026-10-29, against `main` at PR #16 plus the entry-error evidence fix (this document's commit).
Previous version: 2026-10-26 (28a8249), written before PRs #12–#16._

## Where the roadmap stands

The live-trading roadmap runs **Phase 1 — real end-to-end validation on Binance's test environment (Futures Demo
Trading)** and **Phase 2 — per-user live infrastructure**. Phase 2 was built first, as library code only (PR #12).
**Phase 1 is not finished: one strategy of nine has been run end to end against the exchange.**

## Strategy matrix

All nine names are in `LIVE_READY_STRATEGIES` (bot.py) since PR #14, so `--live` accepts them; that only means the
execution code is reachable, not that it is validated.

| Strategy | Paper bot on the VPS | Live execution path | Unit/integration tests (fake exchange) | Exchange end-to-end (Demo) | Status |
|---|---|---|---|---|---|
| `trend_daily` | Running | Hardened dedicated path (`_enter_trend_live`, `close_live_position`, `reconcile_live`) | Yes | **Done** (PR #16): entry + exchange stop, 4 concurrent positions capped by the aggregate risk gate, restart with no duplicates / no false recovery, out-of-band manual close detected with correct PnL. Demo account, no real funds | Blocked: final independent review, deploy of the reviewed code |
| `ict` (default indicator ensemble) | Not deployed | Generic `try_enter` path | Yes (`test_live_ict.py`) | Not run | Blocked: Demo end-to-end |
| `wave_flats` | Not deployed | Shared `_single_leg_live_entry` / `_single_leg_live_exit` | Yes | Not run | Blocked: Demo end-to-end |
| `vol_breakout` | Running | Shared single-leg path | Yes | Not run | Blocked: Demo end-to-end |
| `rsi2_pullback` | Running | Shared single-leg path | Yes | Not run | Blocked: Demo end-to-end |
| `trend_breakout` | Running | Shared single-leg path | Yes | Not run | Blocked: Demo end-to-end |
| `listing_short` | Running | Shared single-leg path | Yes | Not run | Blocked: Demo end-to-end |
| `momentum_ls` | Running | `MultiLegExecutionEngine` basket with atomic leg-failure rollback | Yes | Not run | Blocked: Demo end-to-end (multi-leg failure / restart on a real exchange) |
| `ratio_trend` | Running | `MultiLegExecutionEngine` two-leg pairs with compensating exit | Yes | Not run | Blocked: Demo end-to-end (residual-exposure recovery on a real exchange) |

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

## Deployment gap

The VPS paper bots run `bot.py` from 2026-10-25 (before PRs #12–#16). The live and multi-leg code validated above is
not what runs on the server. Deploying it is part of finishing Phase 1, after review.

## Required sequence before any Live GO

1. ~~Shared execution interface for the nine strategies~~ — done: shared single-leg entry/exit and the multi-leg engine.
2. ~~Live adapters for the single-leg strategies~~ — done (PR #14).
3. ~~Compensating-exit / restart / reconciliation adapters for `momentum_ls`, `ratio_trend`, `listing_short`~~ — done in
   code and fake-exchange tests; still needs step 4 on a real exchange.
4. **Demo end-to-end validation for every adapter — 1 of 9 done (`trend_daily`). This is the rest of Phase 1.**
   Each run should cover: entry, protective order on the exchange, signal exit, a forced restart mid-position, an
   out-of-band manual close, and for the multi-leg strategies a leg that fails on purpose.
5. Fail-closed administrator / strategy / account activation workflow and audit trail — partial: per-user consent and
   audit exist (PR #12); the scheduler that would act on them is not wired.
6. Fresh independent review of the exact final head — not done (each PR had its own review; the combined head has not).

Then: deploy the reviewed head to the VPS paper bots, watch it, and only after that consider real money, one strategy
at a time, small size.

No step authorizes live trading by itself.
