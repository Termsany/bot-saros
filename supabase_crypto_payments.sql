-- Apply before deploying manual crypto payments. Back up first.
alter table public.profiles add column if not exists tier_expires_at timestamptz;
alter table public.profiles add column if not exists stripe_tier text not null default 'free';
alter table public.profiles add column if not exists stripe_event_created bigint not null default 0;
alter table public.profiles add column if not exists manual_tier text;
alter table public.profiles add column if not exists manual_tier_expires_at timestamptz;
update public.profiles set stripe_tier=tier where tier in ('starter','pro','elite') and tier_expires_at is null and stripe_tier='free';
update public.profiles set manual_tier=tier,manual_tier_expires_at=tier_expires_at where tier in ('starter','pro','elite') and tier_expires_at is not null and manual_tier is null;

create table if not exists public.crypto_payment_requests (
 id bigserial primary key,user_id uuid not null references auth.users(id) on delete cascade,email text,
 tier text not null check(tier in('starter','pro','elite')),amount_usdt numeric(12,4) not null check(amount_usdt>0),
 method text not null check(method in('binance_pay','onchain')),network text not null,reference text,note text,
 status text not null default 'pending' check(status in('pending','processing','approved','rejected')),
 admin_note text,reviewed_by uuid references auth.users(id),reviewed_at timestamptz,created_at timestamptz not null default now(),
 unique(method,network,reference));
alter table public.crypto_payment_requests alter column amount_usdt type numeric(12,4);
alter table public.crypto_payment_requests alter column reference drop not null;
alter table public.crypto_payment_requests enable row level security;
drop policy if exists "read own crypto payments" on public.crypto_payment_requests;
create policy "read own crypto payments" on public.crypto_payment_requests for select using(auth.uid()=user_id);
revoke insert,update,delete,truncate on public.crypto_payment_requests from anon,authenticated;
grant select on public.crypto_payment_requests to authenticated;
create index if not exists crypto_payment_user_created_idx on public.crypto_payment_requests(user_id,created_at desc);
create index if not exists crypto_payment_status_created_idx on public.crypto_payment_requests(status,created_at);
create unique index if not exists crypto_payment_one_open_tier_idx on public.crypto_payment_requests(user_id,tier) where status in('pending','processing');
create unique index if not exists crypto_payment_open_amount_idx on public.crypto_payment_requests(network,amount_usdt) where method='onchain' and status in('pending','processing');

create or replace function public.approve_crypto_payment(p_id bigint,p_reviewer uuid,p_note text default '')
returns jsonb language plpgsql security definer set search_path=public as $$
declare p public.crypto_payment_requests%rowtype; pr public.profiles%rowtype; n timestamptz:=now(); exp timestamptz; mt text; effective text; mr int; nr int; sr int;
begin
 select * into p from public.crypto_payment_requests where id=p_id for update;
 if not found then raise exception 'payment_not_found'; end if;
 if p.status='approved' then return jsonb_build_object('ok',true,'id',p.id,'status','approved'); end if;
 if p.status<>'pending' then raise exception 'payment_not_pending'; end if;
 if p.reference is null or length(p.reference)<6 then raise exception 'payment_reference_missing'; end if;
 perform pg_advisory_xact_lock(hashtextextended(p.user_id::text,0));
 insert into public.profiles(id,email,tier) values(p.user_id,p.email,'free') on conflict(id) do nothing;
 select * into pr from public.profiles where id=p.user_id for update;
 mr:=case when pr.manual_tier_expires_at>n then case pr.manual_tier when 'elite' then 3 when 'pro' then 2 when 'starter' then 1 else 0 end else 0 end;
 nr:=case p.tier when 'elite' then 3 when 'pro' then 2 when 'starter' then 1 else 0 end;
 mt:=case when mr>nr then pr.manual_tier else p.tier end;
 exp:=(case when pr.manual_tier_expires_at>n then pr.manual_tier_expires_at else n end)+interval '30 days';
 sr:=case pr.stripe_tier when 'elite' then 3 when 'pro' then 2 when 'starter' then 1 else 0 end;
 effective:=case when sr>=greatest(mr,nr) and sr>0 then pr.stripe_tier else mt end;
 update public.profiles set manual_tier=mt,manual_tier_expires_at=exp,tier=effective,tier_expires_at=case when sr>=greatest(mr,nr) and sr>0 then null else exp end where id=p.user_id;
 update public.crypto_payment_requests set status='approved',admin_note=left(coalesce(p_note,''),500),reviewed_at=n,reviewed_by=p_reviewer where id=p_id;
 return jsonb_build_object('ok',true,'id',p_id,'status','approved','tier',effective,'tier_expires_at',exp);
end; $$;
revoke all on function public.approve_crypto_payment(bigint,uuid,text) from public,anon,authenticated;
grant execute on function public.approve_crypto_payment(bigint,uuid,text) to service_role;

create or replace function public.apply_stripe_entitlement(p_user uuid,p_tier text,p_customer text,p_event_created bigint)
returns jsonb language plpgsql security definer set search_path=public as $$
declare pr public.profiles%rowtype; n timestamptz:=now(); sr int; mr int; effective text; effective_exp timestamptz;
begin
 if p_tier not in('free','starter','pro','elite') then raise exception 'invalid_stripe_tier'; end if;
 perform pg_advisory_xact_lock(hashtextextended(p_user::text,0));
 insert into public.profiles(id,tier) values(p_user,'free') on conflict(id) do nothing;
 select * into pr from public.profiles where id=p_user for update;
 if p_event_created<pr.stripe_event_created then return jsonb_build_object('ok',true,'stale',true); end if;
 sr:=case p_tier when 'elite' then 3 when 'pro' then 2 when 'starter' then 1 else 0 end;
 mr:=case when pr.manual_tier_expires_at>n then case pr.manual_tier when 'elite' then 3 when 'pro' then 2 when 'starter' then 1 else 0 end else 0 end;
 effective:=case when sr>=mr and sr>0 then p_tier when mr>0 then pr.manual_tier else 'free' end;
 effective_exp:=case when sr>=mr and sr>0 then null when mr>0 then pr.manual_tier_expires_at else null end;
 update public.profiles set stripe_tier=p_tier,stripe_event_created=p_event_created,stripe_customer_id=coalesce(p_customer,stripe_customer_id),tier=effective,tier_expires_at=effective_exp where id=p_user;
 return jsonb_build_object('ok',true,'tier',effective,'tier_expires_at',effective_exp);
end; $$;
revoke all on function public.apply_stripe_entitlement(uuid,text,text,bigint) from public,anon,authenticated;
grant execute on function public.apply_stripe_entitlement(uuid,text,text,bigint) to service_role;
