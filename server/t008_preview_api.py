"""Isolated, disposable-only, rights-gated T008 HTTP verification endpoint.

NOT wired into the existing Denmok public API or any production deployment.
A dedicated least-privilege DB login may read ONLY the rights-filtered view.
"""
from fastapi import FastAPI, HTTPException, Query
import psycopg

NO_STORE = "private, no-store, no-cache, max-age=0, must-revalidate"

def create_preview_app(dsn: str) -> FastAPI:
    if not dsn:
        raise ValueError("T008 search DSN required")
    app = FastAPI(title="T008 isolated search-gate verification", docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def forbid_http_cache(request, call_next):
        # Applies to successes AND failures, including validation errors.
        # Proxy/CDN and service-worker policies still require separate review.
        response = await call_next(request)
        response.headers["Cache-Control"] = NO_STORE
        response.headers["Surrogate-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    @app.get("/t008/isolated-preview/search")
    def search(q: str = Query(min_length=1, max_length=80)):
        try:
            with psycopg.connect(dsn, connect_timeout=4) as con:
                with con.transaction():
                    with con.cursor() as cur:
                        # Fresh READ COMMITTED snapshot for EACH short-lived request.
                        # REPEATABLE READ / SERIALIZABLE can retain old license versions.
                        cur.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED READ ONLY")
                        cur.execute("SET LOCAL statement_timeout='2500ms'")
                        cur.execute("SELECT session_user, current_setting('transaction_isolation')")
                        identity, isolation = cur.fetchone()
                        if identity != "t008_search_login" or isolation != "read committed":
                            raise RuntimeError("T008 viewer requires an isolated READ COMMITTED account")
                        cur.execute(
                            """SELECT candidate_id::text,title,artist
                               FROM t008_visible_publications
                               WHERE title ILIKE %s OR artist ILIKE %s
                               ORDER BY title,candidate_id LIMIT 10""",
                            (f"%{q}%", f"%{q}%"),
                        )
                        items = [{"candidate_id": cid, "title": title, "artist": artist}
                                 for cid,title,artist in cur.fetchall()]
            return {"items": items}
        except Exception:
            # Do not disclose SQL, usernames, hostnames or credentials in HTTP errors.
            raise HTTPException(status_code=503, detail="Preview temporarily unavailable")

    return app
