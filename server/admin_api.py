"""Authenticated song database editor for the Ken Denmoku VPS.

Separate from public search API. Requires one-time administrator password set
on the VPS and a dedicated Postgres role. Bearer tokens are kept only in
browser memory (not localStorage) and expire after 30 minutes.
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import unicodedata
from collections import defaultdict, deque
from datetime import date, datetime, timedelta, timezone
from time import monotonic
from typing import Literal
from urllib.parse import urlparse

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator, model_validator
from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from contextlib import asynccontextmanager

DB_URL = os.environ.get("KEN_ADMIN_DATABASE_URL", "")
PASSWORD_HASH = os.environ.get("KEN_ADMIN_PASSWORD_HASH", "")
ORIGINS = [
    value.strip() for value in os.environ.get("KEN_ALLOWED_ORIGINS", "https://y-tools.github.io").split(",")
    if value.strip()
]
if not DB_URL or not PASSWORD_HASH:
    raise RuntimeError("Administrator database and password hash must be configured on the VPS")
if any(v == "*" or not v.startswith("https://") for v in ORIGINS):
    raise RuntimeError("Only explicit HTTPS origins may administer the database")
if not PASSWORD_HASH.startswith("$argon2id$"):
    raise RuntimeError("KEN_ADMIN_PASSWORD_HASH must be an Argon2id hash")

password_hasher = PasswordHasher()
sessions: dict[str, float] = {}
login_attempts: dict[str, deque[float]] = defaultdict(deque)
MAX_SESSIONS = 8
SESSION_SECONDS = 1800


def normalized(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = "".join(chr(ord(ch) - 96) if "\u30a1" <= ch <= "\u30f6" else ch for ch in value)
    return re.sub(r"[\s\u3000・ー‐-]", "", value)


def clean_url(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    url = value.strip()
    parts = urlparse(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or len(url) > 600:
        raise ValueError("出典URLにはHTTPSの公開ページを指定してください")
    return url


def as_iso(value):
    return value.isoformat() if value else None


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool = AsyncConnectionPool(
        conninfo=DB_URL,
        min_size=1, max_size=2,
        open=False, timeout=5,
        kwargs={"row_factory": dict_row},
    )
    await pool.open(wait=True, timeout=10)
    app.state.pool = pool
    try:
        yield
    finally:
        await pool.close()


app = FastAPI(title="Ken Music Database Editor API", version="0.1", lifespan=lifespan, docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGINS,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
    allow_credentials=False,
    max_age=600,
)


@app.middleware("http")
async def reject_wrong_origin(request: Request, call_next):
    # Browser cross-site requests must originate from the official GitHub Pages UI.
    # Auth tokens also protect against non-browser requests; CORS alone is not auth.
    origin = request.headers.get("origin")
    if origin is not None and origin not in ORIGINS:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=403, content={"detail": "Origin not permitted"})
    return await call_next(request)


class Login(BaseModel):
    password: str = Field(min_length=8, max_length=256)


def auth(authorization: str | None = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "管理者ログインが必要です")
    token = authorization[7:]
    if len(token) > 200:
        raise HTTPException(401, "Invalid session")
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    exp = sessions.get(token_hash)
    if exp is None or exp < monotonic():
        sessions.pop(token_hash, None)
        raise HTTPException(401, "セッションの有効期限が切れました")
    return token_hash


@app.post("/api/admin/login")
async def login(body: Login, request: Request):
    ip = request.client.host if request.client else "unknown"
    now = monotonic()
    entries = login_attempts[ip]
    while entries and now - entries[0] > 900:
        entries.popleft()
    if len(entries) >= 5:
        raise HTTPException(429, "ログイン試行回数が上限を超えました。15分後にお試しください。")
    entries.append(now)
    try:
        match = password_hasher.verify(PASSWORD_HASH, body.password)
    except (VerifyMismatchError, VerificationError):
        match = False
    if not match:
        raise HTTPException(401, "認証できませんでした")
    entries.clear()
    # Tokens are opaque, short-lived, and stored server-side only as hashes.
    for key, deadline in list(sessions.items()):
        if deadline <= now:
            del sessions[key]
    if len(sessions) >= MAX_SESSIONS:
        raise HTTPException(429, "同時ログイン数が上限です")
    token = secrets.token_urlsafe(48)
    sessions[hashlib.sha256(token.encode()).hexdigest()] = now + SESSION_SECONDS
    return {"token": token, "expiresIn": SESSION_SECONDS}


@app.post("/api/admin/logout")
async def logout(token_hash: str = Depends(auth)):
    sessions.pop(token_hash, None)
    return {"ok": True}


@app.get("/api/admin/session")
async def session_check(token_hash: str = Depends(auth)):
    return {"ok": True, "expiresIn": max(0, int(sessions[token_hash] - monotonic()))}


def encode_artist(row):
    return {"id": row["id"], "name": row["name"], "version": as_iso(row["updated_at"]),
            "lastResearchedOn": as_iso(row.get("last_researched_on"))}


def encode_song(row):
    return {
        "id": row["id"], "title": row["title"], "version": as_iso(row["updated_at"]),
        "releaseYear": row["release_year"], "releaseMonth": row["release_month"],
        "releaseDay": row["release_day"], "releasePrecision": row["release_precision"],
    }


def encode_alias(row):
    return {
        "id": row["id"], "kind": row["kind"], "value": row["value"],
        "verification": row["verification"], "sourceUrl": row["source_url"],
        "checkedAt": as_iso(row["checked_at"]),
    }


@app.get("/api/admin/artists")
async def artists(request: Request, q: str = Query(min_length=2, max_length=80), token_hash: str = Depends(auth)):
    term = normalized(q)
    if len(term) < 2:
        return {"items": []}
    pattern = term.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
    async with request.app.state.pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                WITH matches AS (
                  SELECT id AS artist_id FROM artists WHERE name_key LIKE %s ESCAPE '!'
                  UNION
                  SELECT artist_id FROM artist_names WHERE search_key LIKE %s ESCAPE '!'
                )
                SELECT a.id, a.name, a.updated_at, a.last_researched_on
                FROM matches m JOIN artists a ON a.id=m.artist_id
                ORDER BY a.name LIMIT 40
                """, (pattern, pattern))
            rows = await cur.fetchall()
    return {"items": [encode_artist(row) for row in rows]}


