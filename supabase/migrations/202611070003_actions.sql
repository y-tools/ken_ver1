-- Ken Denmoku v2: atomic, role-checked mutations and filtered snapshots.
-- SECURITY DEFINER functions must be created by a trusted database owner.
-- Never give direct INSERT/UPDATE/DELETE to public tables.

create or replace function public.denmoku_snapshot()
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  uid uuid := (select auth.uid());
  role_name text;
  admin_access boolean;
  result jsonb;
begin
  if uid is null then raise exception 'Login required' using errcode='28000'; end if;
  select p.role into role_name from public.profiles p where p.id = uid;
  if role_name is null then raise exception 'Profile missing' using errcode='42501'; end if;
  admin_access := role_name in ('admin','owner');
  select pg_catalog.jsonb_build_object(
    'role', role_name,
    'userId', uid,
    'version', (select version from public.sync_version where id=true),
    'name', (select streamer_name from public.stream_status where id=true),
    'streamLive', (select live from public.stream_status where id=true),
    'activeSessionId', (select active_session_id::text from public.stream_status where id=true),
    'songs', coalesce((
      select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'id', s.id, 'title', s.title, 'artist', s.artist, 'status', s.status,
        'year', s.release_year, 'memo', case when admin_access then s.memo else '' end,
        'createdAt', floor(extract(epoch from s.created_at)*1000)::bigint
      ) order by s.title) from public.songs s
    ),'[]'::jsonb),
    'requests', coalesce((
      select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'id',r.id,'userId',r.user_id,'title',r.title,'artist',r.artist,
        'nickname',r.nickname,
        'message',case when admin_access or r.user_id=uid then r.message else '' end,
        'status',r.status,'classifications',r.classifications,
        'createdAt',floor(extract(epoch from r.created_at)*1000)::bigint,
        'waitOrder',q.position,'classifiedAt',floor(extract(epoch from r.classified_at)*1000)::bigint,
        'singingStartedAt',floor(extract(epoch from r.singing_started_at)*1000)::bigint,
        'singingEndedAt',floor(extract(epoch from r.singing_ended_at)*1000)::bigint,
        'completedAt',floor(extract(epoch from r.completed_at)*1000)::bigint,
        'cancelledAt',floor(extract(epoch from r.cancelled_at)*1000)::bigint
      ) order by r.created_at desc)
      from public.requests r left join public.queue q on q.request_id=r.id
      where admin_access or r.user_id=uid or r.status in ('waiting','singing','done')
    ),'[]'::jsonb),
    'sessions', case when admin_access then coalesce((
      select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'id', ss.id, 'startedAt', floor(extract(epoch from ss.started_at)*1000)::bigint,
        'endedAt', floor(extract(epoch from ss.ended_at)*1000)::bigint,
        'events',coalesce((
          select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
            'id',e.id,'type',e.event_type,'at',
            floor(extract(epoch from e.at)*1000)::bigint
          ) || e.details order by e.at)
          from public.session_events e where e.session_id=ss.id
        ),'[]'::jsonb)
      ) order by ss.started_at desc) from
        (select * from public.stream_sessions order by started_at desc limit 100) ss
    ),'[]'::jsonb) else '[]'::jsonb end,
    'chatNotes',case when admin_access then coalesce((
      select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'id',n.id,'kind',n.kind,'text',n.body,
        'at',floor(extract(epoch from n.created_at)*1000)::bigint
      ) order by n.created_at) from (
        select * from public.admin_notes order by created_at desc limit 80
      ) n
    ),'[]'::jsonb) else '[]'::jsonb end
  ) into result;
  return result;
end;
$$;

create or replace function private.denmoku_event(p_event text,p_details jsonb default '{}'::jsonb)
returns void language plpgsql security definer set search_path='' as $$
declare sid uuid;
begin
  select active_session_id into sid from public.stream_status where id=true;
  if sid is not null then
    insert into public.session_events(session_id,event_type,details) values
      (sid,p_event,p_details);
  end if;
end;
$$;

create or replace function public.denmoku_action(p_action text,p_data jsonb default '{}'::jsonb)
returns bigint language plpgsql security definer set search_path='' as $$
declare
  uid uuid := (select auth.uid());
  role_name text;
  is_admin boolean;
  live_now boolean;
  sid uuid;
  rid uuid;
  song_id uuid;
  prior text;
  next_status text;
  title text;
  artist text;
  v_title text;
  v_artist text;
  nick text;
  note text;
  new_position bigint;
  tmp uuid;
  ordered uuid[];
  count_wait bigint;
  result_version bigint;
