"""T008 synthetic staging importer. NEVER uses legacy tables or production DB.

Requires a disposable database whose name is exactly ken_test or t008_test.
No network acquisition; the provided policy is evaluated before any INSERT.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from server.t008_policy import SourcePolicy, acquisition_allowed, publication_allowed

ALLOWED_TEST_DB_NAMES = {"ken_test", "t008_test"}
NAMESPACE = uuid.UUID("d2d383a0-704d-4cf8-814a-9b7a85c77c05")

@dataclass(frozen=True)
class Candidate:
    title: str
    artist: str
    source_id: str
    entity_type: str = "recording"

def fingerprint(candidate: Candidate) -> str:
    return hashlib.sha256(json.dumps(
        [candidate.title, candidate.artist, candidate.source_id, candidate.entity_type],
        ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()

def check_disposable(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT current_database(), current_setting('transaction_read_only')")
        name, readonly = cur.fetchone()
        if name not in ALLOWED_TEST_DB_NAMES or readonly == "on":
            raise RuntimeError("T008 refuses a non-test or read-only database")
        cur.execute("SELECT to_regclass('public.t008_candidates'), to_regclass('public.songs')")
        staging, legacy = cur.fetchone()
        if staging is None:
            raise RuntimeError("T008 staging schema is not installed")
        # Independent staging schema is allowed alongside a legacy schema in test DB.
    return True

def stage_candidates(conn, batch_id: uuid.UUID, candidates: Iterable[Candidate],
                     policy: SourcePolicy, now: datetime | None = None,
                     fail_after: int | None = None) -> dict[str, int]:
    now = now or datetime.now(timezone.utc)
    if not acquisition_allowed(policy, policy.method, {"title", "artist"}, now):
        raise PermissionError("T008 acquisition blocked by unreviewed/expired rights")
    if not publication_allowed(policy, policy.method, {"title", "artist"},
                               {"title", "artist"}, True, now):
        raise PermissionError("T008 staging source lacks publication authorization")
    check_disposable(conn)
    counts = {"inserted": 0, "duplicate": 0, "rejected": 0}
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO t008_source_policies
                (source_code,acquisition_method,content_license,access_terms,allowed_fields,
                 automated_access_allowed,storage_allowed,publication_allowed,reviewed_at,expires_at)
                VALUES (%s,%s,%s,%s,%s,true,true,true,%s,%s)
                ON CONFLICT (source_code,acquisition_method)
                DO UPDATE SET content_license=EXCLUDED.content_license,
                 access_terms=EXCLUDED.access_terms,allowed_fields=EXCLUDED.allowed_fields,
                 reviewed_at=EXCLUDED.reviewed_at,expires_at=EXCLUDED.expires_at
                RETURNING id""",
                (policy.source_code,policy.method,policy.content_license,policy.access_terms,
                 list(policy.allowed_fields),policy.reviewed_at,policy.expires_at))
            policy_id = cur.fetchone()[0]
            cur.execute("INSERT INTO t008_batches(id) VALUES (%s) ON CONFLICT DO NOTHING",
                        (batch_id,))
            for i, c in enumerate(candidates):
                if fail_after is not None and i >= fail_after:
                    raise RuntimeError("Synthetic injected batch failure")
                if not c.title.strip() or not c.artist.strip() or not c.source_id.strip():
                    counts["rejected"] += 1
                    continue
                digest = fingerprint(c)
                cid = uuid.uuid5(NAMESPACE, f"{batch_id}/{digest}")
                cur.execute("""INSERT INTO t008_candidates
                   (id,batch_id,title,artist,title_key,artist_key,
                    external_source,external_entity_type,external_id,input_digest)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT DO NOTHING RETURNING id""",
                    (cid,batch_id,c.title,c.artist,c.title.casefold(),c.artist.casefold(),
                     policy.source_code,c.entity_type,c.source_id,digest))
                if not cur.fetchone():
                    counts["duplicate"] += 1
                    continue
                counts["inserted"] += 1
                for field_name, value in (("title",c.title),("artist",c.artist)):
                    original_hash = hashlib.sha256(value.encode("utf-8")).hexdigest()
                    cur.execute("""INSERT INTO t008_evidence
                        (candidate_id,field_name,source_code,source_record_id,acquisition_method,
                         original_data_hash,source_policy_id)
                         VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                        (cid,field_name,policy.source_code,c.source_id,policy.method,
                         original_hash,policy_id))
            cur.execute("INSERT INTO t008_audit(batch_id,action,details) VALUES (%s,%s,%s::jsonb)",
                        (batch_id,"staged",json.dumps(counts)))
    return counts
