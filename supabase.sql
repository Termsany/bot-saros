-- Run this in Supabase SQL Editor
create table if not exists profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text,
  tier text default 'free' check (tier in ('free','starter','pro','elite')),
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
-- RLS: user can only see own rows
create policy "own profile" on profiles for all using (auth.uid()=id);
create policy "own trades" on trades for all using (auth.uid()=user_id);
create policy "own backtests" on backtest_runs for all using (auth.uid()=user_id);
-- Trigger: create profile on signup
create or replace function handle_new_user() returns trigger as $$
begin insert into public.profiles (id,email) values (new.id, new.email); return new; end; $$ language plpgsql security definer;
drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users for each row execute function handle_new_user();
