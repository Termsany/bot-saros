# Bot Saros production-readiness matrix

Status is **NO-GO**. Paper mode remains the only permitted operating mode.

## Strategy matrix

| Strategy | Paper implementation | Live execution adapter | Independent testnet validation | Status |
|---|---|---|---|---|
| `trend_daily` | Existing | Existing hardened path | Not run | Blocked: testnet validation and independent review |
| default indicator ensemble | Existing | Existing generic path | Not run | Blocked: testnet validation and independent review |
| `wave_flats` | Existing | No live entry path | Not run | Blocked: live adapter |
| `listing_short` | Existing | Explicitly paper-only | Not run | Blocked: multi/single-leg live safety design |
| `momentum_ls` | Existing | Explicitly paper-only | Not run | Blocked: basket live adapter and failure recovery |
| `ratio_trend` | Existing | Explicitly paper-only | Not run | Blocked: pair live adapter, compensating exits, residual exposure recovery |
| `vol_breakout` | Existing | Explicitly paper-only | Not run | Blocked: live adapter |
| `rsi2_pullback` | Existing | Explicitly paper-only | Not run | Blocked: live adapter |
| `trend_breakout` | Existing | Explicitly paper-only | Not run | Blocked: live adapter |

## Shared safety baseline

- Central Risk Manager uses a transactional SQLite ledger.
- Pre-trade limit checking and reservation are one `BEGIN IMMEDIATE` transaction.
- Failed known entries can roll back reservations; ambiguous outcomes persist recovery reservations.
- Missing, invalid, or stale equity fails closed and engages the persisted kill switch during kill-switch evaluation.
- `ALLOW_LIVE_TRADING` remains false by default and no real orders are permitted.

## Required sequence before any Live GO

1. Finish the shared paper execution interface and verify all nine strategy runners use it.
2. Add disabled live adapters for the four single-leg paper strategies, preserving their signal logic.
3. Design and test compensating-exit/restart/reconciliation adapters for `momentum_ls`, `ratio_trend`, and `listing_short`.
4. Run Testnet end-to-end validation independently for every adapter.
5. Add the fail-closed administrator/strategy/account activation workflow and audit trail.
6. Obtain fresh independent review of the exact final head.

No step authorizes live trading by itself.