@app.get("/api/admin/artists/{artist_id}")
async def artist_detail(
    artist_id: int, request: Request,
    offset: int = Query(0, ge=0, le=200000),
    limit: int = Query(50, ge=1, le=100),
    token_hash: str = Depends(auth),
):
    async with request.app.state.pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id,name,updated_at,last_researched_on FROM artists WHERE id=%s", (artist_id,))
            artist = await cur.fetchone()
            if not artist:
                raise HTTPException(404, "アーティストが見つかりません")
            await cur.execute("""
              SELECT id,kind,value,verification,source_url,checked_at
              FROM artist_names WHERE artist_id=%s
              ORDER BY kind,CASE verification WHEN 'human_confirmed' THEN 0 WHEN 'source_confirmed' THEN 1 ELSE 2 END,id
              LIMIT 100
            """, (artist_id,))
            aliases = await cur.fetchall()
            await cur.execute("SELECT COUNT(*) AS count FROM songs WHERE primary_artist_id=%s", (artist_id,))
            total = (await cur.fetchone())["count"]
            await cur.execute("""
              SELECT id,title,release_year,release_month,release_day,release_precision,updated_at
              FROM songs WHERE primary_artist_id=%s ORDER BY title,id LIMIT %s OFFSET %s
            """, (artist_id, limit, offset))
            songs = await cur.fetchall()
    return {
        "artist": encode_artist(artist),
        "aliases": [encode_alias(row) for row in aliases],
        "songs": [encode_song(row) for row in songs],
        "total": total, "offset": offset, "limit": limit,
    }


