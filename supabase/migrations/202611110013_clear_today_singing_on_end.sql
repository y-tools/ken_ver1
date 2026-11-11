-- Clear only the viewer-facing "today's singing history" at stream end.
-- Keep the completed requests themselves and session_events so past reports
-- remain available. The day boundary is Japan Standard Time (Asia/Tokyo).
-- This trigger runs in the same transaction as denmoku_action('stream_end').
create or replace function private.denmoku_clear_today_singing_on_end()
returns trigger
language plpgsql
security definer
set search_path=''
as $$
declare
  v_today_start timestamptz :=
    date_trunc('day', now() at time zone 'Asia/Tokyo') at time zone 'Asia/Tokyo';
begin
  -- The request record/status stays "done" for back-office management,
  -- but its display-only completion time is cleared.
  update public.requests
     set completed_at = null
   where status='done'
     and completed_at >= v_today_start;

  -- This table is the short-lived singing history, not the session report.
  delete from public.singing_history
   where completed_at >= v_today_start;

  return new;
end;
$$;

revoke all on function private.denmoku_clear_today_singing_on_end()
  from public,anon,authenticated;

drop trigger if exists denmoku_clear_today_singing_on_end
  on public.stream_status;
create trigger denmoku_clear_today_singing_on_end
after update of live on public.stream_status
for each row
when (old.live = true and new.live = false)
execute function private.denmoku_clear_today_singing_on_end();
