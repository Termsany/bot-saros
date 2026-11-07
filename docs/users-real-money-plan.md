# Real money for up to 4 users (plan, 2026-11-05)

**Status: a plan, nothing built yet.** The owner's decisions (2026-11-05): up to **4 people the owner knows, no fee**,
each on their **own Binance account**, **momentum_ls only**, **each user's own capital, margin and accepted risk level** (§3), and a
bot that **starts on its own** once the keys and the consent are in (no per-account approval click).

**2026-11-07 — RSI-2 with the BTC filter next to momentum (owner's decision):** a user picks momentum, RSI-2 + the
BTC filter (research §28: new RSI-2 entries only while BTC closes above its 200-day average), or both, in step 2 of
`/settings/live`. Each runs as its own `raqm-user@<uid>--<strategy>` service on the user's account (RSI-2's gets
`--rsi2-btc-ma 200`), the shared ledger keeps them off each other's coins, and the open-risk budget is split by
trades (10 each). The worst case the user sees and accepts is every stop of the chosen strategies at once (20 for
both); the consent records the strategies it covers, and a plan with a strategy the consent doesn't name asks
again (a consent from before the choice covers momentum only). **Before anyone's RSI-2 can start, the owner's
readiness evidence (`/opt/raqm-api/app/readiness_evidence.json`) must cover `rsi2_pullback`** — without it the
activation record refuses the whole plan and no real bot starts (fail closed).

This changes `docs/development-plan.md` 4.5 ("real money for users", marked 🔒) by the owner's decision. The parts
of that gate that protect the users' money stay, below, as things the code checks — not as reviews to wait for.

## 1. What already exists

- The site: `/settings/live` — keys (encrypted, never sent back), consent, the user's bots, up to 4 users
  (`backend/app/user_bots.py` MAX_USERS) — Demo only (`ENVS_ALLOWED = ("demo",)`, checked again by the provisioner).
- The provisioner (root, narrow) and the `raqm-user@` unit: one sandboxed process per user and strategy, its own
  ledger and kill switch; refused if the key is one of the owner's bots' keys.
- The owner's gift invitation approves an account (4.1). **Not yet run end to end by anyone**; the provisioner timer
  is off until after the first real momentum rebalance (`docs/after-rebalance-1.md`).

## 2. What protects a friend's money (all checked by code, before the first real entry)

1. **Who:** only an account the owner invited (the invitation is the approval; no one else can switch to real money).
2. **The key, on Binance itself:** withdrawals off, restricted to the server's IP, futures on, one-way mode — the
   preflight's checks (`scripts/live_preflight.py`), run automatically for each user; a key that fails is refused.
3. **The account is the bot's alone:** a position the bot did not open blocks its entries (as for the owner).
4. **The user's own ledger:** their kill switch on daily loss and drawdown, equity read fresh before each entry.
5. **The server's switch:** `ALLOW_LIVE_TRADING` and the operator's kill switch stop every user's entries at once.
6. **Watchdog and backup** cover users' bots: a stopped bot, an unprotected position or a kill switch alerts the
   owner's Telegram (development-plan 2.4/2.5 for users).

## 3. Risk: each user chooses, sees the level, and accepts it (owner's decision, 2026-11-05)

Each user enters **their own capital and margin per trade**. The page computes and shows, before anything is saved:
the trade size, one stop's loss ($ and % of the capital), the whole basket at its stops (the worst week), and the
level (low < 1% ≤ medium < 2% ≤ high < 5% ≤ very high, the admin page's scale). The user then **accepts that level on
their own responsibility** — the consent record stores the exact numbers and level they accepted, and a change of
capital or margin asks again. Their own risk gate's limits are set from what they accepted (per trade = one stop,
aggregate = the whole basket), so the gate never refuses the plan they agreed to.

What stays fixed by the code, whatever the choice: the capital counts at most the account's balance on Binance;
a margin below Binance's minimum order skips that coin (BTC needs $25 at x2, ETH $10); x2 and the 40% stop are the
strategy's (not the user's); a basket enters whole or not at all; the user's own kill switch on daily loss and
drawdown, and the operator's for everyone.

### Why the old bounds didn't fit

momentum opens **10 legs at once**, each at a 40% stop (80% of its margin at x2). The users' limits were at most
**1% per trade and 3% for everything open**, so the basket fitted only when one leg's margin ≤ 0.375% of the capital:

| capital | margin per leg | what trades |
|---|---|---|
| $1,000 | $3.75 | only small coins (BTC needs $25, ETH $10 at x2) — not the tested basket |
| $3,000 | $11 | ETH in, BTC out |
| $6,700 | $25 | the whole basket, as on the owner's account |

The options weighed were 1% / 3% (about $6,700 each), the owner's 4.5% / 45%, or 2% / 20%; the owner chose to let
each user decide with the numbers in front of them (above).

## 4. Order of work

1. **Monday 2026-11-09:** the first real momentum rebalance on the owner's account, verified.
2. **4.1 on Demo, first:** one test account (a second email, a second Binance Demo) through the whole path —
   sign-up, keys, consent, momentum, a basket opened with its stops, a rebalance. Nothing real before this passes.
3. **The code for real money (on a branch, tests):**
   - `user_bots.py` / the provisioner: `live` allowed for invited accounts, `momentum_ls` only.
   - The automatic key checks of §2.2 before a live service starts; a failing key keeps the user on "keys refused".
   - `/settings/live`: for real money, the user adds the keys, picks momentum, enters capital and margin, sees the
     level and what a week at the stops can cost, and accepts it (§3); the consent stores those numbers.
   - Watchdog and backup for users' bots (§2.6).
4. **The owner's account first:** momentum at least 3 real rebalances clean (docs/live-small-size-plan.md §5).
5. **One friend, then the others:** the first user alone for a week, then up to 4.

The earliest real-money user is after step 4 (3 real rebalances: about 2026-11-23), if steps 2–3 are done by then.

## 5. What to tell the friends (the owner's words, before their keys)

The bot trades their money on their own Binance account; it can lose; past results are no promise; the key must
not allow withdrawals; they can switch it off from the site at any time, and closing a position on Binance stops
the bot's entries until they check.
