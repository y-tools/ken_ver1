-- SECURITY FIX: PostgREST's service-role API key is validated by gateway grants.
-- The previous claim-value check does not exist in all service-key formats.
-- Only service_role has EXECUTE via explicit ACL; anon/authenticated/PUBLIC are revoked.
create or replace function public.denmoku_guest_request(
  p_fingerprint text,p_nonce uuid,p_title text,p_artist text,
  p_nickname text,p_message text default ''
) returns uuid language plpgsql security definer set search_path='' as $$
declare
  v_title text; v_artist text; v_nick text := pg_catalog.btrim(p_nickname);
  v_note text := pg_catalog.btrim(coalesce(p_message,''));
  v_existing uuid; v_id uuid;
  v_window_start timestamptz; v_day_start timestamptz;
  v_window_count int; v_day_count int; v_last timestamptz;
  v_global_window timestamptz; v_global_count int;
begin
  -- Server-only: EXECUTE is granted exclusively to service_role.
  -- Never grant this RPC to anon or authenticated clients.
  if p_fingerprint is null or p_fingerprint !~ '^[0-9a-f]{64}$' or p_nonce is null then
    raise exception 'Invalid request credentials' using errcode='22023';
  end if;
  if p_title is null or length(pg_catalog.btrim(p_title)) not between 1 and 120 or
     p_artist is null or length(pg_catalog.btrim(p_artist)) not between 1 and 120 or
     v_nick is null or length(v_nick) not between 1 and 40 or
     length(v_note)>200 or
     v_nick ~ '[<>]' or v_note ~* '(https?://|www\.)'
  then
    raise exception 'Invalid request fields' using errcode='22023';
  end if;

  -- An owner may toggle ON AIR at any time. Hold this row lock through insert,
  -- limits and sync_version to avoid a race between stream stop and request.
  perform 1 from public.stream_status where id=true for update;
  if not (select live from public.stream_status where id=true) then
    raise exception 'Requests are closed (OFF AIR)' using errcode='23514';
  end if;

  -- Retry-safe nonce; no new song request or quota is consumed on retries.
  select id into v_existing from public.requests
  where user_id is null and client_nonce=p_nonce;
  if v_existing is not null then return v_existing; end if;

  select c.title,c.artist into v_title,v_artist
  from private.guest_request_catalog c
  where pg_catalog.lower(pg_catalog.btrim(c.title))=pg_catalog.lower(pg_catalog.btrim(p_title))
    and pg_catalog.lower(pg_catalog.btrim(c.artist))=pg_catalog.lower(pg_catalog.btrim(p_artist))
  limit 1;
  if v_title is null then
    raise exception 'Select a song from the TK catalog' using errcode='22023';
  end if;

  insert into private.guest_request_limits(visitor_hash)
    values(p_fingerprint) on conflict(visitor_hash) do nothing;
  select last_request_at,window_started,window_count,day_started,day_count
    into v_last,v_window_start,v_window_count,v_day_start,v_day_count
  from private.guest_request_limits where visitor_hash=p_fingerprint for update;
  if v_last is not null and v_last>now()-interval '15 seconds' then
    raise exception 'Too many requests: retry later' using errcode='P0001';
  end if;
  if v_window_start<=now()-interval '10 minutes' then
    v_window_start:=now();v_window_count:=0;
  end if;
  if v_day_start<=now()-interval '24 hours' then
    v_day_start:=now();v_day_count:=0;
  end if;
  if v_window_count>=12 or v_day_count>=40 then
    raise exception 'Request quota reached: retry later' using errcode='P0001';
  end if;

  select window_started,window_count into v_global_window,v_global_count
    from private.guest_request_global_limit where id=true for update;
  if v_global_window<=now()-interval '1 minute' then
    v_global_window:=now();v_global_count:=0;
  end if;
  if v_global_count>=90 then
    raise exception 'Too many requests now: retry later' using errcode='P0001';
  end if;
  insert into public.requests(user_id,client_nonce,title,artist,nickname,message,status)
    values(null,p_nonce,v_title,v_artist,v_nick,v_note,'new') returning id into v_id;
  update private.guest_request_limits
  set last_request_at=now(),window_started=v_window_start,
      window_count=v_window_count+1,day_started=v_day_start,day_count=v_day_count+1
  where visitor_hash=p_fingerprint;
  update private.guest_request_global_limit
  set window_started=v_global_window,window_count=v_global_count+1 where id=true;
  perform private.denmoku_event('request',pg_catalog.jsonb_build_object(
    'requestId',v_id,'title',v_title,'artist',v_artist,'nickname',v_nick));
  update public.sync_version set version=version+1,updated_at=now() where id=true;
  return v_id;
end;
$$;

revoke all on function public.denmoku_guest_request(text,uuid,text,text,text,text)
 from public,anon,authenticated;
grant execute on function public.denmoku_guest_request(text,uuid,text,text,text,text)
 to service_role;
