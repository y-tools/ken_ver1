"""Ken Denmoku read-only song search API.

GitHub Pages remains a static client. PostgreSQL runs privately on the user's
VPS. Put this service behind TLS and nginx rate limiting; never publish port
5432 or credentials. See server/README.md for operational prerequisites.
"""
from __future__ import annotations

import asyncio
import logging
import json
import os
import re
import urllib.request
import unicodedata
from contextlib import asynccontextmanager
from collections import OrderedDict, deque
from time import monotonic
from datetime import date
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

DATABASE_URL = os.environ.get("KEN_DATABASE_URL", "")
_ALLOWED = os.environ.get("KEN_ALLOWED_ORIGINS", "https://y-tools.github.io")
ORIGINS = [v.strip() for v in _ALLOWED.split(",") if v.strip()]
if any(v == "*" or not v.startswith(("https://", "http://localhost:", "http://127.0.0.1:")) for v in ORIGINS):
    raise RuntimeError("KEN_ALLOWED_ORIGINS must contain explicit trusted HTTPS origins")
if not DATABASE_URL:
    raise RuntimeError("Set KEN_DATABASE_URL from an environment file, never from frontend code")


def norm(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = "".join(chr(ord(c) - 96) if "\u30a1" <= c <= "\u30f6" else c for c in value)
    return re.sub(r"[\s\u3000・ー‐-]", "", value)


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool = AsyncConnectionPool(
        conninfo=DATABASE_URL,
        min_size=1,
        max_size=int(os.getenv("KEN_DB_POOL_SIZE", "3")),
        open=False,
        kwargs={"row_factory": dict_row, "autocommit": False},
        timeout=5,
    )
    await pool.open(wait=True, timeout=10)
    app.state.pool = pool
    try:
        yield
    finally:
        await pool.close()


app = FastAPI(title="Ken Song Search API", version="0.1.0", lifespan=lifespan, docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Accept", "Content-Type", "Authorization"],
    allow_credentials=False,
    max_age=1800,
)

# Single-worker in-memory burst limit; Caddy remains the only public reverse proxy.
# Explicit rate limiting avoids accidental overload of the shared VPS.
_SEARCH_REQUESTS = OrderedDict()
_MAX_REQUESTS_PER_MINUTE = 60
_MAX_TRACKED_CLIENTS = 5000


@app.middleware("http")
async def search_rate_limit(request: Request, call_next):
    if request.url.path not in ("/api/v1/search", "/api/v1/stats", "/api/v1/priority-requests", "/api/v1/artists") and \
            not request.url.path.startswith(("/api/v1/priority-requests/", "/api/v1/artists/", "/api/v1/utachaoh/")):
        return await call_next(request)
    ip = request.client.host if request.client else "unknown"
    now = monotonic()
    bucket = _SEARCH_REQUESTS.setdefault(ip, deque())
    _SEARCH_REQUESTS.move_to_end(ip)
    while bucket and now - bucket[0] > 60:
        bucket.popleft()
    if len(bucket) >= _MAX_REQUESTS_PER_MINUTE:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many searches. Please retry shortly."},
            headers={"Retry-After": "10"},
        )
    bucket.append(now)
    while len(_SEARCH_REQUESTS) > _MAX_TRACKED_CLIENTS:
        _SEARCH_REQUESTS.popitem(last=False)
    return await call_next(request)


