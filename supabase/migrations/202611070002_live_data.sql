-- Ken's Denmoku v2: performance-specific data. The 2M-song search catalog
-- remains on GitHub/VPS; public.songs stores ONLY ready/practice selections.
create table if not exists public.songs (
  id uuid primary key default gen_random_uuid(),
  title text not null check (length(btrim(title)) between 1 and 120),
  artist text not null check (length(btrim(artist)) between 1 and 120),
  status text not null check(status in ('ready','practice')),
  release_year text,
  memo text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create unique index if not exists denmoku_song_identity
  on public.songs(lower(btrim(title)),lower(btrim(artist)));

-- Shared source-linked DAM / JOYSOUND verification.
create table if not exists public.karaoke_records (
  id uuid primary key default gen_random_uuid(),
  title text not null check(length(btrim(title)) between 1 and 190),
  artist text not null check(length(btrim(artist)) between 1 and 150),
  dam jsonb not null default '{}'::jsonb,
  joy jsonb not null default '{}'::jsonb,
  notes text not null default '' check(length(notes)<=400),
  changed_by uuid references auth.users(id),
  updated_at timestamptz not null default now()
);
create unique index if not exists denmoku_karaoke_unique
  on public.karaoke_records(lower(btrim(title)),lower(btrim(artist)));
alter table public.karaoke_records enable row level security;
revoke all on public.karaoke_records from anon,authenticated;


create table if not exists public.stream_sessions (
  id uuid primary key default gen_random_uuid(),
  started_at timestamptz not null default now(),
  ended_at timestamptz
);
create table if not exists public.stream_status (
  id boolean primary key default true check (id),
  live boolean not null default false,
  streamer_name text not null default 'Ken',
  active_session_id uuid references public.stream_sessions(id),
  updated_by uuid references auth.users(id),
  updated_at timestamptz not null default now()
);
insert into public.stream_status(id) values(true) on conflict(id) do nothing;

create table if not exists public.requests (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id),
  client_nonce uuid not null,
  title text not null check (length(btrim(title)) between 1 and 120),
  artist text not null check (length(btrim(artist)) between 1 and 120),
  nickname text not null check(length(btrim(nickname)) between 1 and 40),
  message text not null default '' check(length(message) <= 200),
  status text not null default 'new'
    check (status in ('new','waiting','singing','practice','classified','done','cancelled')),
  classifications jsonb not null default '[]'::jsonb,
  classified_at timestamptz,
  singing_started_at timestamptz,
  singing_ended_at timestamptz,
  completed_at timestamptz,
  cancelled_at timestamptz,
  created_at timestamptz not null default now(),
  unique(user_id,client_nonce)
);
create index if not exists denmoku_requests_user_time
  on public.requests(user_id,created_at desc);
create index if not exists denmoku_requests_status_time
  on public.requests(status,created_at desc);

create table if not exists public.queue (
  request_id uuid primary key references public.requests(id) on delete cascade,
  position bigint not null,
  status text not null default 'waiting' check(status in ('waiting','singing')),
  updated_at timestamptz not null default now()
);
create index if not exists denmoku_queue_order on public.queue(position);

create table if not exists public.singing_history (
  request_id uuid primary key references public.requests(id) on delete cascade,
  title text not null,
  artist text not null,
  nickname text not null,
  completed_at timestamptz not null
);
create index if not exists denmoku_history_date on public.singing_history(completed_at desc);

create table if not exists public.session_events (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references public.stream_sessions(id) on delete cascade,
  event_type text not null,
  details jsonb not null default '{}'::jsonb,
  at timestamptz not null default now()
);
create index if not exists denmoku_session_events_time on public.session_events(session_id,at);

create table if not exists public.admin_notes (
  id uuid primary key default gen_random_uuid(),
  kind text not null check(kind in ('note','research')),
  body text not null check(length(body) between 1 and 1500),
  created_by uuid references auth.users(id),
  created_at timestamptz not null default now()
);

create table if not exists public.admin_logs (
  id uuid primary key default gen_random_uuid(),
  actor_id uuid references auth.users(id),
  action text not null,
  subject_id uuid,
  summary jsonb not null default '{}'::jsonb,
  at timestamptz not null default now()
);

-- This is the ONLY table used in Realtime. It carries no private data.
-- A subscribed client fetches its role-filtered snapshot when the version changes.
create table if not exists public.sync_version (
  id boolean primary key default true check(id),
  version bigint not null default 0,
  updated_at timestamptz not null default now()
);
insert into public.sync_version(id) values(true) on conflict(id) do nothing;

-- All writes and private reads go through authenticated, role-checking RPCs.
-- RLS is defense in depth; direct table access is denied unless explicitly granted.
do $$
declare t text;
begin
 for t in select unnest(array[
   'songs','requests','queue','singing_history','stream_status',
   'stream_sessions','session_events','admin_notes','admin_logs','sync_version',
   'karaoke_records'
 ]) loop
   execute format('alter table public.%I enable row level security',t);
   execute format('revoke all on public.%I from anon,authenticated',t);
 end loop;
end $$;
grant select on public.sync_version to authenticated;
drop policy if exists "Authenticated can see sync counter" on public.sync_version;
create policy "Authenticated can see sync counter" on public.sync_version
  for select to authenticated using ((select auth.uid()) is not null);

-- DO NOT drop/recreate the publication: other apps may already use it.
do $$
begin
  if exists(select 1 from pg_publication where pubname='supabase_realtime') then
    begin
      alter publication supabase_realtime add table public.sync_version;
    exception when duplicate_object then null;
    end;
  end if;
end $$;
