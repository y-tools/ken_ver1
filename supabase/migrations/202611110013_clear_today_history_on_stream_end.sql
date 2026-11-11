-- Kenのデンモク Ver.2: 「本日の歌唱履歴」は現在の配信だけを表示する。
-- 配信終了により active_session_id が NULL になると両スナップショットの
-- activeSessionStartedAt も NULL となり、再読込なしでリスナー履歴が空になる。
-- 同じ日に次の配信を始めても過去配信の完了曲は再表示しない。
-- リクエスト原本、singing_history、session_events、配信レポートは保持する。
-- No new table grants or anonymous write permissions.

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
    'activeSessionStartedAt', (select floor(extract(epoch from ss.started_at)*1000)::bigint
      from public.stream_status st join public.stream_sessions ss
        on ss.id=st.active_session_id where st.id=true),
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
    'karaoke',coalesce((
      select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'title',k.title,'artist',k.artist,'dam',k.dam,'joy',k.joy,'notes',k.notes
      )) from public.karaoke_records k
    ),'[]'::jsonb),
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

create or replace function public.denmoku_public_snapshot()
returns jsonb language plpgsql stable security definer set search_path='' as $$
begin
 return pg_catalog.jsonb_build_object(
 'role','guest',
 'version',(select version from public.sync_version where id=true),
 'name',(select streamer_name from public.stream_status where id=true),
 'streamLive',(select live from public.stream_status where id=true),
 'activeSessionId',null,
    'activeSessionStartedAt', (select floor(extract(epoch from ss.started_at)*1000)::bigint
      from public.stream_status st join public.stream_sessions ss
        on ss.id=st.active_session_id where st.id=true),
 'songs',coalesce((select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
   'id',s.id,'title',s.title,'artist',s.artist,'status',s.status,'year',s.release_year,
   'memo','','createdAt',floor(extract(epoch from s.created_at)*1000)::bigint) order by s.title)
   from public.songs s),'[]'::jsonb),
 'requests',coalesce((select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
   'id',r.id,'title',r.title,'artist',r.artist,'nickname',r.nickname,
   'message','','status',r.status,'classifications',r.classifications,
   'createdAt',floor(extract(epoch from r.created_at)*1000)::bigint,
   'waitOrder',q.position,'classifiedAt',floor(extract(epoch from r.classified_at)*1000)::bigint,
   'singingStartedAt',floor(extract(epoch from r.singing_started_at)*1000)::bigint,
   'singingEndedAt',floor(extract(epoch from r.singing_ended_at)*1000)::bigint,
   'completedAt',floor(extract(epoch from r.completed_at)*1000)::bigint)
   order by r.created_at desc)
   from public.requests r left join public.queue q on q.request_id=r.id
   where r.status in ('waiting','singing','done')),'[]'::jsonb),
 'sessions','[]'::jsonb,
 'karaoke',coalesce((select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
   'title',k.title,'artist',k.artist,'dam',k.dam,'joy',k.joy,'notes',''))
   from public.karaoke_records k),'[]'::jsonb),
 'chatNotes','[]'::jsonb);
end; $$;

-- SECURITY DEFINER snapshots retain their original allowlisted grants.
revoke all on function public.denmoku_snapshot() from public,anon;
revoke all on function public.denmoku_public_snapshot() from public,anon,authenticated;
grant execute on function public.denmoku_snapshot() to authenticated;
grant execute on function public.denmoku_public_snapshot() to anon,authenticated;
