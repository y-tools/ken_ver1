-- Public read-only projection. Migrated to Tokyo Supabase as denmoku_v2_public_read_only_snapshot.
-- NOTE: project migration history has been applied before this git file was added.
-- See Supabase dashboard for deployed definition, and do not run twice with divergent SQL.
create or replace function public.denmoku_public_snapshot()
returns jsonb language plpgsql stable security definer set search_path='' as $$
begin
 return pg_catalog.jsonb_build_object(
 'role','guest',
 'version',(select version from public.sync_version where id=true),
 'name',(select streamer_name from public.stream_status where id=true),
 'streamLive',(select live from public.stream_status where id=true),
 'activeSessionId',null,
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
revoke all on function public.denmoku_public_snapshot() from public,anon,authenticated;
grant execute on function public.denmoku_public_snapshot() to anon,authenticated;
grant select on public.sync_version to anon;
drop policy if exists "Anonymous can see sync counter" on public.sync_version;
create policy "Anonymous can see sync counter" on public.sync_version for select to anon using(true);
