# Development plan — the whole application (from 2026-11-04)

The near-term trading steps are in [roadmap.md](roadmap.md) (A–F); this file ([development-plan.md](development-plan.md)) is the whole picture: seven tracks that
run side by side. Each stage says **whether it can be deferred** and what deferring costs.

- 🔒 **Gate** — never skipped: it protects real money or users. It can wait only if what it guards waits too.
- ⏸️ **Deferrable** — useful, can be done later at no risk; the cost of waiting is written next to it.
- ✂️ **Optional** — only if the owner wants it.

Effort: S = one session, M = 2–4 sessions, L = a week or more of sessions.
The rule from the roadmap holds everywhere: the real bot is touched last, Demo first, outside a rebalance.

## Track 1 — Real-money trading (the core)

| # | Stage | Kind | Effort | Notes |
|---|---|---|---|---|
| 1.1 | First real rebalance checked (Mon 2026-11-09) = roadmap A7 | 🔒 | S | everything below waits for it |
| 1.2 | Three real rebalances at $26/leg (to 2026-11-23), costs vs backtest each week | 🔒 | — (time) | the only real sample we will have |
| 1.3 | **Independent review** of the order path by a programmer other than the owner | 🔒 before 1.4 | M (theirs) | none exists yet (roadmap A4); at $26/leg accepted, above it not |
| 1.4 | Size decision: one step up ($26 → $40) or switch off | 🔒 | S | needs 1.2 + 1.3; skipping 1.4 = staying small, which is safe |
| 1.5 | Second strategy on its own sub-account (first Demo strategy within baseline) | ⏸️ | M | waiting costs only opportunity; earliest ~December |
| 1.6 | Portfolio view: all real strategies, one capital, one kill switch report | ⏸️ | M | only matters from 1.5 on |

## Track 2 — Reliability and operations