# IDs are not sequential public data paths; API exposes only read-only search.
SEARCH_TITLE = """
WITH matched AS (
 SELECT id AS song_id, CASE WHEN title_key LIKE %s ESCAPE '!' THEN 0 ELSE 1 END AS priority
 FROM songs WHERE title_key LIKE %s ESCAPE '!'
 UNION ALL
 SELECT song_id, CASE WHEN search_key LIKE %s ESCAPE '!' THEN 2 ELSE 3 END AS priority
 FROM song_names WHERE search_key LIKE %s ESCAPE '!'
)
SELECT s.id, s.title, s.release_year, s.release_month, s.release_day,
       s.release_precision, a.id AS artist_id, a.name AS artist,
       MIN(m.priority) AS match_priority
FROM matched m JOIN songs s ON s.id=m.song_id
JOIN artists a ON a.id=s.primary_artist_id
GROUP BY s.id,a.id
ORDER BY MIN(m.priority),s.id
LIMIT %s
"""
SEARCH_ARTIST = """
WITH matched AS (
 SELECT id AS artist_id, CASE WHEN name_key LIKE %s ESCAPE '!' THEN 0 ELSE 1 END AS priority
 FROM artists WHERE name_key LIKE %s ESCAPE '!'
 UNION ALL
 SELECT artist_id, CASE WHEN search_key LIKE %s ESCAPE '!' THEN 2 ELSE 3 END AS priority
 FROM artist_names WHERE search_key LIKE %s ESCAPE '!'
)
SELECT s.id, s.title, s.release_year, s.release_month, s.release_day,
       s.release_precision, a.id AS artist_id, a.name AS artist,
       MIN(m.priority) AS match_priority
FROM matched m JOIN artists a ON a.id=m.artist_id
JOIN songs s ON s.primary_artist_id=a.id
GROUP BY s.id,a.id
ORDER BY MIN(m.priority),s.id
LIMIT %s
"""

READINGS = """
SELECT 'title' AS side, song_id AS entity_id, kind, value, verification
FROM song_names WHERE song_id = ANY(%s) AND kind IN ('hiragana','katakana','romaji','english')
UNION ALL
SELECT 'artist' AS side, artist_id AS entity_id, kind, value, verification
FROM artist_names WHERE artist_id = ANY(%s) AND kind IN ('hiragana','katakana','romaji','english')
"""


@app.get("/api/v1/health")
async def health(request: Request):
    try:
        async with request.app.state.pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1")
                await cur.fetchone()
    except Exception:
        raise HTTPException(status_code=503, detail="Service unavailable")
    return {"ok": True, "service": "ken-song-api"}


_STATS_CACHE: dict = {"at": 0.0, "data": None}


@app.get("/api/v1/stats")
async def stats(request: Request):
    """Public aggregate counts only (no rows). Cached briefly to protect the VPS."""
    now = monotonic()
    if _STATS_CACHE["data"] is not None and now - _STATS_CACHE["at"] < 5:
        return _STATS_CACHE["data"]
    try:
        async with request.app.state.pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    await cur.execute("SET LOCAL statement_timeout = '2500ms'")
                    await cur.execute("SET LOCAL default_transaction_read_only = on")
                    await cur.execute(
                        "SELECT (SELECT COUNT(*) FROM songs) AS song_count,"
                        " (SELECT COUNT(*) FROM artists) AS artist_count"
                    )
                    row = await cur.fetchone()
    except Exception:
        raise HTTPException(status_code=503, detail="Stats temporarily unavailable")
    data = {"songCount": int(row["song_count"]), "artistCount": int(row["artist_count"])}
    _STATS_CACHE.update(at=now, data=data)
    return data


# ---------------------------------------------------------------------------
# Kenの優先リクエスト (admin only). The browser sends its Supabase access token;
# the VPS verifies it with Supabase and requires profiles.role owner/admin.
SUPABASE_URL = os.environ.get("KEN_SUPABASE_URL", "https://kflsbmlpupvpbwsenfba.supabase.co").rstrip("/")
SUPABASE_KEY = os.environ.get("KEN_SUPABASE_PUBLISHABLE_KEY", "sb_publishable_2Mm0B-H0tGj0CfKRavlptg_onKxPkFM")
_ADMIN_CACHE: OrderedDict = OrderedDict()
# Kenの優先リクエストを使えるログインID（大文字小文字は区別しない）
PRIORITY_LOGIN_IDS = {
    v.strip().lower() for v in os.environ.get("KEN_PRIORITY_LOGIN_IDS", "kenmorley05280602").split(",") if v.strip()
}