begin
  if uid is null then raise exception 'Login required' using errcode='28000'; end if;
  select p.role into role_name from public.profiles p where p.id=uid;
  if role_name is null then raise exception 'Profile missing' using errcode='42501'; end if;
  is_admin := role_name in ('admin','owner');
  if p_action not in ('request_add','request_cancel_self') and not is_admin then
    raise exception 'Admin permission required' using errcode='42501';
  end if;
  if p_data is null or pg_catalog.jsonb_typeof(p_data)<>'object' then
    raise exception 'Object payload required' using errcode='22023';
  end if;

  -- Serializes all writes. This prevents concurrent start/stop/reorder
  -- and checks against a consistent stream and queue.
  perform 1 from public.stream_status where id=true for update;
  select live,active_session_id into live_now,sid
    from public.stream_status where id=true;

  if p_action='request_add' then
    if not live_now then raise exception 'Requests are closed' using errcode='23514'; end if;
    title := btrim(p_data->>'title');
    artist := btrim(p_data->>'artist');
    nick := btrim(p_data->>'nickname');
    note := coalesce(p_data->>'message','');
    if title is null or length(title) not between 1 and 120 or
       artist is null or length(artist) not between 1 and 120 or
       nick is null or length(nick) not between 1 and 40 or length(note)>200 then
      raise exception 'Invalid request fields' using errcode='22023';
    end if;
    rid := (p_data->>'nonce')::uuid;
    insert into public.requests(user_id,client_nonce,title,artist,nickname,message)
      values(uid,rid,title,artist,nick,note)
      on conflict(user_id,client_nonce) do nothing returning id into tmp;
    if tmp is null then
      select version into result_version from public.sync_version where id=true;
      return result_version;
    end if;
    perform private.denmoku_event('request',pg_catalog.jsonb_build_object(
      'requestId',tmp,'title',title,'artist',artist,'nickname',nick));
  elsif p_action='request_cancel_self' or p_action='request_cancel' then
    rid := (p_data->>'id')::uuid;
    select status into prior from public.requests
      where id=rid and (is_admin or user_id=uid) for update;
    if prior not in ('new','waiting') and not (is_admin and prior='singing') then
      raise exception 'Request cannot be cancelled' using errcode='23514';
    end if;
    update public.requests set status='cancelled',cancelled_at=now(),
      singing_ended_at=case when prior='singing' then now() else singing_ended_at end
      where id=rid;
    delete from public.queue where request_id=rid;
    perform private.denmoku_event('request_cancelled',pg_catalog.jsonb_build_object('requestId',rid));
  elsif p_action='stream_start' then
    if live_now then raise exception 'Already live' using errcode='23514'; end if;
    insert into public.stream_sessions default values returning id into sid;
    update public.stream_status set live=true,active_session_id=sid,
      updated_by=uid,updated_at=now() where id=true;
  elsif p_action='stream_end' then
    if not live_now then raise exception 'Already offline' using errcode='23514'; end if;
    for rid in select id from public.requests where status='singing' loop
      perform private.denmoku_event('singing_end',pg_catalog.jsonb_build_object('requestId',rid,'reason','stream_end'));
      update public.requests set status='done',completed_at=now(),singing_ended_at=now() where id=rid;
      delete from public.queue where request_id=rid;
      insert into public.singing_history(request_id,title,artist,nickname,completed_at)
        select id,title,artist,nickname,now() from public.requests where id=rid
        on conflict(request_id) do nothing;
    end loop;
    update public.stream_sessions set ended_at=now() where id=sid;
    update public.stream_status set live=false,active_session_id=null,
      updated_by=uid,updated_at=now() where id=true;
  elsif p_action='request_classify' then
    rid := (p_data->>'id')::uuid;
    select status,title,artist into prior,title,artist
      from public.requests where id=rid for update;
    if prior is distinct from 'new' then raise exception 'Not a new request' using errcode='23514'; end if;
    if (p_data->>'waiting')::boolean and (p_data->>'practice')::boolean or
       (p_data->>'practice')::boolean and (p_data->>'ready')::boolean then
      raise exception 'Conflicting classifications' using errcode='22023';
    end if;
    if not (coalesce((p_data->>'waiting')::boolean,false) or
            coalesce((p_data->>'practice')::boolean,false) or
            coalesce((p_data->>'ready')::boolean,false)) then
      raise exception 'Choose a classification' using errcode='22023';
    end if;
    if coalesce((p_data->>'ready')::boolean,false) or coalesce((p_data->>'practice')::boolean,false) then
      insert into public.songs(title,artist,status) values
        (title,artist,case when (p_data->>'ready')::boolean then 'ready' else 'practice' end)
        on conflict ((lower(btrim(title))),(lower(btrim(artist))))
        do update set status=excluded.status,updated_at=now();
      perform private.denmoku_event(
        case when (p_data->>'ready')::boolean then 'ready_added' else 'practice_added' end,
        pg_catalog.jsonb_build_object('title',title,'artist',artist,'source','request')
      );
    end if;
    next_status := case
      when coalesce((p_data->>'waiting')::boolean,false) then 'waiting'
      when coalesce((p_data->>'practice')::boolean,false) then 'practice'
      else 'classified' end;
    update public.requests set status=next_status,classified_at=now(),
      classifications=to_jsonb(array_remove(array[
        case when coalesce((p_data->>'waiting')::boolean,false) then 'waiting' end,
        case when coalesce((p_data->>'practice')::boolean,false) then 'practice' end,
        case when coalesce((p_data->>'ready')::boolean,false) then 'ready' end
      ]::text[],null)) where id=rid;
    if next_status='waiting' then
      select coalesce(max(position),0)+1 into new_position from public.queue;
      insert into public.queue(request_id,position,status) values(rid,new_position,'waiting');
    end if;
    perform private.denmoku_event('classified',pg_catalog.jsonb_build_object(
      'requestId',rid,'title',title,'artist',artist,'categories',p_data));
  elsif p_action='request_status' then
    rid := (p_data->>'id')::uuid;
    next_status := p_data->>'status';
    if next_status not in ('new','waiting','singing','practice','done') then
      raise exception 'Invalid request status' using errcode='22023';
    end if;
    select status,title,artist,nickname into prior,title,artist,nick
      from public.requests where id=rid for update;
    if prior is null then raise exception 'Request missing' using errcode='22023'; end if;
    if next_status='singing' then
      if not live_now or prior<>'waiting' then raise exception 'Cannot start singing' using errcode='23514'; end if;
      if exists(select 1 from public.requests where status='singing' and id<>rid) then
        raise exception 'Another song is singing' using errcode='23514';
      end if;
      update public.queue set status='singing' where request_id=rid;
      update public.requests set singing_started_at=now() where id=rid;
      perform private.denmoku_event('singing_start',pg_catalog.jsonb_build_object(
        'requestId',rid,'title',title,'artist',artist,'nickname',nick));
    else
      if prior='singing' then
        perform private.denmoku_event('singing_end',pg_catalog.jsonb_build_object(
          'requestId',rid,'title',title,'artist',artist));
        update public.requests set singing_ended_at=now() where id=rid;
      end if;
      if next_status='waiting' then
        if prior not in ('new','waiting','singing') then
          raise exception 'Cannot return to waiting' using errcode='23514'; end if;
        select coalesce(max(position),0)+1 into new_position from public.queue;
        insert into public.queue(request_id,position,status)
          values(rid,new_position,'waiting')
          on conflict(request_id) do update set position=excluded.position,status='waiting';
      else
        delete from public.queue where request_id=rid;
      end if;
      if next_status='done' then
        if prior<>'singing' then raise exception 'Must be singing first' using errcode='23514'; end if;
        update public.requests set completed_at=now() where id=rid;
        insert into public.singing_history(request_id,title,artist,nickname,completed_at)
          values(rid,title,artist,nick,now()) on conflict(request_id) do nothing;
      end if;
      if next_status='practice' then
        insert into public.songs(title,artist,status) values(title,artist,'practice')
          on conflict ((lower(btrim(title))),(lower(btrim(artist))))
          do update set status='practice',updated_at=now();
      end if;
    end if;
    update public.requests set status=next_status where id=rid;
    perform private.denmoku_event('status_change',pg_catalog.jsonb_build_object(
      'requestId',rid,'title',title,'artist',artist,'status',next_status));
  elsif p_action='request_reorder' then
    select coalesce(array_agg(value::uuid order by ord),array[]::uuid[]) into ordered
      from pg_catalog.jsonb_array_elements_text(p_data->'ids') with ordinality as a(value,ord);
    select count(*) into count_wait from public.queue where status='waiting';
    if array_length(ordered,1) is distinct from count_wait or
       (select count(distinct v) from unnest(ordered) v) is distinct from count_wait or
       exists(select 1 from unnest(ordered) v where not exists
         (select 1 from public.queue q where q.request_id=v and q.status='waiting')) then
      raise exception 'Queue changed, reload and retry' using errcode='40001';
    end if;
    update public.queue q set position=x.ord,updated_at=now()
      from unnest(ordered) with ordinality x(v,ord) where q.request_id=x.v;
  elsif p_action='request_delete' then
    rid := (p_data->>'id')::uuid;
    delete from public.requests where id=rid;
  elsif p_action='song_upsert' then
    title := btrim(p_data->>'title');
    artist := btrim(p_data->>'artist');
    next_status := p_data->>'status';
    note := coalesce(p_data->>'memo','');
    if title is null or length(title) not between 1 and 120 or
       artist is null or length(artist) not between 1 and 120 or
       next_status not in ('ready','practice') or length(note)>2000 or
       length(coalesce(p_data->>'year',''))>4 then
      raise exception 'Invalid song fields' using errcode='22023';
    end if;
    if nullif(p_data->>'id','') is not null then
      song_id := (p_data->>'id')::uuid;
      v_title := title; v_artist := artist;
      update public.songs set title=v_title,artist=v_artist,status=next_status,
        release_year=nullif(p_data->>'year',''),memo=note,updated_at=now()
        where id=song_id;
      if not found then raise exception 'Song not found' using errcode='22023'; end if;
    else
      insert into public.songs(title,artist,status,release_year,memo)
        values(title,artist,next_status,nullif(p_data->>'year',''),note)
        on conflict ((lower(btrim(title))),(lower(btrim(artist))))
        do update set status=excluded.status,release_year=excluded.release_year,
          memo=excluded.memo,updated_at=now();
    end if;
    perform private.denmoku_event(
      case when next_status='ready' then 'ready_added' else 'practice_added' end,
      pg_catalog.jsonb_build_object('title',title,'artist',artist,'source','manual'));
  elsif p_action='song_import' then
    if pg_catalog.jsonb_typeof(p_data->'items')<>'array' or
      pg_catalog.jsonb_array_length(p_data->'items')>500 then
      raise exception 'Import must contain at most 500 songs' using errcode='22023';
    end if;
    insert into public.songs(title,artist,status,release_year,memo)
    select btrim(x->>'title'),btrim(x->>'artist'),
      case when x->>'status'='practice' then 'practice' else 'ready' end,
      nullif(x->>'year',''),''
      from pg_catalog.jsonb_array_elements(p_data->'items') x
      where length(btrim(x->>'title')) between 1 and 120
        and length(btrim(x->>'artist')) between 1 and 120
        and length(coalesce(x->>'year',''))<=4
      on conflict ((lower(btrim(title))),(lower(btrim(artist)))) do nothing;
  elsif p_action='note_add' then
    note := btrim(p_data->>'text');
    if note is null or length(note) not between 1 and 1500 then
      raise exception 'Invalid note' using errcode='22023';
    end if;
    insert into public.admin_notes(kind,body,created_by) values
      (case when p_data->>'kind'='research' then 'research' else 'note' end,note,uid);
  elsif p_action='name_update' then
    note := btrim(p_data->>'name');
    if note is null or length(note) not between 1 and 30 then
      raise exception 'Invalid streamer name' using errcode='22023';
    end if;
    update public.stream_status set streamer_name=note,updated_by=uid,updated_at=now() where id=true;
  else
    raise exception 'Unknown action' using errcode='22023';
  end if;

  insert into public.admin_logs(actor_id,action,subject_id,summary)
    values(uid,p_action,case when p_action='request_add' then tmp else rid end,
      case when p_action='request_add' then '{}'::jsonb
        else (p_data - 'message' - 'memo' - 'text') end);
  update public.sync_version set version=version+1,updated_at=now() where id=true
    returning version into result_version;
  return result_version;
end;
$$;

revoke all on function public.denmoku_snapshot() from public,anon;
revoke all on function public.denmoku_action(text,jsonb) from public,anon;
grant execute on function public.denmoku_snapshot() to authenticated;
grant execute on function public.denmoku_action(text,jsonb) to authenticated;
revoke all on function private.denmoku_event(text,jsonb) from public,anon,authenticated;
