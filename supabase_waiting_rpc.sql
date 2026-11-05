-- Kenのデンモク: リスナーに「待機中」の曲名・アーティスト・リクエスト者のみ公開
-- 前提: public.requests テーブルがあり、status='accepted' を待機とする。
-- 既存の requests RLS を緩めず、限定された列だけを返す。
create or replace function public.ken_waiting_requests()
returns table (
  id bigint,
  song_title text,
  artist text,
  listener_name text,
  created_at timestamptz
)
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select r.id, r.song_title, r.artist,
         coalesce(nullif(left(btrim(r.listener_name), 40), ''), '匿名') as listener_name,
         r.created_at
  from public.requests as r
  where r.status = 'accepted'
  order by r.created_at asc, r.id asc
  limit 200;
$$;

revoke all on function public.ken_waiting_requests() from public;
grant execute on function public.ken_waiting_requests() to anon, authenticated;