def _supabase_get(path: str, token: str):
    req = urllib.request.Request(
        SUPABASE_URL + path,
        headers={"apikey": SUPABASE_KEY, "Authorization": "Bearer " + token, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=6) as res:
        return json.loads(res.read().decode("utf-8"))


async def require_priority_user(authorization: str | None) -> dict:
    admin = await require_admin(authorization)
    # オーナーと、許可されたログインID（けんもり(kenmorley05280602)）だけが利用できる
    if admin["role"] != "owner" and admin["login_id"] not in PRIORITY_LOGIN_IDS:
        logging.getLogger("uvicorn.error").warning(
            "priority denied: role=%s login_id=%r", admin.get("role"), admin.get("login_id"))
        raise HTTPException(status_code=403, detail="Kenの優先リクエストは許可されたIDだけが利用できます")
    return admin


async def require_admin(authorization: str | None) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="管理者ログインが必要です")
    token = authorization[7:].strip()
    if not (20 <= len(token) <= 4096):
        raise HTTPException(status_code=401, detail="管理者ログインが必要です")
    now = monotonic()
    hit = _ADMIN_CACHE.get(token)
    if hit and now - hit[0] < 60:
        return hit[1]
    try:
        user = await asyncio.to_thread(_supabase_get, "/auth/v1/user", token)
        uid = str(user.get("id") or "")
        if not re.fullmatch(r"[0-9a-f-]{36}", uid):
            raise ValueError("no user")
        rows = await asyncio.to_thread(
            _supabase_get, "/rest/v1/profiles?select=role,display_name,login_id&id=eq." + uid, token
        )
    except Exception:
        raise HTTPException(status_code=401, detail="ログインを確認できませんでした。再ログインしてください")
    profile = rows[0] if isinstance(rows, list) and rows else {}
    if profile.get("role") not in ("owner", "admin"):
        logging.getLogger("uvicorn.error").warning(
            "admin denied: role=%r login_id=%r", profile.get("role"), profile.get("login_id"))
        raise HTTPException(status_code=403, detail="管理者のみ利用できます")
    info = {"uid": uid, "name": str(profile.get("display_name") or "")[:80],
            "login_id": str(profile.get("login_id") or "").lower(), "role": profile.get("role")}
    _ADMIN_CACHE[token] = (now, info)
    while len(_ADMIN_CACHE) > 200:
        _ADMIN_CACHE.popitem(last=False)
    return info


class PriorityRequestIn(BaseModel):
    kind: Literal["song", "artist"]
    artist: str = Field(min_length=1, max_length=120)
    title: str | None = Field(default=None, max_length=120)
    note: str = Field(default="", max_length=300)


def _priority_row(r: dict) -> dict:
    return {
        "id": r["id"], "kind": r["kind"], "artist": r["artist_name"], "title": r["song_title"],
        "note": r["note"], "status": r["status"], "requestedBy": r["requested_by"],
        "createdAt": r["created_at"].isoformat(),
        "handledAt": r["handled_at"].isoformat() if r["handled_at"] else None,
        "completedAt": r["completed_at"].isoformat() if r["completed_at"] else None,
        "addedArtistName": r["added_artist_name"],
        "addedSongCount": r["added_song_count"],
    }


PRIORITY_COLUMNS = ("id, kind, artist_name, song_title, note, status, requested_by, created_at,"
                    " handled_at, completed_at, added_artist_name, added_song_count")


@app.get("/api/v1/priority-requests")
async def list_priority_requests(request: Request, authorization: str | None = Header(default=None)):
    await require_priority_user(authorization)
    try:
        async with request.app.state.pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"SELECT {PRIORITY_COLUMNS} FROM ken_priority_requests WHERE cleared_at IS NULL"
                    " ORDER BY created_at DESC, id DESC LIMIT 200"
                )
                rows = await cur.fetchall()
            await conn.rollback()
    except Exception:
        raise HTTPException(status_code=503, detail="優先リクエストを読み込めませんでした")
    return {"items": [_priority_row(r) for r in rows]}


