-- Keep profile SELECT policy restrictive while avoiding overlapping permissive policies.
drop policy if exists "Read own profile" on public.profiles;
drop policy if exists "Owner reads all profiles" on public.profiles;
create policy "Read own profile or owner views profiles" on public.profiles
  for select to authenticated
  using (id=(select auth.uid()) or (select private.current_role())='owner');

-- Index common foreign-key relationships; these tables use RLS and admin reporting.
create index if not exists denmoku_invites_invited_by_idx on public.admin_invites(invited_by);
create index if not exists denmoku_logs_actor_idx on public.admin_logs(actor_id);
create index if not exists denmoku_notes_created_by_idx on public.admin_notes(created_by);
create index if not exists denmoku_karaoke_changed_by_idx on public.karaoke_records(changed_by);
create index if not exists denmoku_stream_active_session_idx on public.stream_status(active_session_id);
create index if not exists denmoku_stream_updated_by_idx on public.stream_status(updated_by);
