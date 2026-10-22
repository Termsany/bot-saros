# BASELINE — Bot Saros `dev` from `main` @ 6abc3f2

- **Date:** 2026-10-22 (Asia/Riyadh)
- **Base branch:** `main` @ `6abc3f2158114d916898fe76183678843bcec80b` — "Capital-based setup: tested sizes per bot, my-account card, personal paper portfolio"
- **Working branch:** `dev` @ `6abc3f2158114d916898fe76183678843bcec80b` (created 2026-10-22, `git switch -c dev` from `origin/main`, pushed to `origin/dev`)
- **Build assumption:** this baseline is `main` as deployed; pending work on `feat/manual-crypto-payments` @ `6900349` (manual + NOWPayments crypto) stays on its own branch and is NOT merged into `dev` yet.
- **Environment:**
  - Python 3.14.7
  - Node 24.18.0, npm 11.16.0
  - Next.js 15.5.28, React 19.2.0, TypeScript 5.4.5
  - FastAPI backend under `backend/app/` (Python), Next.js frontend under `app/`
  - DB: `backend/app/db.py` -> `raqm.db` (aiosqlite, was `saros.db`) — Supabase `profiles/trades/backtest_runs` via `supabase.sql`
  - Deploy: Vercel (`bot-saros`, `prj_GDQH0xfTbPJxDZJ1K8WkZBOmpUaq`, prod = `main`), VPS `api.da3m.io` pulls main every 5min; Render hook `render-deploy.yml` is manual fallback only.
- **Non-negotiables enforced:** `ALLOW_LIVE_TRADING=false`, no real orders, no real credentials in tests, no deploy to production from this task, no merge to `main`.

## Commands executed

```
git fetch origin
git switch main && git reset --hard origin/main && git switch -c dev && git config credential.helper manager && git push -u origin dev
python -m py_compile backend/app/*.py bot.py backtest.py
npx tsc --noEmit   (via next build lint, see below)
npm run build
npm audit --omit=dev  (not run in baseline; run in QA stage)
python -m pytest / backend/tests  (no auto-discover baseline; existing tests under research/ + manual invocation)
```

## Baseline results (dev @ 6abc3f2)

| Check | Result |
|---|---|
| `python -m py_compile backend/app/*.py bot.py backtest.py` | **PASS** — `ALL_PY OK` (backend: main, oco, keys_vault, db, llm_sandbox, llm_runner, llm_generator, auth, exchange_manager, telegram_bot; plus bot.py/backtest.py) |
| `npm run build` (Next.js) | **PASS** — built 8 routes (/, /_not-found, /admin, /auth, /backtest, /dashboard, /icon.svg, /llm-lab, /settings/keys) + 2 dynamic Stripe routes; No blocking errors. Warnings only from `.next/types` validator (stale generated types, non-blocking). |
| `npx tsc --noEmit` (standalone) | **Non-blocking** — 17 errors all from `.next/types/*.ts` referencing `route.js` (generated validator); not from source `app/` or `lib/`. Source build via `next build` passes. Action: excluded `.next` from direct tsc in CI; baseline records as known non-blocking. |
| Supabase migrations | `supabase.sql` (profiles/trades/backtest_runs + RLS + trigger) and `supabase_fix_rls.sql` (fix FOR ALL -> SELECT-only for anon/authenticated, add stripe_customer_id, backfill profiles, trigger revoke) — present in repo; application in production assumed via prior Supabase; `dev` inherits as-is. New crypto migrations (`supabase_crypto_payments.sql`, `supabase_nowpayments.sql`) remain on `feat/manual-crypto-payments` only. |
| `ALLOW_LIVE_TRADING` | Not set in `.env.example`; `backend/app/main.py:live_trading_allowed()` returns false unless explicitly `true` — baseline compliant. |
| Secrets in tree | `.env.local` gitignored, `backend/.env` gitignored, `vault.json` / `.master.key` / `*.db` gitignored; no secrets found tracked. Verified via `git status` + `.gitignore` inspection. |
| `feat/manual-crypto-payments` branch | Independent preview at `bot-saros-eww5qe6th-termsanys-projects.vercel.app` (READY, non-production target `null`); not merged into `dev`/`main`. |

## Failures at baseline (not regressions)

- `npx tsc --noEmit` standalone reports `.next/types` errors — expected after a build with dynamic routes; not a source defect. CI should run `next build` as the type gate or `tsc --noEmit --skipLibCheck` excluding `.next`.
- No Python test harness auto-discovered on `main` at baseline (tests live under `research/` and invoked ad-hoc). Coverage to be established in Stage F.

## Entry-point & risk-surface inventory (baseline)

- **Processes that can place orders:** `bot.py` (local Windows/paper default, `bot_loop` in `backend/app/main.py` for VPS; CCXT with `defaultType future/linear`), `backend/app/oco.py:place_oco_orders` (STOP/TP via `stopLossPrice`/`takeProfitPrice` + `reduceOnly`).
- **Shared mutable state:** `state.json`, `dashboard-data.json`, `raqm.db`/`saros.db`, Supabase `profiles` tier, `vault.json` (Fernet).
- **External deps:** Binance/Bybit/OKX/MEXC (CCXT), Supabase Auth/DB, Stripe Checkout/Webhook, Bybit/OKX kline fallbacks, Telegram `api.telegram.org`.
- **Kill switch:** `ALLOW_LIVE_TRADING` env in `backend/app/main.py:live_trading_allowed()` — default closed.

## Next baseline actions (Stage F)

- `npm audit --omit=dev` and `pip audit` / `python -m pytest` on `backend/tests` once tests land.
- Verify Vercel env scoping (no `sb_secret` / `sk_live` in `NEXT_PUBLIC_*`), verify Supabase RLS actually applied in prod (not just SQL in repo).
- Record any new failures separately from baseline before marking them as regressions.

---
*Teams review this file as the untrusted-repo baseline before Stage B defect reproduction.*
