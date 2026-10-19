-- Run once in Supabase SQL Editor on an existing project (safe to re-run).
-- Fixes: "own profile" was FOR ALL, so any signed-in user could
--   update profiles set tier = 'elite'  (free upgrade) or edit paper_balance
-- from the browser with the anon key. Users may now only READ their own rows;
-- tier is written only by the Stripe webhook (service key bypasses RLS).

drop policy if exists "own profile" on profiles;
drop policy if exists "own trades" on trades;
drop policy if exists "own backtests" on backtest_runs;
drop policy if exists "read own profile" on profiles;
drop policy if exists "read own trades" on trades;
drop policy if exists "read own backtests" on backtest_runs;
drop policy if exists "insert own backtests" on backtest_runs;

create policy "read own profile" on profiles for select using (auth.uid() = id);
create policy "read own trades" on trades for select using (auth.uid() = user_id);
create policy "read own backtests" on backtest_runs for select using (auth.uid() = user_id);
create policy "insert own backtests" on backtest_runs for insert with check (auth.uid() = user_id);

-- belt and braces: no direct writes to profiles from the client roles
revoke insert, update, delete on profiles from anon, authenticated;

-- Stripe subscription id, so cancellations can downgrade the right user
alter table profiles add column if not exists stripe_customer_id text;
create index if not exists profiles_stripe_customer_idx on profiles(stripe_customer_id);
create index if not exists profiles_email_idx on profiles(email);
