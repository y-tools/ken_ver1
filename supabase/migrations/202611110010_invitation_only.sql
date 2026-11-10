-- Enforce owner-invitation-only creation of all NEW Auth users.
-- Existing owner unchanged, only owner-initiated admin invitations create new accounts.
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer set search_path='' as $$
declare requested_id text; v_email text:=lower(btrim(coalesce(new.email,'')));
begin
 if not exists(
    select 1 from public.admin_invites ai
    where lower(ai.email)=v_email
      and ai.status='pending' and ai.expires_at>now()
 ) then
   raise exception 'New accounts require an owner invitation' using errcode='42501';
 end if;
 requested_id:=nullif(lower(btrim(new.raw_user_meta_data ->> 'login_id')),'');
 if requested_id is not null and requested_id !~ '^[a-z][a-z0-9._-]{3,23}$'
 then raise exception 'Invalid login ID' using errcode='22023'; end if;
 insert into public.profiles(id,display_name,role,login_id)
 values(new.id,left(coalesce(nullif(btrim(new.raw_user_meta_data ->> 'display_name'),''),'ユーザー'),40),
        'listener',requested_id)
 on conflict(id) do nothing;
 return new;
end; $$;
revoke all on function public.handle_new_user() from public,anon,authenticated;
