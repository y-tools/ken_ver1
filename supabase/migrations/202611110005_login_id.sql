-- Ken's Denmoku v2 / login ID support.
-- Must be applied AFTER 202611070001_auth.sql; run only on a reviewed Supabase project.
-- Login IDs are NOT email addresses, are unique across the project, and do not affect roles.

alter table public.profiles
  add column if not exists login_id text;

-- Existing accounts (including owner/admin invites) can set this later after email login.
-- Stored IDs are always lowercase ASCII to make case-insensitive login deterministic.
alter table public.profiles
  add constraint profiles_login_id_format
  check (login_id is null or login_id ~ '^[a-z][a-z0-9._-]{3,23}$');

create unique index if not exists profiles_login_id_unique
  on public.profiles (login_id)
  where login_id is not null;

-- Update the signup trigger. The client may suggest a login_id but never a role.
-- UNIQUE stops concurrent registrations from reserving the same login ID.
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer set search_path = '' as $$
declare
  requested_id text;
begin
  requested_id := nullif(lower(btrim(new.raw_user_meta_data ->> 'login_id')), '');
  if requested_id is not null
    and requested_id !~ '^[a-z][a-z0-9._-]{3,23}$' then
    raise exception 'Invalid login ID' using errcode='22023';
  end if;
  insert into public.profiles(id,display_name,role,login_id) values (
    new.id,
    left(coalesce(nullif(btrim(new.raw_user_meta_data ->> 'display_name'),''),'ユーザー'),40),
    'listener',requested_id
  ) on conflict(id) do nothing;
  return new;
end;
$$;

-- Every authenticated user can set/change only THEIR OWN login ID, never their role.
-- Browser UPDATE is not granted on profiles.login_id; only this guarded function can write it.
create or replace function public.set_login_id(p_login_id text)
returns text language plpgsql security definer set search_path='' as $$
declare
  uid uuid := (select auth.uid());
  cleaned text := lower(btrim(coalesce(p_login_id,'')));
begin
  if uid is null then
    raise exception 'Authentication required' using errcode='28000';
  end if;
  if cleaned !~ '^[a-z][a-z0-9._-]{3,23}$' then
    raise exception 'Invalid login ID (4-24 ASCII characters, first letter)' using errcode='22023';
  end if;
  update public.profiles
    set login_id=cleaned,updated_at=now()
    where id=uid;
  if not found then
    raise exception 'Profile not found' using errcode='22023';
  end if;
  return cleaned;
exception when unique_violation then
  raise exception 'Login ID unavailable' using errcode='23505';
end;
$$;
revoke all on function public.set_login_id(text) from public, anon;
grant execute on function public.set_login_id(text) to authenticated;

-- This table is NOT queryable by anon/authenticated clients. It is accessible
-- only by the ID-login Edge Function using service_role, and by DB administrators.
create table if not exists public.id_login_rate_limits (
  bucket text primary key,
  window_started_at timestamptz not null default now(),
  attempt_count integer not null default 0
);
alter table public.id_login_rate_limits enable row level security;
revoke all on public.id_login_rate_limits from public, anon, authenticated;
grant select, insert, update, delete on public.id_login_rate_limits to service_role;

-- Atomic fixed-window limiter: max 8 tries per login-ID+IP and max 60 per IP
-- every 15 minutes. Postgres upsert prevents parallel request races.
create or replace function public.reserve_id_login_attempt(
  p_login_id text, p_ip text
)
returns boolean language plpgsql security definer set search_path='' as $$
declare
  pair_hits int;
  ip_hits int;
  ip_key text := left(coalesce(nullif(p_ip,''),'unknown'),128);
begin
  if p_login_id is null or p_login_id !~ '^[a-z][a-z0-9._-]{3,23}$' then
    return false;
  end if;
  insert into public.id_login_rate_limits(bucket,window_started_at,attempt_count)
    values('pair:'||md5(ip_key||'|'||p_login_id),now(),1)
  on conflict (bucket) do update
    set attempt_count=case
      when public.id_login_rate_limits.window_started_at < now()-interval '15 minutes'
      then 1 else public.id_login_rate_limits.attempt_count+1 end,
        window_started_at=case
      when public.id_login_rate_limits.window_started_at < now()-interval '15 minutes'
      then now() else public.id_login_rate_limits.window_started_at end
    returning attempt_count into pair_hits;

  insert into public.id_login_rate_limits(bucket,window_started_at,attempt_count)
    values('ip:'||md5(ip_key),now(),1)
  on conflict (bucket) do update
    set attempt_count=case
      when public.id_login_rate_limits.window_started_at < now()-interval '15 minutes'
      then 1 else public.id_login_rate_limits.attempt_count+1 end,
        window_started_at=case
      when public.id_login_rate_limits.window_started_at < now()-interval '15 minutes'
      then now() else public.id_login_rate_limits.window_started_at end
    returning attempt_count into ip_hits;

  return pair_hits<=8 and ip_hits<=60;
end;
$$;
revoke all on function public.reserve_id_login_attempt(text,text)
  from public, anon, authenticated;
grant execute on function public.reserve_id_login_attempt(text,text)
  to service_role;

-- Periodically remove expired rows after seven days (manual or scheduled):
-- delete from public.id_login_rate_limits
-- where window_started_at < now() - interval '7 days';
