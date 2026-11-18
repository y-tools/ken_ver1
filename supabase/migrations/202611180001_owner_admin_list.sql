-- オーナー専用：現在の管理者一覧（ID・表示名・ログインID・メール・権限・作成日・最終ログイン）。
-- パスワードはSupabase Authにハッシュでしか保存されないため、返さない（返せない）。
create or replace function public.denmoku_owner_admin_list()
returns table(id uuid, display_name text, login_id text, role text, email text,
              created_at timestamptz, last_sign_in_at timestamptz)
language plpgsql stable security definer set search_path='' as $$
begin
  if (select p.role from public.profiles p where p.id=(select auth.uid())) is distinct from 'owner' then
    raise exception 'Owner only' using errcode='42501';
  end if;
  return query
    select p.id, p.display_name, p.login_id, p.role, u.email::text, u.created_at, u.last_sign_in_at
    from public.profiles p join auth.users u on u.id=p.id
    where p.role in ('owner','admin')
    order by case p.role when 'owner' then 0 else 1 end, u.created_at;
end;
$$;
revoke all on function public.denmoku_owner_admin_list() from public, anon;
grant execute on function public.denmoku_owner_admin_list() to authenticated;
