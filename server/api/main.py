"""Ken Denmoku read-only song search API.

GitHub Pages remains a static client. PostgreSQL runs privately on the user's
VPS. Put this service behind TLS and nginx rate limiting; never publish port
5432 or credentials. See server/README.md for operational prerequisites.
"""
from __future__ import annotations

import os
import re
import unicodedata
from contextlib import asynccontextmanager
from datetime import date
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
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
    allow_methods=["GET"],
    allow_headers=["Accept", "Content-Type"],
    allow_credentials=False,
    max_age=1800,
)

# IDs are not sequential public data paths; API exposes only read-only search.
SEARCH_TITLE = """
WITH matched AS (
 SELECT id AS song_id, 0 AS priority FROM songs WHERE title_key LIKE %s
 UNION ALL
 SELECT song_id, CASE WHEN verification IN ('source_confirmed','human_confirmed')
                       THEN 1 ELSE 2 END AS priority
 FROM song_names WHERE search_key LIKE %s
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
 SELECT id AS artist_id, 0 AS priority FROM artists WHERE name_key LIKE %s
 UNION ALL
 SELECT artist_id, CASE WHEN verification IN ('source_confirmed','human_confirmed')
                        THEN 1 ELSE 2 END AS priority
 FROM artist_names WHERE search_key LIKE %s
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
    pattern = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    statement = (SEARCH_ARTIST if mode == "artist" else SEARCH_TITLE).replace(
        "LIKE %s", "LIKE %s ESCAPE '\\\\'"
    )
    try:
        async with request.app.state.pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    await cur.execute("SET LOCAL statement_timeout = '2500ms'")
                    await cur.execute("SET LOCAL default_transaction_read_only = on")
                    await cur.execute(statement, (pattern, pattern, limit))
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
