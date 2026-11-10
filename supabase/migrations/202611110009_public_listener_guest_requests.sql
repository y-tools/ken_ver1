-- Ver.2: audience uses public read-only data without signing up.
-- Only verified owner/admin accounts get privileged snapshots and mutation RPCs.
-- A public song request goes through an Edge Function with server-only credentials.
-- Never expose the request rate-limit key or admin chat through this API.

alter table public.requests alter column user_id drop not null;
alter table public.requests add column if not exists anonymous_hash text;
alter table public.requests add constraint requests_author_identity_required
  check (user_id is not null or anonymous_hash is not null);
create unique index if not exists denmoku_anonymous_nonce
  on public.requests(anonymous_hash,client_nonce)
  where anonymous_hash is not null;

-- A public version counter is intentionally the only directly queryable public table.
grant select on public.sync_version to anon;
drop policy if exists "Public can see sync counter" on public.sync_version;
create policy "Public can see sync counter" on public.sync_version
  for select to anon using (id=true);

-- Return strictly allowlisted audience fields; no user IDs, request message,
-- private queue/notes, audit logs, or administrative sessions.
create or replace function public.denmoku_public_snapshot()
returns jsonb language plpgsql stable security definer set search_path='' as $$
begin
  return pg_catalog.jsonb_build_object(
    'role','listener',
    'userId',null,
    'version',(select version from public.sync_version where id=true),
    'name',(select streamer_name from public.stream_status where id=true),
    'streamLive',(select live from public.stream_status where id=true),
    'activeSessionId',null,
    'songs',coalesce((
      select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'id',s.id,'title',s.title,'artist',s.artist,
        'status',s.status,'year',s.release_year,'memo','',
        'createdAt',floor(extract(epoch from s.created_at)*1000)::bigint
      ) order by s.title)
      from public.songs s
    ),'[]'::jsonb),
    'requests',coalesce((
      select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'id',r.id,'title',r.title,'artist',r.artist,
        'nickname',r.nickname,'message','',
        'status',r.status,'classifications','[]'::jsonb,
        'createdAt',floor(extract(epoch from r.created_at)*1000)::bigint,
        'waitOrder',q.position,
        'classifiedAt',floor(extract(epoch from r.classified_at)*1000)::bigint,
        'singingStartedAt',floor(extract(epoch from r.singing_started_at)*1000)::bigint,
        'singingEndedAt',floor(extract(epoch from r.singing_ended_at)*1000)::bigint,
        'completedAt',floor(extract(epoch from r.completed_at)*1000)::bigint,
        'cancelledAt',null
      ) order by r.created_at desc)
      from public.requests r
      left join public.queue q on q.request_id=r.id
      where r.status in ('waiting','singing','done','practice')
    ),'[]'::jsonb),
    'sessions','[]'::jsonb,
    'karaoke',coalesce((
      select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'title',k.title,'artist',k.artist,'dam',k.dam,'joy',k.joy,'notes',''
      )) from public.karaoke_records k
    ),'[]'::jsonb),
    'chatNotes','[]'::jsonb
  );
end;
$$;
revoke all on function public.denmoku_public_snapshot() from public,anon,authenticated;
grant execute on function public.denmoku_public_snapshot() to anon,authenticated;

-- Back-office only: safe aggregate throttle counters never exposed to the Data API.
create table if not exists private.anonymous_request_limits (
  bucket text primary key,
  window_started_at timestamptz not null default now(),
  attempt_count int not null default 0
);
alter table private.anonymous_request_limits enable row level security;
revoke all on private.anonymous_request_limits from public,anon,authenticated;

-- Only callable with the service-role credential from the server-side Edge Function.
create or replace function public.submit_anonymous_request(
 p_title text,p_artist text,p_nickname text,p_message text,p_nonce uuid,p_ip_hash text
) returns jsonb language plpgsql security definer set search_path='' as $$
declare
  title_value text:=btrim(coalesce(p_title,''));
  artist_value text:=btrim(coalesce(p_artist,''));
  nick_value text:=btrim(coalesce(p_nickname,''));
  message_value text:=coalesce(p_message,'');
  cnt_short int;
  cnt_daily int;
  cnt_global int;
  rid uuid;
  ver bigint;
  is_live boolean;
