-- Run this in Supabase SQL Editor
create table if not exists profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text,
  tier text default 'free' check (tier in ('free','starter','pro','elite')),
  paper_balance numeric default 1000,
  paper_pnl numeric default 0,
  stripe_customer_id text,
  tier_expires_at timestamptz,
  created_at timestamptz default now()
);
create table if not exists trades (
  id bigserial primary key,
  user_id uuid references auth.users(id),
  symbol text, side text, entry numeric, exit numeric, qty numeric,
  sl numeric, tp numeric, leverage int, pnl numeric, status text, created_at timestamptz default now()
);
create table if not exists backtest_runs (
  id bigserial primary key, user_id uuid, symbol text, timeframe text, strategies text, stats jsonb, created_at timestamptz default now()
);
alter table profiles enable row level security;
alter table trades enable row level security;
alter table backtest_runs enable row level security;
-- RLS: user can only READ own rows. tier/paper_balance are written by the server (service key) only.
-- (existing projects: run supabase_fix_rls.sql)
create policy "read own profile" on profiles for select using (auth.uid()=id);
create policy "read own trades" on trades for select using (auth.uid()=user_id);
create policy "read own backtests" on backtest_runs for select using (auth.uid()=user_id);
create policy "insert own backtests" on backtest_runs for insert with check (auth.uid()=user_id);
revoke insert, update, delete on profiles from anon, authenticated;
-- Trigger: create profile on signup
create or replace function handle_new_user() returns trigger as $$
begin insert into public.profiles (id,email,paper_balance) values (new.id, new.email, 1000); return new; end; $$ language plpgsql security definer;
drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users for each row execute function handle_new_user();
