# Phase 2 design — other users trading on their own Binance accounts

_Draft for the owner, 2026-11-01. Nothing here is built or switched on. Status stays **NO-GO** for real money._

## Why a new design

The per-user path from PR #12 (`backend/app/user_live_trading.py`, `user_live_scheduler.py`) was reviewed on 2026-11-01
against the owner's bot. It is a second order path written before the Demo run and the three reviews, and most of
their fixes are missing from it: order fills not completed from the exchange's trades (every exit would end in
recovery), one fixed client order id per user and coin (the bug `bot.py` fixed at `_enter_trend_live`), a stop left
on the exchange when its cancellation fails, a hit stop not seen until the next exit signal, fees and funding
assumed instead of read, failed entries never settled, single readings of the position, no detection of a position
opened by hand, the account's position mode changed on every entry, no Binance Demo support at all, and the orders
would run inside the web API's process next to every user's keys.

**Decision: one order path.** A user's strategy runs as the owner's bot does — `bot.py --live` in its own service,
its own OS user, its own keys, ledger and folders — so every fix made for the owner reaches users, and what was
tested on Demo is what users run. The old per-user execution modules are removed once the new path replaces them.

## Constraints

- The Demo measurement (Phase 1b) is not disturbed: no change to the `raqm-demo@` units, their folders or their
  ledger; bot changes are small, behind settings the owner's bots don't set, and deployed with the usual checks.
- Demo first: every user path is built and run end to end on Binance Demo before any real money.
- A strategy is offered to users only after it passed its Phase 1 measurement (`demo_measure.py`: `in_range`) and has
  readiness evidence (`readiness_evidence.json`).
- Real money for other people has legal and responsibility questions that depend on the country and on how the service
  is offered. They are the owner's to settle with a specialist before the first real user; this design does not
  settle them.

## Parts

```
 site (Vercel)  ──►  API (raqmapi)  ──►  /opt/raqm-users/desired/<uid>.json   (what the user asked for; no keys)
 /settings/live       vault (encrypted keys, existing)          │
                      consent record (existing)                 ▼
                                                    provisioner (root, every minute)
                                                                │ creates / updates / stops
                                                                ▼
                         raqm-user@<uid>--<strategy>.service   (bot.py --live, OS user ru-<n>)
                           keys: systemd credential, readable by that service only
                           ledger: /var/lib/raqm-users/<uid>/risk     state: /var/lib/raqm-users/<uid>/state
                           status / close requests: /opt/raqm-users/ipc/<uid>/<strategy>  (read by the API)
```

### 1. The site and the API (no trading)