@app.post("/api/v1/priority-requests", status_code=201)
async def add_priority_request(
    request: Request, body: PriorityRequestIn, authorization: str | None = Header(default=None)
):
    admin = await require_priority_user(authorization)
    bad = re.compile(r"[<>\x00-\x1f]")
    artist = body.artist.strip()
    title = (body.title or "").strip() or None
    note = body.note.strip()
    if not artist or bad.search(artist) or (title and bad.search(title)) or re.search(r"[\x00-\x08\x0b-\x1f]", note):
        raise HTTPException(status_code=422, detail="入力内容を確認してください")
    if body.kind == "song" and not title:
        raise HTTPException(status_code=422, detail="曲名を入力してください")
    if body.kind == "artist":
        title = None
    try:
        async with request.app.state.pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    await cur.execute("SET TRANSACTION READ WRITE")
                    await cur.execute(
                        f"""INSERT INTO ken_priority_requests(kind, artist_name, song_title, note, requested_by, requested_uid)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            ON CONFLICT DO NOTHING RETURNING {PRIORITY_COLUMNS}""",
                        (body.kind, artist, title, note, admin["name"], admin["uid"]),
                    )
                    row = await cur.fetchone()
    except Exception:
        raise HTTPException(status_code=503, detail="優先リクエストを保存できませんでした")
    if row is None:
        raise HTTPException(status_code=409, detail="同じ内容がすでにリクエスト済みです")
    return {"item": _priority_row(row)}


# 対応日・追加アーティスト名・追加楽曲数・完了日時はクロードの処理がDBへ直接書き込む。
# 管理画面（公開API）からは変更できないよう、状態変更APIは提供しない。


@app.post("/api/v1/priority-requests/{request_id}/clear")
async def clear_priority_request(request: Request, request_id: int, authorization: str | None = Header(default=None)):
    """対応完了のものだけ一覧から消し込む（行は残し cleared_at を記録）。"""
    await require_priority_user(authorization)
    try:
        async with request.app.state.pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    await cur.execute("SET TRANSACTION READ WRITE")
                    await cur.execute(
                        "UPDATE ken_priority_requests SET cleared_at=now(), updated_at=now()"
                        " WHERE id=%s AND status='done' AND cleared_at IS NULL RETURNING id",
                        (request_id,),
                    )
                    row = await cur.fetchone()
    except Exception:
        raise HTTPException(status_code=503, detail="消し込みできませんでした")
    if row is None:
        raise HTTPException(status_code=409, detail="対応完了のリクエストだけ消し込みできます")
    return {"ok": True, "id": request_id}


# ---------------------------------------------------------------------------
# データベース閲覧（読み取り専用）: アーティスト検索 → 登録楽曲一覧
BROWSE_ARTISTS = """
SELECT a.id, a.name, (SELECT COUNT(*) FROM songs s WHERE s.primary_artist_id=a.id) AS song_count,
       CASE WHEN a.name_key LIKE %s ESCAPE '!' THEN 0 ELSE 1 END AS rank
FROM artists a
WHERE %s = '' OR a.name_key LIKE %s ESCAPE '!'
   OR EXISTS (SELECT 1 FROM artist_names n WHERE n.artist_id=a.id AND n.search_key LIKE %s ESCAPE '!')
ORDER BY rank, a.name_key, a.id
LIMIT %s
"""


@app.get("/api/v1/artists")
async def browse_artists(request: Request, q: str = Query(default="", max_length=120),
                         limit: int = Query(100, ge=1, le=300)):
    term = norm(q)
    escaped = term.replace("!", "!!").replace("%", "!%").replace("_", "!_")
    prefix, pattern = escaped + "%", "%" + escaped + "%"
    try:
        async with request.app.state.pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    await cur.execute("SET LOCAL statement_timeout = '2500ms'")
                    await cur.execute(BROWSE_ARTISTS, (prefix, term, pattern, pattern, limit))
                    rows = await cur.fetchall()
    except Exception:
        raise HTTPException(status_code=503, detail="アーティストを読み込めませんでした")
    return {"items": [{"id": r["id"], "name": r["name"], "songCount": int(r["song_count"])} for r in rows]}


