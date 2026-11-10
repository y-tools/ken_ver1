-- Anonymous song requests: only through the server-side public-request Edge Function.
-- The Edge Function holds the service role key privately and hashes the connecting IP.
-- No anonymous write grants on public.requests or any other mutable data.
alter table public.requests alter column user_id drop not null;
create unique index if not exists denmoku_guest_request_nonce_unique
  on public.requests(client_nonce) where user_id is null;

create table if not exists private.guest_request_catalog(
  title text not null,
  artist text not null,
  primary key(title,artist)
);
revoke all on private.guest_request_catalog from public,anon,authenticated;
alter table private.guest_request_catalog enable row level security;

insert into private.guest_request_catalog(title,artist)
select item->>0,item->>1
from pg_catalog.jsonb_array_elements('[["12th laser","TK from 凛として時雨"],["5lies","TK from 凛として時雨"],["Abnormal trick","TK from 凛として時雨"],["Acoustic Installation","TK from 凛として時雨"],["Addictive Dancer","TK from 凛として時雨"],["Affaire classée","TK from 凛として時雨"],["As long as I love","TK from 凛として時雨"],["CRAZY感情STYLE","TK from 凛として時雨"],["Crazy Tampern","TK from 凛として時雨"],["Dramatic Slow Motion","TK from 凛として時雨"],["Ender Ember","TK from 凛として時雨"],["Fantastic Magic","TK from 凛として時雨"],["Fu re te Fu re ru","TK from 凛として時雨"],["Future Tone Bender","TK from 凛として時雨"],["GRANT","TK from 凛として時雨"],["Last Eye","TK from 凛として時雨"],["Microwaver","TK from 凛として時雨"],["Missing ling","TK from 凛として時雨"],["Missing ling (Acoustique Electrick Session for 0)","TK from 凛として時雨"],["P.S. RED I","TK from 凛として時雨"],["Scratch","TK from 凛として時雨"],["Secret Sensation","TK from 凛として時雨"],["Secret Sense","TK from 凛として時雨"],["Shandy","TK from 凛として時雨"],["Shinkiro","TK from 凛として時雨"],["Showcase Reflection","TK from 凛として時雨"],["Signal","TK from 凛として時雨"],["Spiral Parade","TK from 凛として時雨"],["Super bloom","TK from 凛として時雨"],["Synchrome","TK from 凛として時雨"],["The Game Begins","TK from 凛として時雨"],["UN-APEX","TK from 凛として時雨"],["Whose World? Whose Blue?","TK from 凛として時雨"],["Wonder Palette","TK from 凛として時雨"],["an artist","TK from 凛として時雨"],["contrast","TK from 凛として時雨"],["copy light","TK from 凛として時雨"],["daylily","TK from 凛として時雨"],["dead end complex","TK from 凛として時雨"],["eF","TK from 凛として時雨"],["ear+f","TK from 凛として時雨"],["end roll","TK from 凛として時雨"],["ephemeral mist","TK from 凛として時雨"],["film A moment","TK from 凛として時雨"],["first death","TK from 凛として時雨"],["flower","TK from 凛として時雨"],["fourth","TK from 凛として時雨"],["fragile","TK from 凛として時雨"],["haze","TK from 凛として時雨"],["illusion is mine","TK from 凛として時雨"],["invalid phrase","TK from 凛として時雨"],["kalappo","TK from 凛として時雨"],["kalei de scope","TK from 凛として時雨"],["kanazawan","TK from 凛として時雨"],["katharsis","TK from 凛として時雨"],["like A moment","TK from 凛として時雨"],["like there is tomorrow","TK from 凛として時雨"],["make up syndrome","TK from 凛として時雨"],["melt","TK from 凛として時雨"],["memento","TK from 凛として時雨"],["moving on","TK from 凛として時雨"],["musique","TK from 凛として時雨"],["orbit","TK from 凛として時雨"],["phase to phrase","TK from 凛として時雨"],["planet triangle","TK from 凛として時雨"],["pop eye","TK from 凛として時雨"],["reframe","TK from 凛として時雨"],["snow flurry","TK from 凛として時雨"],["sound_am326","TK from 凛として時雨"],["subliminal","TK from 凛として時雨"],["this is is this?","TK from 凛として時雨"],["toiki -prologue-","TK from 凛として時雨"],["tokio","TK from 凛として時雨"],["tokio (Acoustique Electrick Session for 0)","TK from 凛として時雨"],["unravel","TK from 凛として時雨"],["unravel (n-buna from ヨルシカ Remix) - Exhibition edit","TK from 凛として時雨"],["whisper -epilogue-","TK from 凛として時雨"],["white out","TK from 凛として時雨"],["white silence","TK from 凛として時雨"],["will-ill","TK from 凛として時雨"],["yesworld","TK from 凛として時雨"],["アシデマトイ","TK from 凛として時雨"],["インフィクション","TK from 凛として時雨"],["クジャクジャノマアムアイア","TK from 凛として時雨"],["クジャクジャノマアムアイア -TV edit-","TK from 凛として時雨"],["クローズド・アーカイヴ","TK from 凛として時雨"],["トモダチゲームR4 メインテーマ","TK from 凛として時雨"],["凡脳","TK from 凛として時雨"],["彩脳 -Sui Side-","TK from 凛として時雨"],["彩脳 -TK Side-","TK from 凛として時雨"],["掌の世界","TK from 凛として時雨"],["涙の旅路","TK from 凛として時雨"],["片つ","TK from 凛として時雨"],["罪の宝石","TK from 凛として時雨"],["蝶の飛ぶ水槽","TK from 凛として時雨"],["誰我為","TK from 凛として時雨"],["誰我為 (Acoustic version at Metropolis Studios)","TK from 凛として時雨"],["鶴の仕返し","TK from 凛として時雨"]]'::jsonb) as item
on conflict(title,artist) do nothing;