- `/settings/live`: the user saves Binance keys (the existing encrypted vault), chooses Demo or real, the strategies
  (only those cleared for users), capital and margin (the same capital plan as the owner's), and gives the existing
  audited consent.
- The API checks every gate (below) and writes the **desired state** for that user: environment, strategies, capital
  plan, enabled or not. It never places an order and never builds an exchange client with a user's keys.
- The user's page reads their own bots' status files (positions, history, why no trade, the Demo-vs-baseline table)
  and sends close requests through the same request folder the owner's bots use. A user sees only their own folder.
- Admin page: every user's bots, open risk, problems; a per-user stop.

### 2. The provisioner (root, narrow)

A small root script on a timer, like `raqm-api-update`. Each minute it reads the desired-state files and applies
them; it trusts nothing in them it can check itself (user id format, strategy in the cleared list, environment in
`demo|live`, numbers within the risk bounds), and refuses `live` unless the server's live switch is on and that
strategy has readiness evidence.

For a user switched on:
- creates the OS user `ru-<n>` (one per Raqm user; all of that user's strategy services run as it, so they share one
  ledger and the coin-sharing rule, and no user's process can read another's files);
- decrypts that user's keys from the vault and writes them as a systemd credential
  `/etc/raqm-users/<uid>/binance` (root, 0600) — the service reads it through `LoadCredential=`, so the key file is
  never readable by the user's process directly, the API, or another user;
- writes the user's risk limits and capital plan into their ledger, and their yes/no per strategy into their activation
  record;
- enables `raqm-user@<uid>--<strategy>` for each chosen strategy.

For a user switched off: entries stop at once (activation record); each service keeps running until its positions are
closed by their own rules or by the user, then it is stopped and disabled. Keys deleted on the user's request:
credential wiped, services stopped only once flat.

### 3. The user's service

Template `deploy/vps/raqm-user@.service`, a copy of `raqm-demo@.service` with:
- `User=ru-<n>` (from a per-user drop-in written by the provisioner), `ProtectSystem=strict`, `ProtectHome=true`,
  `PrivateTmp=true`, `NoNewPrivileges=true`, read-write only on that user's own folders;
- `LoadCredential=binance:/etc/raqm-users/<uid>/binance`;
- `Environment=BINANCE_ENV=demo|live` and `--expect-env` the same, as today;
- `RAQM_RISK_DIR`, `RAQM_IPC_DIR`, `--state` all under that user's folders;
- when real money comes: a separate instance name per environment, with `Conflicts=` between the Demo and the real one (one environment exists today).

### 4. Bot changes (small, owner's bots unaffected)

- Keys from `$CREDENTIALS_DIRECTORY/binance` when it is set; else the current environment variables (owner's bots).
- The real-account name check (`BINANCE_LIVE_ACCOUNT`) and the activation record path taken from the service, so a
  user's bot checks that user's record, never the owner's.
- Telegram: a user's bot sends nothing to the owner's chat except problems (through the watchdog); user notifications
  (email or their own Telegram) are a later step.
- Everything else — order path, stops, reconciliation, risk gate, capital plan, slots, kill switch, measurement — is
  the code the owner's bots run today.

## Gates (all must hold for a real-money entry)

1. The server's live switch (`ALLOW_LIVE_TRADING`) on, the operator's kill switch not tripped (it stops every
   user's entries; exits continue).
2. The strategy cleared for users: passed Phase 1 and has readiness evidence.
3. The user's audited consent (existing record and wording) and their keys present.
4. The owner's approval of that user (an allow-list at first), and the user's plan allows live trading.
5. The user's own risk ledger: per-trade and aggregate limits (bounded: leverage ≤ 5, risk per trade ≤ 1%, aggregate
   ≤ 3% — the existing bounds), their own kill switch on drawdown, equity read fresh each entry.

Demo needs 3 (with Demo keys) and 4, not 1 and 2, so users can be tested without real money.

## Alerts, backup, monitoring

- The watchdog also checks every `raqm-user@` unit (down, stale, unprotected position, review, block, kill switch) and
  alerts the owner's Telegram — operations, not the user.
- The daily backup includes `/var/lib/raqm-users` (states and ledgers; never `/etc/raqm-users`).
- The uptime check (`/api/health/bots`) already covers the watchdog.

## Capacity

Measured 2026-11-01: each bot process uses about 140 MB; the VPS has about 3.7 GB free on 2 CPUs, shared with other
applications. One process per user and strategy means about 1 GB for a user running all seven. All users' bots also
share the server's IP for Binance's market-data rate limit.

- Start: a hard cap in the provisioner (for example 4 users × 2 strategies) and measure memory and Binance request
  weight with the first users.
- Before more users: a separate VPS for users' bots — it also keeps users' load and risk apart from the owner's bots
  and the other applications on this server. The design does not change: the provisioner and units move with it.
- Later, only if needed: one process serving several users of the same strategy (a larger change to `bot.py`).

## Steps

| Step | What | Done when |
|---|---|---|
| P2.1 | Bot reads keys from a credential; account and activation from the service | Tests; owner's bots unchanged on deploy |
| P2.2 | Provisioner and `raqm-user@` template, Demo only (refuses `live` in code) | A test user's service on a second Binance Demo account, created and removed by the provisioner |
| P2.3 | API desired state, `/settings/live` rework, the user's status page | A test user switches a strategy on and off from the site |
| P2.4 | End-to-end Demo run for a test user (`scripts/demo_e2e.py` against their service) | Entry, stop on Binance, restart, manual close, exit, switch off while open |
| P2.5 | Watchdog and backup cover user bots | An alert from a stopped user bot; a user's ledger in the backup |
| P2.6 | Remove `user_live_trading.py` / `user_live_scheduler.py` | One order path left |
| P2.7 | Independent review of the whole user path | Findings fixed and re-checked |
| P2.8 | Real money for users | Only after Phase 1's verdict, the review, the legal side settled, and the owner's decision — one user, one strategy, small size |

## Decisions for the owner

1. Which strategies are offered to users (only those that pass Phase 1 — some may pass, some not).
2. Users allowed in at first (an allow-list), and which plan tier includes live trading.
3. When to move users' bots to a separate server.
4. The legal and responsibility side, with a specialist, before any real user.