@app.get("/api/v1/artists/{artist_id}/songs")
async def browse_artist_songs(request: Request, artist_id: int):
    try:
        async with request.app.state.pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    await cur.execute("SET LOCAL statement_timeout = '2500ms'")
                    await cur.execute("SELECT id, name FROM artists WHERE id=%s", (artist_id,))
                    artist = await cur.fetchone()
                    if artist is None:
                        raise HTTPException(status_code=404, detail="アーティストが見つかりません")
                    await cur.execute(
                        """SELECT id, title, release_year, release_month, release_day, release_precision
                           FROM songs WHERE primary_artist_id=%s ORDER BY title_key, id LIMIT 2000""",
                        (artist_id,),
                    )
                    rows = await cur.fetchall()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="楽曲を読み込めませんでした")
    def release(r):
        p = r["release_precision"]
        if p == "unknown" or r["release_year"] is None:
            return None
        parts = [str(r["release_year"])]
        if p in ("month", "day"):
            parts.append(f'{r["release_month"]:02d}')
        if p == "day":
            parts.append(f'{r["release_day"]:02d}')
        return "-".join(parts)
    return {"artist": {"id": artist["id"], "name": artist["name"]},
            "items": [{"id": r["id"], "title": r["title"], "releaseDate": release(r)} for r in rows]}


@app.get("/api/v1/search")
async def search(
    request: Request,
    q: str = Query(min_length=2, max_length=120),
    mode: Literal["title", "artist"] = "title",
    limit: int = Query(30, ge=1, le=50),
):
    term = norm(q)
    if len(term) < 2:
        return {"items": [], "query": q, "mode": mode}
    if len(term) > 120:
        raise HTTPException(status_code=422, detail="Query is too long")
    escaped = term.replace("!", "!!").replace("%", "!%").replace("_", "!_")
    # Prefix matches rank first, but partial (middle) matches are also returned
    # so that e.g. "凛として" finds "TK from 凛として時雨".
    prefix = escaped + "%"
    pattern = "%" + escaped + "%"
    statement = SEARCH_ARTIST if mode == "artist" else SEARCH_TITLE
    try:
        async with request.app.state.pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    await cur.execute("SET LOCAL statement_timeout = '2500ms'")
                    await cur.execute("SET LOCAL default_transaction_read_only = on")
                    await cur.execute(statement, (prefix, pattern, prefix, pattern, limit))
                    rows = await cur.fetchall()
                    song_ids = [r["id"] for r in rows]
                    artist_ids = list({r["artist_id"] for r in rows})
                    name_rows = []
                    if song_ids:
                        await cur.execute(READINGS, (song_ids, artist_ids))
                        name_rows = await cur.fetchall()
    except Exception:
        # Do not leak table names, SQL or database credentials to anonymous clients.
        raise HTTPException(status_code=503, detail="Search temporarily unavailable")

    preferred = {"human_confirmed": 0, "source_confirmed": 1, "derived_from_confirmed": 2, "estimated": 3}
    names = {}
    for v in sorted(name_rows, key=lambda x: preferred.get(x["verification"], 9)):
        names.setdefault((v["side"], v["entity_id"], v["kind"]), v)
    def group(side: str, id_: int):
        data = {}
        for kind in ("hiragana", "katakana", "romaji", "english"):
            v = names.get((side, id_, kind))
            if v:
                data[kind] = v["value"]
                data[kind + "Verification"] = v["verification"]
        return data
    items = []
    for r in rows:
        precision = r["release_precision"]
        parts = [str(r["release_year"])] if precision != "unknown" else []
        if precision in ("month", "day"):
            parts.append(f'{r["release_month"]:02d}')
        if precision == "day":
            parts.append(f'{r["release_day"]:02d}')
        items.append({
            "id": r["id"],
            "title": r["title"],
            "artist": r["artist"],
            "releaseDate": "-".join(parts) if parts else None,
            "releasePrecision": precision,
            "readings": {
                "type": "verified_or_estimated",
                "title": group("title", r["id"]),
                "artist": group("artist", r["artist_id"]),
            },
        })
    return {"items": items, "query": q, "mode": mode}


