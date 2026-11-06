-- Ken's Denmoku v2: accounts and role separation.
-- Apply to a NEW / audited Supabase project via SQL editor or migrations.
create schema if not exists private;
create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  display_name text not null default 'ユーザー',
  role text not null default 'listener'
    check (role in ('listener','admin','owner')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create table if not exists public.admin_invites (
  id uuid primary key default gen_random_uuid(),
  email text not null,
  invited_by uuid not null references auth.users(id),
  status text not null default 'pending'
    check (status in ('pending','accepted','revoked')),
  expires_at timestamptz not null default now() + interval '7 days',
  created_at timestamptz not null default now()
);
create unique index if not exists admin_invites_pending_email_idx
  on public.admin_invites(lower(email)) where status = 'pending';

create or replace function public.handle_new_user()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  insert into public.profiles(id,display_name,role) values (
    new.id,
    left(coalesce(nullif(btrim(new.raw_user_meta_data ->> 'display_name'),''),'ユーザー'),40),
    'listener'
  ) on conflict(id) do nothing;
  return new;
end;
$$;
drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users
  for each row execute function public.handle_new_user();

create or replace function private.current_role()
returns text language sql stable security definer set search_path = '' as $$
  select role from public.profiles where id = (select auth.uid())
$$;
revoke all on function private.current_role() from public, anon, authenticated;
grant usage on schema private to authenticated;
grant execute on function private.current_role() to authenticated;

alter table public.profiles enable row level security;
alter table public.admin_invites enable row level security;
revoke all on public.profiles from anon,authenticated;
revoke all on public.admin_invites from anon,authenticated;
grant select on public.profiles to authenticated;
grant update(display_name,updated_at) on public.profiles to authenticated;
drop policy if exists "Read own profile" on public.profiles;
create policy "Read own profile" on public.profiles
  for select to authenticated using (id = (select auth.uid()));
drop policy if exists "Owner reads all profiles" on public.profiles;
create policy "Owner reads all profiles" on public.profiles
  for select to authenticated using ((select private.current_role()) = 'owner');
drop policy if exists "Update own display name" on public.profiles;
create policy "Update own display name" on public.profiles
  for update to authenticated
  using (id = (select auth.uid()))
  with check (id = (select auth.uid()) and role = (select private.current_role()));
create index if not exists profiles_role_idx on public.profiles(role);

-- IMPORTANT: The FIRST owner must be promoted by an authorized operator in SQL Editor,
-- not from the browser. Replace the email below only after that user has registered:
-- update public.profiles set role='owner'
-- where id=(select id from auth.users where email='OWNER_EMAIL_HERE');
