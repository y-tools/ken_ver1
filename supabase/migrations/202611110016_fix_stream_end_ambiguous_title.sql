-- Fix stream_end failure (PostgreSQL 42702: column reference "title" is ambiguous).
-- denmoku_action declares local title/artist variables. In stream_end, the
-- INSERT ... SELECT used unqualified request column names. PostgreSQL could
-- not decide whether "title" meant the PL/pgSQL variable or table column.
-- Preserve the rest of the RPC, grants, sessions, reports and queue behavior.
-- Idempotent: an already-fixed function is left unchanged.
do $denmoku_fix_stream_end$
declare
  v_definition text;
  v_old constant text := 'select id,title,artist,nickname,now() from public.requests where id=rid';
  v_new constant text := 'select r.id,r.title,r.artist,r.nickname,now() from public.requests r where r.id=rid';
  v_occurrences integer;
begin
  select pg_catalog.pg_get_functiondef(
    'public.denmoku_action(text,jsonb)'::regprocedure
  ) into v_definition;
  if pg_catalog.position(v_new in v_definition) > 0 then
    raise notice 'denmoku stream_end: already fixed';
    return;
  end if;
  v_occurrences := (length(v_definition)-length(replace(v_definition,v_old,'')))/length(v_old);
  if v_occurrences <> 1 then
    raise exception 'denmoku stream_end: expected one ambiguous SELECT, found %',v_occurrences;
  end if;
  execute replace(v_definition,v_old,v_new);
end;
$denmoku_fix_stream_end$;