# ---- 歌っちゃ王（YouTube @uta-cha-oh）専用DB: 1行=動画1本。既存の楽曲DBとは別系統 ----
UTACHAOH_SEARCH = """
SELECT youtube_id, video_title, video_type,
       artist_name, artist_hiragana, artist_katakana, artist_english, artist_reading_verification,
       song_title, song_hiragana, song_katakana, song_english, song_reading_verification,
       (CASE WHEN %(a)s = '' THEN 0 WHEN artist_search_key LIKE %(ap)s ESCAPE '!' OR artist_search_key LIKE %(ab)s ESCAPE '!' THEN 0 ELSE 1 END
        + CASE WHEN %(t)s = '' THEN 0 WHEN song_search_key LIKE %(tp)s ESCAPE '!' OR song_search_key LIKE %(tb)s ESCAPE '!' THEN 0 ELSE 1 END) AS rank
FROM utachaoh_videos
WHERE (%(a)s = '' OR artist_search_key LIKE %(am)s ESCAPE '!')
  AND (%(t)s = '' OR song_search_key LIKE %(tm)s ESCAPE '!')
ORDER BY rank, artist_name, song_title, channel_order
LIMIT %(limit)s
"""


def _like(term: str) -> str:
    return term.replace("!", "!!").replace("%", "!%").replace("_", "!_")


@app.get("/api/v1/utachaoh/search")
async def utachaoh_search(
    request: Request,
    artist: str = Query("", max_length=120),
    title: str = Query("", max_length=120),
    limit: int = Query(50, ge=1, le=100),
):
    a, t = norm(artist), norm(title)
    if not a and not t:
        return {"items": [], "artist": artist, "title": title}
    ea, et = _like(a), _like(t)
    params = {"a": a, "t": t, "limit": limit,
              "ap": ea + "%", "ab": "%|" + ea + "%", "am": "%" + ea + "%",
              "tp": et + "%", "tb": "%|" + et + "%", "tm": "%" + et + "%"}
    try:
        async with request.app.state.pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    await cur.execute("SET LOCAL statement_timeout = '2500ms'")
                    await cur.execute("SET LOCAL default_transaction_read_only = on")
                    await cur.execute(UTACHAOH_SEARCH, params)
                    rows = await cur.fetchall()
    except Exception:
        raise HTTPException(status_code=503, detail="Search temporarily unavailable")
    items = []
    for r in rows:
        items.append({
            "youtubeId": r["youtube_id"],
            "url": "https://www.youtube.com/watch?v=" + r["youtube_id"],
            "videoTitle": r["video_title"],
            "videoType": r["video_type"],
            "artist": {"name": r["artist_name"], "hiragana": r["artist_hiragana"],
                       "katakana": r["artist_katakana"], "english": r["artist_english"],
                       "verification": r["artist_reading_verification"]},
            "song": {"title": r["song_title"], "hiragana": r["song_hiragana"],
                     "katakana": r["song_katakana"], "english": r["song_english"],
                     "verification": r["song_reading_verification"]},
        })
    return {"items": items, "artist": artist, "title": title}


@app.get("/api/v1/utachaoh/stats")
async def utachaoh_stats(request: Request):
    try:
        async with request.app.state.pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT COUNT(*) AS n, COUNT(DISTINCT artist_name) AS a FROM utachaoh_videos")
                r = await cur.fetchone()
    except Exception:
        raise HTTPException(status_code=503, detail="Stats temporarily unavailable")
    return {"videoCount": r["n"], "artistCount": r["a"]}
