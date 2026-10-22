-- NOWPayments automatic crypto gateway. Apply after supabase_crypto_payments.sql. Safe to re-run.
create table if not exists public.nowpayments_payments (
  id bigserial primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  email text,
  tier text not null check (tier in ('starter','pro','elite')),
  price_amount numeric(12,2) not null,
  price_currency text not null default 'usd',
  pay_currency text,
  order_id text not null unique,
  payment_id text unique,
  invoice_id text unique,
  invoice_url text,
  pay_address text,
  pay_amount numeric(20,10),
  status text not null default 'waiting' check (status in ('waiting','confirming','confirmed','sending','partially_paid','finished','failed','refunded','expired')),
  raw jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
alter table public.nowpayments_payments enable row level security;
drop policy if exists "read own nowpayments" on public.nowpayments_payments;
create policy "read own nowpayments" on public.nowpayments_payments for select using (auth.uid()=user_id);
revoke insert,update,delete,truncate on public.nowpayments_payments from anon,authenticated;
grant select on public.nowpayments_payments to authenticated;
create index if not exists nowpayments_user_created_idx on public.nowpayments_payments(user_id, created_at desc);
create index if not exists nowpayments_order_idx on public.nowpayments_payments(order_id);
create index if not exists nowpayments_payment_idx on public.nowpayments_payments(payment_id);

-- Grant a 30-day tier extension from NOWPayments (same semantics as manual approval, but source is nowpayments).
create or replace function public.grant_nowpayments_tier(p_user uuid, p_tier text)
returns jsonb language plpgsql security definer set search_path=public as $$
declare pr public.profiles%rowtype; n timestamptz:=now(); exp timestamptz; mt text; effective text; mr int; nr int; sr int;
begin
 if p_tier not in ('starter','pro','elite') then raise exception 'invalid_tier'; end if;
 perform pg_advisory_xact_lock(hashtextextended(p_user::text,0));
 insert into public.profiles(id,tier) values(p_user,'free') on conflict(id) do nothing;
 select * into pr from public.profiles where id=p_user for update;
 mr:=case when pr.manual_tier_expires_at>n then case pr.manual_tier when 'elite' then 3 when 'pro' then 2 when 'starter' then 1 else 0 end else 0 end;
 nr:=case p_tier when 'elite' then 3 when 'pro' then 2 when 'starter' then 1 else 0 end;
 mt:=case when mr>nr then pr.manual_tier else p_tier end;
 exp:=(case when pr.manual_tier_expires_at>n then pr.manual_tier_expires_at else n end)+interval '30 days';
 sr:=case pr.stripe_tier when 'elite' then 3 when 'pro' then 2 when 'starter' then 1 else 0 end;
 effective:=case when sr>=greatest(mr,nr) and sr>0 then pr.stripe_tier else mt end;
 update public.profiles set manual_tier=mt, manual_tier_expires_at=exp, tier=effective,
   tier_expires_at=case when sr>=greatest(mr,nr) and sr>0 then null else exp end where id=p_user;
 return jsonb_build_object('ok',true,'tier',effective,'tier_expires_at',exp);
end; $$;
revoke all on function public.grant_nowpayments_tier(uuid,text) from public,anon,authenticated;
grant execute on function public.grant_nowpayments_tier(uuid,text) to service_role;