create table if not exists private.guest_request_limits(
  visitor_hash text primary key check(visitor_hash ~ '^[0-9a-f]{64}$'),
  last_request_at timestamptz,
  window_started timestamptz not null default now(),
  window_count integer not null default 0,
  day_started timestamptz not null default now(),
  day_count integer not null default 0
);
revoke all on private.guest_request_limits from public,anon,authenticated;
alter table private.guest_request_limits enable row level security;

create table if not exists private.guest_request_global_limit(
  id boolean primary key default true check(id),
  window_started timestamptz not null default now(),
  window_count integer not null default 0
);
insert into private.guest_request_global_limit(id) values(true) on conflict do nothing;
revoke all on private.guest_request_global_limit from public,anon,authenticated;
alter table private.guest_request_global_limit enable row level security;

create or replace function public.denmoku_guest_request(
  p_fingerprint text,p_nonce uuid,p_title text,p_artist text,
  p_nickname text,p_message text default ''
) returns uuid language plpgsql security definer set search_path='' as $$
declare
  v_title text; v_artist text; v_nick text := pg_catalog.btrim(p_nickname);
  v_note text := pg_catalog.btrim(coalesce(p_message,''));
  v_existing uuid; v_id uuid;
  v_window_start timestamptz; v_day_start timestamptz;
  v_window_count int; v_day_count int; v_last timestamptz;
  v_global_window timestamptz; v_global_count int;
begin
  if pg_catalog.current_setting('request.jwt.claim.role',true) is distinct from 'service_role' then
    raise exception 'Server authentication required' using errcode='42501';
  end if;
  if p_fingerprint is null or p_fingerprint !~ '^[0-9a-f]{64}$' or p_nonce is null then
    raise exception 'Invalid request credentials' using errcode='22023';
  end if;
  if p_title is null or length(pg_catalog.btrim(p_title)) not between 1 and 120 or
     p_artist is null or length(pg_catalog.btrim(p_artist)) not between 1 and 120 or
     v_nick is null or length(v_nick) not between 1 and 40 or
     length(v_note)>200 or
     v_nick ~ '[<>]' or v_note ~* '(https?://|www\.)'
  then
    raise exception 'Invalid request fields' using errcode='22023';
  end if;

  -- An owner may toggle ON AIR at any time. Hold this row lock through insert,
  -- limits and sync_version to avoid a race between stream stop and request.
  perform 1 from public.stream_status where id=true for update;
  if not (select live from public.stream_status where id=true) then
    raise exception 'Requests are closed (OFF AIR)' using errcode='23514';
  end if;

  -- Retry-safe nonce; no new song request or quota is consumed on retries.
  select id into v_existing from public.requests
  where user_id is null and client_nonce=p_nonce;
  if v_existing is not null then return v_existing; end if;

  select c.title,c.artist into v_title,v_artist
  from private.guest_request_catalog c
  where pg_catalog.lower(pg_catalog.btrim(c.title))=pg_catalog.lower(pg_catalog.btrim(p_title))
    and pg_catalog.lower(pg_catalog.btrim(c.artist))=pg_catalog.lower(pg_catalog.btrim(p_artist))
  limit 1;
  if v_title is null then
    raise exception 'Select a song from the TK catalog' using errcode='22023';
  end if;

  insert into private.guest_request_limits(visitor_hash)
    values(p_fingerprint) on conflict(visitor_hash) do nothing;
  select last_request_at,window_started,window_count,day_started,day_count
    into v_last,v_window_start,v_window_count,v_day_start,v_day_count
  from private.guest_request_limits where visitor_hash=p_fingerprint for update;
  if v_last is not null and v_last>now()-interval '15 seconds' then
    raise exception 'Too many requests: retry later' using errcode='P0001';
  end if;
  if v_window_start<=now()-interval '10 minutes' then
    v_window_start:=now();v_window_count:=0;
  end if;
  if v_day_start<=now()-interval '24 hours' then
    v_day_start:=now();v_day_count:=0;
  end if;
  if v_window_count>=12 or v_day_count>=40 then
    raise exception 'Request quota reached: retry later' using errcode='P0001';
  end if;

  select window_started,window_count into v_global_window,v_global_count
    from private.guest_request_global_limit where id=true for update;
  if v_global_window<=now()-interval '1 minute' then
    v_global_window:=now();v_global_count:=0;
  end if;
  if v_global_count>=90 then
    raise exception 'Too many requests now: retry later' using errcode='P0001';
  end if;
  insert into public.requests(user_id,client_nonce,title,artist,nickname,message,status)
    values(null,p_nonce,v_title,v_artist,v_nick,v_note,'new') returning id into v_id;
  update private.guest_request_limits
  set last_request_at=now(),window_started=v_window_start,
      window_count=v_window_count+1,day_started=v_day_start,day_count=v_day_count+1
  where visitor_hash=p_fingerprint;
  update private.guest_request_global_limit
  set window_started=v_global_window,window_count=v_global_count+1 where id=true;
  perform private.denmoku_event('request',pg_catalog.jsonb_build_object(
    'requestId',v_id,'title',v_title,'artist',v_artist,'nickname',v_nick));
  update public.sync_version set version=version+1,updated_at=now() where id=true;
  return v_id;
end;
$$;

revoke all on function public.denmoku_guest_request(text,uuid,text,text,text,text)
 from public,anon,authenticated;
grant execute on function public.denmoku_guest_request(text,uuid,text,text,text,text)
 to service_role;
