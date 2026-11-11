-- When a song is sung once, honor every waiting request for the same
-- title + artist. Keep individual requesters and history for reporting.
-- The UI groups identical waiting songs into one row with joined nicknames.
-- This AFTER trigger also covers an ON AIR -> OFF AIR auto-completion.
-- No anonymous/public write permissions are added.

create or replace function private.denmoku_complete_matching_waiters()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
 v_id uuid;
begin
 if old.status <> 'singing' or new.status <> 'done' then return new; end if;
 for v_id in
   select r.id
     from public.requests r
    where r.status='waiting' and r.id<>new.id
      and lower(btrim(r.title))=lower(btrim(new.title))
      and lower(btrim(r.artist))=lower(btrim(new.artist))
    order by r.created_at, r.id
    for update
 loop
   update public.requests set status='done',
     completed_at=coalesce(new.completed_at,now()),
     singing_ended_at=coalesce(new.singing_ended_at,now())
     where id=v_id;
   delete from public.queue where request_id=v_id;
   insert into public.singing_history(request_id,title,artist,nickname,completed_at)
     select id,title,artist,nickname,coalesce(completed_at,now())
       from public.requests where id=v_id
     on conflict(request_id) do nothing;
 end loop;
 return new;
end;
$$;

drop trigger if exists denmoku_complete_matching_waiters on public.requests;
create trigger denmoku_complete_matching_waiters
 after update of status on public.requests
 for each row
 when (old.status='singing' and new.status='done')
 execute function private.denmoku_complete_matching_waiters();

revoke all on function private.denmoku_complete_matching_waiters()
 from public,anon,authenticated;
