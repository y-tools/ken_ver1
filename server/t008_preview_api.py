"""Isolated, test-only read path for T008 publication-visibility gate.

Never mount this preview endpoint on the existing production Denmok app.
It connects with a dedicated non-owner PostgreSQL account that can SELECT
only t008_visible_publications (not raw publication/identity tables).
"""
from fastapi import FastAPI, HTTPException, Query
import psycopg

def create_preview_app(dsn: str) -> FastAPI:
    if not dsn:
        raise ValueError("T008 search DSN required")
    app = FastAPI(title="T008 isolated search-gate verification", docs_url=None, redoc_url=None)
    @app.get("/t008/isolated-preview/search")
    def search(q: str = Query(min_length=1, max_length=80)):
        try:
            with psycopg.connect(dsn, connect_timeout=4) as con:
                with con.transaction():
                    with con.cursor() as cur:
                        cur.execute("SET TRANSACTION READ ONLY")
                        cur.execute("SET LOCAL statement_timeout='2500ms'")
                        cur.execute("SELECT session_user")
                        if cur.fetchone()[0] != "t008_search_login":
                            raise RuntimeError("T008 requires distinct least-privilege search login")
                        cur.execute(
                            """SELECT candidate_id::text,title,artist
                               FROM t008_visible_publications
                               WHERE title ILIKE %s OR artist ILIKE %s
                               ORDER BY title,candidate_id LIMIT 10""",
                            (f"%{q}%", f"%{q}%")
                        )
                        items=[{"candidate_id":cid,"title":title,"artist":artist}
                               for cid,title,artist in cur.fetchall()]
            return {"items":items}
        except Exception:
            # Do not leak credentials, hostnames, SQL or song data in HTTP errors.
            raise HTTPException(status_code=503, detail="Preview temporarily unavailable")
    return app
