# Real money for up to 4 users (plan, 2026-11-05)

**Status: a plan, nothing built yet.** The owner's decisions (2026-11-05): up to **4 people the owner knows, no fee**,
each on their **own Binance account**, **momentum_ls only**, risk settings **as the Demo flow has them now**, and a
bot that **starts on its own** once the keys and the consent are in (no per-account approval click).

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

## 3. The open decision: momentum's risk limits for users

momentum opens **10 legs at once**, each at a 40% stop (80% of its margin at x2). The users' limits today are at most
**1% per trade and 3% for everything open**, so the basket fits only when one leg's margin ≤ 0.375% of the capital:

| capital | margin per leg | what trades |
|---|---|---|
| $1,000 | $3.75 | only small coins (BTC needs $25, ETH $10 at x2) — not the tested basket |
| $3,000 | $11 | ETH in, BTC out |
| $6,700 | $25 | the whole basket, as on the owner's account |

Options: (a) keep 1% / 3% and ask each friend for about **$6,700**; (b) the owner's own limits for momentum users
(4.5% / 45%: a basket at its stops loses ≈ 42% of the capital in the worst week — the owner's own size, $500 →
$208); (c) a middle (2% / 20%). **The owner chooses before anything is built.**

## 4. Order of work

1. **Monday 2026-11-09:** the first real momentum rebalance on the owner's account, verified.
2. **4.1 on Demo, first:** one test account (a second email, a second Binance Demo) through the whole path —
   sign-up, keys, consent, momentum, a basket opened with its stops, a rebalance. Nothing real before this passes.
3. **The code for real money (on a branch, tests):**
   - `user_bots.py` / the provisioner: `live` allowed for invited accounts, `momentum_ls` only.
   - The automatic key checks of §2.2 before a live service starts; a failing key keeps the user on "keys refused".
   - `/settings/live`: for real money, the user only adds the keys and picks momentum; the page shows what a week at
     the stops can cost with their capital and the chosen limits (§3).
   - Watchdog and backup for users' bots (§2.6).
4. **The owner's account first:** momentum at least 3 real rebalances clean (docs/live-small-size-plan.md §5).
5. **One friend, then the others:** the first user alone for a week, then up to 4.

The earliest real-money user is after step 4 (3 real rebalances: about 2026-11-23), if steps 2–3 are done by then.

## 5. What to tell the friends (the owner's words, before their keys)

The bot trades their money on their own Binance account; it can lose; past results are no promise; the key must
not allow withdrawals; they can switch it off from the site at any time, and closing a position on Binance stops
the bot's entries until they check.
