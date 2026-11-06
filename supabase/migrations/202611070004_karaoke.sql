-- Karaoke records table and index are created in 202611070002_live_data.sql
-- so that 202611070003_actions.sql can reference the table safely.
-- Records are served by a role-aware RPC only.
create or replace function private.denmoku_save_karaoke(record jsonb,actor uuid)
returns void language plpgsql security definer set search_path='' as $$
declare
 t text := btrim(record->>'title');
 a text := btrim(record->>'artist');
 d jsonb := coalesce(record->'dam','{}'::jsonb);
 j jsonb := coalesce(record->'joy','{}'::jsonb);
 n text := coalesce(record->>'notes','');
 p jsonb;
 src text;
 status_value text;
 url_value text;
begin
 if t is null or length(t) not between 1 and 190 or
    a is null or length(a) not between 1 and 150 or length(n)>400 then
   raise exception 'Invalid karaoke record' using errcode='22023';
 end if;
 for p,src in select d,'dam' union all select j,'joy' loop
   status_value := coalesce(p->>'status','unknown');
   url_value := coalesce(p->>'url','');
   if status_value not in ('unknown','available','searched') then
     raise exception 'Invalid verification status' using errcode='22023';
   end if;
   if length(coalesce(p->>'number',''))>35 then
     raise exception 'Song number too long' using errcode='22023';
   end if;
   if url_value<>'' and not (
      (src='dam' and url_value ~* '^https://([a-z0-9-]+\.)*clubdam\.com(/|$)') or
      (src='joy' and url_value ~* '^https://([a-z0-9-]+\.)*joysound\.com(/|$)')
   ) then
     raise exception 'Only official HTTPS URLs are allowed' using errcode='22023';
   end if;
   if status_value='available' and url_value='' then
     raise exception 'Verified status needs official URL' using errcode='22023';
   end if;
 end loop;
 if coalesce(d->>'status','unknown')='unknown' and
    coalesce(j->>'status','unknown')='unknown' and n='' then
   delete from public.karaoke_records where lower(btrim(title))=lower(t)
     and lower(btrim(artist))=lower(a);
 else
   insert into public.karaoke_records(title,artist,dam,joy,notes,changed_by)
   values(t,a,d,j,n,actor)
   on conflict ((lower(btrim(title))),(lower(btrim(artist))))
   do update set dam=excluded.dam,joy=excluded.joy,
      notes=excluded.notes,changed_by=excluded.changed_by,updated_at=now();
 end if;
end;
$$;
revoke all on function private.denmoku_save_karaoke(jsonb,uuid) from public,anon,authenticated;