| # | Stage | Kind | Effort | Cost of waiting |
|---|---|---|---|---|
| 2.1 | ✓ (PR #101) Automatic rebalance check (read only): old legs closed with fills/fees/funding, no stop left, new legs each with a stop, qty = exchange; result to Telegram | ⏸️ but do before Monday | S | the Monday check by hand at 02:00 Cairo |
| 2.2 | ✓ (PR #101, docs/restore.md) Restore test of the backups (real ledger + state into a scratch folder) | 🔒 before 1.4 | S | a server loss today has an untested way back |
| 2.3 | ✓ (PR #101) CI starts `python bot.py` as the server does, on a fake exchange (roadmap B2) | 🔒 before PR #89 | S | an entry-point break would reach the server |
| 2.4 | ✓ (this PR, watchdog) Server health alerts: disk, memory, clock drift (Binance rejects a request outside its recvWindow, 5 s by default), certificate expiry | ⏸️ | S | silent failure modes the watchdog can't see |
| 2.5 | Real costs per rebalance kept by the bot and shown on realbot.da3m.io / dashboard (roadmap B3) — first step done 2026-11-04: `scripts/rebalance_costs.py` sends fees, slippage and the week's funding to Telegram after each Monday check; first reading: fees 0.05 % a fill vs the backtest's 0.04 %. Re-run at real costs (`research/momentum_fee_sensitivity.py`): PF 1.18 → 1.18, PnL −1.5 %; the edge holds up to ~0.7 % a side (fee + slippage) | 🟡 | M | read by hand from Binance each week |
| 2.6 | Monthly key rotation with `set_demo_keys.sh` / a new real key; quarterly dependency updates | ⏸️ ongoing | S each | slow drift, not a sudden risk |
| 2.7 | Second server or a cold standby image | ✂️ | M | worth it only at a larger size |

## Track 3 — Code health

| # | Stage | Kind | Effort | Cost of waiting |
|---|---|---|---|---|
| 3.1 | PR #89: one file per strategy (after 1.1 and 2.3; Demo, then the real bot) | ⏸️ | S | none; easier strategy work after it |
| 3.2 | Split `backend/app/main.py` (74 endpoints, one file) into routers: admin, user, live, keys, llm… — first step done 2026-11-04: the dead admin keys API (`/api/keys/*`, keys_vault, exchange_manager) removed | 🟡 | M | none now; grows harder with every endpoint |
| 3.3 | ✓ (e2e/, CI job `e2e`; the A6 switches need a signed-in admin: not covered yet) Frontend tests: Playwright smoke for dashboard, live page (the A6 switches), backtest, auth | ⏸️ | M | UI regressions are found by the owner (as on 2026-11-03) |
| 3.4 | One shared definition of the strategies for bot, API and site (today: bot.py, lib/strategies.ts, the API's lists) | ⏸️ | M | names and counts drift (see 5.1) |

## Track 4 — Users (Phase 2, [phase2-design.md](phase2-design.md))

| # | Stage | Kind | Effort | Notes |
|---|---|---|---|---|
| 4.1 | 2–3 testers on **their own Demo keys**: allow list, provisioner, per-user ledger and kill switch | ⏸️ | M | the owner gives their user IDs; nothing of theirs touches the owner's bots |
| 4.2 | Key setup in the site: Ed25519 made for the user (Binance's Demo hides HMAC secrets), checked before saving | ⏸️ | M | needed before more than a handful of users |
| 4.3 | Per-user alerts and status page | ⏸️ | S | |
| 4.4 | Open Demo to all paying users | ⏸️ | S | after 4.1 ran clean for two weeks |
| 4.5 | Real money for users | 🔒 not on this plan | — | needs Track 1 results, 1.3, and Track 5's legal review first |

## Track 5 — Business and payments

| # | Stage | Kind | Effort | Notes |
|---|---|---|---|---|
| 5.1 | ✓ (owner 2026-11-04: plans = follow the bots + Backtest) Pricing page matches what exists: it sells "4 bots", the app runs 7 (3 experimental); say what each plan really gets | 🔒 before selling more | S | a paid plan must not promise what isn't there |
| 5.2 | ✓ (/terms, owner 2026-11-04: no refunds, cancel anytime via the Stripe portal) Terms, risk disclosure and refund policy on the site; backtest numbers labelled as past results everywhere | 🔒 before marketing | S | |
| 5.3 | Legal review for the countries sold to: paid trading bots / signals can need a licence | 🔒 before 4.5 or scale | — (lawyer) | the one stage Claude can't do |
| 5.4 | Stripe in live mode checked end to end (checkout, webhook, downgrade, cancel) | ⏸️ until selling | S | |

## Track 6 — Strategies and research

| # | Stage | Kind | Effort | Notes |
|---|---|---|---|---|
| 6.1 | ✓ (2026-11-04, `scripts/demo_weekly.py`, raqm-demo-weekly.timer Sundays 18:00 UTC to Telegram) Weekly Demo check of the 6 strategies against [demo-baseline.md](demo-baseline.md) (roadmap B5) | 🔒 for 1.5 | S/week | a strategy past its sample and far from the baseline is named to switch off (6.2) |
| 6.2 | A strategy far below baseline after its sample: switched off, not re-tuned | 🔒 | S | |
| 6.3 | New strategy ideas: backtest → Demo sample → small size, the same path as momentum_ls | ⏸️ | L each | never straight to real money |
| 6.4 | LLM Lab: keep as research only, or remove | ✂️ | S | nothing it makes reaches a bot without 6.3's path |

## Track 7 — Public site

| # | Stage | Kind | Effort | Notes |
|---|---|---|---|---|
| 7.1 | realbot.da3m.io as the public proof: monthly summary, costs (with 2.5) | ⏸️ | S | |
| 7.2 | Landing page: real results next to backtest, plain risk wording | ⏸️ | S | with 5.2 |
| 7.3 | Arabic/English, SEO | ✂️ | M | |

## Suggested order (owner can move any ⏸️ / ✂️ later)

1. **Now → Mon 2026-11-09:** 2.1, 2.2, 2.3 (all S, none touches the real bot). Then 1.1 on Monday.
2. **2026-11-09 → 11-23:** 1.2 running by itself; 3.1 (PR #89), 5.1, 5.2; start finding the reviewer for 1.3.
3. **~2026-11-24:** 1.4 — only with 1.3 done; otherwise stay at $26.
4. **December:** 4.1 testers on Demo; 1.5 if a Demo strategy has its sample; 2.4, 2.5.
5. **Later, when there is time:** 3.2–3.4, 4.2–4.4, 5.4, 6.3, Track 7.

Skipping any ⏸️ or ✂️ stage leaves the real bot exactly as safe as today. Skipping a 🔒 gate is possible only by not
doing what it guards (no size increase without 1.3, no users' real money without 5.3).