@app.get("/api/admin/songs/{song_id}")
async def song_detail(song_id: int, request: Request, token_hash: str = Depends(auth)):
    async with request.app.state.pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
              SELECT id,title,primary_artist_id,release_year,release_month,release_day,release_precision,updated_at
              FROM songs WHERE id=%s
            """, (song_id,))
            song = await cur.fetchone()
            if not song:
                raise HTTPException(404, "楽曲が見つかりません")
            await cur.execute("""
              SELECT id,kind,value,verification,source_url,checked_at FROM song_names
              WHERE song_id=%s ORDER BY kind,id LIMIT 100
            """, (song_id,))
            names = await cur.fetchall()
    return {"song": {**encode_song(song), "artistId": song["primary_artist_id"]},
            "aliases": [encode_alias(row) for row in names]}


class ArtistUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    version: datetime

    @field_validator("name")
    @classmethod
    def trimmed_name(cls, value: str):
        if not value.strip():
            raise ValueError("アーティスト名が空です")
        return value.strip()


class ArtistResearchUpdate(BaseModel):
    version: datetime
    lastResearchedOn: date | None

    @field_validator("lastResearchedOn")
    @classmethod
    def reject_future_research_date(cls, value: date | None):
        if value and (value < date(1980, 1, 1) or value > datetime.now(timezone(timedelta(hours=9))).date()):
            raise ValueError("最終調査日は1980年以降の実際に調査した日付を指定してください")
        return value


class SongUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    version: datetime
    releasePrecision: Literal["unknown", "year", "month", "day"] = "unknown"
    releaseYear: int | None = Field(default=None, ge=1850, le=2100)
    releaseMonth: int | None = Field(default=None, ge=1, le=12)
    releaseDay: int | None = Field(default=None, ge=1, le=31)
    releaseSourceUrl: str | None = None

    @model_validator(mode="after")
    def date_consistency(self):
        if not self.title.strip():
            raise ValueError("曲名が空です")
        p = self.releasePrecision
        y, m, d = self.releaseYear, self.releaseMonth, self.releaseDay
        if (p == "unknown" and any(v is not None for v in (y, m, d))) or (
            p == "year" and (y is None or m is not None or d is not None)
        ) or (p == "month" and (y is None or m is None or d is not None)) or (
            p == "day" and (y is None or m is None or d is None)
        ):
            raise ValueError("発売日の精度と年月日が一致しません")
        if p == "day":
            date(y, m, d)
        elif p == "month":
            date(y, m, 1)
        if self.releaseSourceUrl:
            clean_url(self.releaseSourceUrl)
        return self


class AliasUpdate(BaseModel):
    side: Literal["artist", "song"]
    entityId: int = Field(gt=0)
    kind: Literal["hiragana", "katakana", "romaji", "english"]
    value: str = Field(min_length=1, max_length=300)
    sourceUrl: str | None = Field(default=None, max_length=600)
    oldId: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_alias(self):
        if not self.value.strip():
            raise ValueError("表記が空です")
        if self.sourceUrl:
            clean_url(self.sourceUrl)
        return self


async def audit(cur, action, kind, entity_id, before, after):
    from psycopg.types.json import Jsonb
    await cur.execute("""
      INSERT INTO ken_admin_audit(action,entity_type,entity_id,before_json,after_json,actor)
      VALUES (%s,%s,%s,%s,%s,'admin')
    """, (action, kind, entity_id, Jsonb(before), Jsonb(after)))


@app.post("/api/admin/artists/{artist_id}")
async def update_artist(artist_id: int, body: ArtistUpdate, request: Request, token_hash: str = Depends(auth)):
    try:
        async with request.app.state.pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    await cur.execute("SELECT id,name,name_key,updated_at FROM artists WHERE id=%s FOR UPDATE", (artist_id,))
                    before = await cur.fetchone()
                    if not before:
                        raise HTTPException(404, "アーティストが見つかりません")
                    if before["updated_at"] != body.version:
                        raise HTTPException(409, "ほかの編集が先に保存されました。再読み込みしてください")
                    key = normalized(body.name)
                    if not key:
                        raise HTTPException(422, "アーティスト名が空です")
                    await cur.execute("""
                      UPDATE artists SET name=%s,name_key=%s,identity_status='human_confirmed',updated_at=now()
                      WHERE id=%s RETURNING id,name,updated_at,last_researched_on
                    """, (body.name, key, artist_id))
                    after = await cur.fetchone()
                    await audit(cur, "artist_update", "artist", artist_id,
                                {"name": before["name"]}, {"name": after["name"]})
    except UniqueViolation:
        raise HTTPException(409, "同じ名前のアーティストが既にあります。統合作業が必要です")
    return {"artist": encode_artist(after)}


@app.post("/api/admin/artists/{artist_id}/research")
async def update_artist_research(
    artist_id: int, body: ArtistResearchUpdate, request: Request, token_hash: str = Depends(auth)
):
    async with request.app.state.pool.connection() as conn:
        async with conn.transaction():
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id,name,updated_at,last_researched_on FROM artists WHERE id=%s FOR UPDATE",
                    (artist_id,),
                )
                before = await cur.fetchone()
                if not before:
                    raise HTTPException(404, "アーティストが見つかりません")
                if before["updated_at"] != body.version:
                    raise HTTPException(409, "ほかの編集が先に保存されました。再読み込みしてください")
                await cur.execute("""
                    UPDATE artists SET last_researched_on=%s,updated_at=now()
                    WHERE id=%s RETURNING id,name,updated_at,last_researched_on
                """, (body.lastResearchedOn, artist_id))
                after = await cur.fetchone()
                await audit(cur, "artist_research_date_update", "artist", artist_id,
                            {"lastResearchedOn": as_iso(before["last_researched_on"])},
                            {"lastResearchedOn": as_iso(after["last_researched_on"])})
    return {"artist": encode_artist(after)}


@app.post("/api/admin/songs/{song_id}")
async def update_song(song_id: int, body: SongUpdate, request: Request, token_hash: str = Depends(auth)):
    try:
        async with request.app.state.pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    await cur.execute("""
                      SELECT id,title,title_key,primary_artist_id,release_year,release_month,release_day,
                             release_precision,updated_at FROM songs WHERE id=%s FOR UPDATE
                    """, (song_id,))
                    before = await cur.fetchone()
                    if not before:
                        raise HTTPException(404, "楽曲が見つかりません")
                    if before["updated_at"] != body.version:
                        raise HTTPException(409, "ほかの編集が先に保存されました。再読み込みしてください")
                    key = normalized(body.title)
                    if not key:
                        raise HTTPException(422, "曲名が空です")
                    source_id = None
                    if body.releaseSourceUrl and body.releasePrecision != "unknown":
                        await cur.execute("SELECT id FROM source_catalogs WHERE code='ken_admin_manual'")
                        source = await cur.fetchone()
                        if not source:
                            raise HTTPException(503, "管理データソース未設定です")
                        source_id = source["id"]
                    await cur.execute("""
                      UPDATE songs SET title=%s,title_key=%s,release_year=%s,release_month=%s,
                        release_day=%s,release_precision=%s,release_source_id=%s,
                        identity_status='human_confirmed',updated_at=now()
                      WHERE id=%s
                      RETURNING id,title,release_year,release_month,release_day,release_precision,updated_at
                    """, (body.title.strip(), key, body.releaseYear, body.releaseMonth, body.releaseDay,
                          body.releasePrecision, source_id, song_id))
                    after = await cur.fetchone()
                    before_data = {k: before[k] for k in ("title","release_year","release_month","release_day","release_precision")}
                    after_data = {k: after[k] for k in ("title","release_year","release_month","release_day","release_precision")}
                    if body.releaseSourceUrl and body.releasePrecision != "unknown":
                        await cur.execute("""
                           INSERT INTO release_evidence(song_id,source_id,release_year,release_month,
                             release_day,precision,reference_url)
                           VALUES (%s,%s,%s,%s,%s,%s,%s)
                        """, (song_id, source_id,body.releaseYear,body.releaseMonth,body.releaseDay,
                              body.releasePrecision,clean_url(body.releaseSourceUrl)))
                    await audit(cur,"song_update","song",song_id,before_data,after_data)
    except UniqueViolation:
        raise HTTPException(409, "同じアーティストに同名曲が存在します")
    return {"song": encode_song(after)}


@app.post("/api/admin/aliases")
async def upsert_alias(body: AliasUpdate, request: Request, token_hash: str = Depends(auth)):
    table = "artist_names" if body.side == "artist" else "song_names"
    id_col = "artist_id" if body.side == "artist" else "song_id"
    owner_table = "artists" if body.side == "artist" else "songs"
    name = body.value.strip()
    key = normalized(name)
    if not key:
        raise HTTPException(422, "表記が空です")
    try:
        async with request.app.state.pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    await cur.execute(f"SELECT id FROM {owner_table} WHERE id=%s", (body.entityId,))
                    if not await cur.fetchone():
                        raise HTTPException(404, "編集対象が存在しません")
                    previous = {}
                    if body.oldId:
                        await cur.execute(
                            f"SELECT id,kind,value,source_url FROM {table} WHERE id=%s AND {id_col}=%s FOR UPDATE",
                            (body.oldId, body.entityId))
                        existing = await cur.fetchone()
                        if not existing:
                            raise HTTPException(404, "編集対象の表記が見つかりません")
                        previous = dict(existing)
                    source = clean_url(body.sourceUrl)
                    if body.oldId:
                        await cur.execute(f"""
                          UPDATE {table} SET kind=%s,value=%s,search_key=%s,
                            verification='human_confirmed',reviewed_by='admin',
                            checked_at=now(),source_url=%s
                          WHERE id=%s AND {id_col}=%s
                          RETURNING id,kind,value,verification,source_url,checked_at
                        """, (body.kind,name,key,source,body.oldId,body.entityId))
                    else:
                        await cur.execute(f"""
                          INSERT INTO {table} ({id_col},kind,value,search_key,verification,reviewed_by,checked_at,source_url)
                          VALUES (%s,%s,%s,%s,'human_confirmed','admin',now(),%s)
                          RETURNING id,kind,value,verification,source_url,checked_at
                        """, (body.entityId,body.kind,name,key,source))
                    after = await cur.fetchone()
                    before_record = {k:v for k,v in previous.items() if k in ("kind","value","source_url")}
                    await audit(cur, "artist_alias_upsert" if body.side=="artist" else "song_alias_upsert",
                                body.side,body.entityId,before_record,
                                {"kind":after["kind"],"value":after["value"],"sourceUrl":source})
    except UniqueViolation:
        raise HTTPException(409, "同じ表記がすでに登録されています")
    return {"alias": encode_alias(after)}


@app.get("/api/admin/audit")
async def get_audit(
    request: Request, entityType: Literal["artist","song"], entityId: int = Query(gt=0),
    token_hash: str = Depends(auth),
):
    async with request.app.state.pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
              SELECT id,action,before_json,after_json,changed_at
              FROM ken_admin_audit WHERE entity_type=%s AND entity_id=%s
              ORDER BY changed_at DESC LIMIT 30
            """, (entityType, entityId))
            rows = await cur.fetchall()
    return {"items":[{
        "id":row["id"],"action":row["action"],
        "before":row["before_json"],"after":row["after_json"],
        "changedAt":as_iso(row["changed_at"]),
    } for row in rows]}