begin
  if length(title_value) not between 1 and 120
     or length(artist_value) not between 1 and 120
     or length(nick_value) not between 1 and 40
     or length(message_value)>200 or p_nonce is null
     or p_ip_hash is null or p_ip_hash !~ '^[a-f0-9]{64}$' then
    return pg_catalog.jsonb_build_object('ok',false,'code','invalid');
  end if;
  -- All changes to requests and stream status are serialized through one row.
  select live into is_live from public.stream_status where id=true for update;
  if is_live is distinct from true then
    return pg_catalog.jsonb_build_object('ok',false,'code','closed');
  end if;
  if exists(select 1 from public.requests
      where anonymous_hash=p_ip_hash and client_nonce=p_nonce) then
    return pg_catalog.jsonb_build_object('ok',true,'duplicate',true);
  end if;
  insert into private.anonymous_request_limits(bucket,attempt_count)
    values('15m:'||p_ip_hash,1)
    on conflict(bucket) do update set
      attempt_count=case
        when private.anonymous_request_limits.window_started_at<now()-interval '15 minutes'
        then 1 else private.anonymous_request_limits.attempt_count+1 end,
      window_started_at=case
        when private.anonymous_request_limits.window_started_at<now()-interval '15 minutes'
        then now() else private.anonymous_request_limits.window_started_at end
    returning attempt_count into cnt_short;
  insert into private.anonymous_request_limits(bucket,attempt_count)
    values('1d:'||p_ip_hash,1)
    on conflict(bucket) do update set
      attempt_count=case
        when private.anonymous_request_limits.window_started_at<now()-interval '1 day'
        then 1 else private.anonymous_request_limits.attempt_count+1 end,
      window_started_at=case
        when private.anonymous_request_limits.window_started_at<now()-interval '1 day'
        then now() else private.anonymous_request_limits.window_started_at end
    returning attempt_count into cnt_daily;
  insert into private.anonymous_request_limits(bucket,attempt_count)
    values('global:1d',1)
    on conflict(bucket) do update set
      attempt_count=case
        when private.anonymous_request_limits.window_started_at<now()-interval '1 day'
        then 1 else private.anonymous_request_limits.attempt_count+1 end,
      window_started_at=case
        when private.anonymous_request_limits.window_started_at<now()-interval '1 day'
        then now() else private.anonymous_request_limits.window_started_at end
    returning attempt_count into cnt_global;
  if cnt_short>8 or cnt_daily>40 or cnt_global>800 then
    return pg_catalog.jsonb_build_object('ok',false,'code','rate_limit');
  end if;
  if (select count(*) from public.requests where status in ('new','waiting'))>=300 then
    return pg_catalog.jsonb_build_object('ok',false,'code','busy');
  end if;
  insert into public.requests(
    user_id,anonymous_hash,client_nonce,title,artist,nickname,message
  ) values(
    null,p_ip_hash,p_nonce,title_value,artist_value,nick_value,message_value
  ) returning id into rid;
  perform private.denmoku_event('request',pg_catalog.jsonb_build_object(
    'requestId',rid,'title',title_value,'artist',artist_value,'nickname',nick_value
  ));
  insert into public.admin_logs(actor_id,action,subject_id,summary)
    values(null,'request_add_public',rid,'{}'::jsonb);
  update public.sync_version set version=version+1,updated_at=now()
    where id=true returning version into ver;
  return pg_catalog.jsonb_build_object('ok',true,'version',ver);
end;
$$;
revoke all on function public.submit_anonymous_request(text,text,text,text,uuid,text)
  from public,anon,authenticated;
grant execute on function public.submit_anonymous_request(text,text,text,text,uuid,text)
  to service_role;

-- Block open public account signups at the database trigger, not only in the UI.
-- Owner account already exists. An admin is created ONLY after owner invitation.
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer set search_path='' as $$
declare
  requested_id text;
begin
  if not exists (
    select 1 from public.admin_invites ai
     where lower(ai.email)=lower(new.email)
       and ai.status='pending' and ai.expires_at>now()
  ) then
    raise exception 'Registration is invitation only' using errcode='42501';
  end if;
  requested_id:=nullif(lower(btrim(new.raw_user_meta_data->>'login_id')),'');
  if requested_id is not null
      and requested_id !~ '^[a-z][a-z0-9._-]{3,23}$' then
    raise exception 'Invalid login ID' using errcode='22023';
  end if;
  insert into public.profiles(id,display_name,role,login_id)
  values(new.id,left(coalesce(nullif(btrim(new.raw_user_meta_data->>'display_name'),''),'ユーザー'),40),
    'listener',requested_id)
  on conflict(id) do nothing;
  return new;
end;
$$;
revoke all on function public.handle_new_user() from public,anon,authenticated;
