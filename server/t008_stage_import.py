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

from server.t008_policy import SourcePolicy, acquisition_allowed

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
    # Staging needs lawful automated access + storage, not public redistribution.
    check_disposable(conn)
    counts = {"inserted": 0, "duplicate": 0, "collision": 0, "rejected": 0}
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("""SELECT id, content_license,access_terms,allowed_fields,
                automated_access_allowed,storage_allowed,publication_allowed,
                reviewed_at,expires_at
                FROM t008_source_policies
                WHERE source_code=%s AND acquisition_method=%s
                ORDER BY policy_version DESC LIMIT 1""",
                (policy.source_code, policy.method))
            row = cur.fetchone()
            if row is None:
                raise PermissionError("T008 source policy must be provisioned by an administrator")
            policy_id = row[0]
            dbpolicy = SourcePolicy(policy.source_code,policy.method,row[1],row[2],
                frozenset(row[3]),row[4],row[5],row[6],True,row[7],row[8])
            if dbpolicy != policy or not acquisition_allowed(dbpolicy,policy.method,
                                                             {"title","artist"},now):
                raise PermissionError("T008 stored policy differs from supplied policy")
            cur.execute("INSERT INTO t008_batches(id) VALUES (%s) ON CONFLICT DO NOTHING",
                        (batch_id,))
            for i, c in enumerate(candidates):
                if fail_after is not None and i >= fail_after:
                    raise RuntimeError("Synthetic injected batch failure")
                if not c.title.strip() or not c.artist.strip() or not c.source_id.strip():
                    counts["rejected"] += 1
                    continue
                if c.entity_type not in ("work","recording","release"):
                    counts["rejected"] += 1
                    continue
                digest = fingerprint(c)
                cur.execute("""SELECT candidate_id FROM t008_intake_events
                    WHERE batch_id=%s AND input_digest=%s""", (batch_id,digest))
                if cur.fetchone():
                    counts["duplicate"] += 1
                    continue
                cur.execute("""SELECT candidate_id,input_digest FROM t008_external_claims
                    WHERE source_code=%s AND entity_type=%s AND external_id=%s
                    FOR UPDATE""",(policy.source_code,c.entity_type,c.source_id))
                claim = cur.fetchone()
                if claim and claim[1] == digest:
                    cur.execute("""INSERT INTO t008_intake_events
                         (batch_id,input_digest,source_code,entity_type,external_id,
                          title,artist,outcome,candidate_id)
                         VALUES(%s,%s,%s,%s,%s,%s,%s,'duplicate',%s)""",
                         (batch_id,digest,policy.source_code,c.entity_type,c.source_id,
                          c.title,c.artist,claim[0]))
                    counts["duplicate"] += 1
                    continue
                outcome = "collision" if claim else "new"
                cid = uuid.uuid5(NAMESPACE, f"{batch_id}/{digest}")
                cur.execute("""INSERT INTO t008_candidates
                   (id,batch_id,title,artist,title_key,artist_key,
                    external_source,external_entity_type,external_id,input_digest,
                    verification)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (id) DO NOTHING RETURNING id""",
                    (cid,batch_id,c.title,c.artist,c.title.casefold(),c.artist.casefold(),
                     policy.source_code,c.entity_type,c.source_id,digest,
                     "review" if claim else "unverified"))
                if not cur.fetchone():
                    raise RuntimeError("T008 unexpected candidate ID collision")
                if not claim:
                    cur.execute("""INSERT INTO t008_external_claims
                       (source_code,entity_type,external_id,candidate_id,input_digest)
                       VALUES(%s,%s,%s,%s,%s)""",
                       (policy.source_code,c.entity_type,c.source_id,cid,digest))
                else:
                    counts["collision"] += 1
                    cur.execute("""INSERT INTO t008_review_queue(candidate_id,reason)
                      VALUES(%s,%s)""", (cid,"external_id_content_conflict"))
                cur.execute("""INSERT INTO t008_intake_events
                   (batch_id,input_digest,source_code,entity_type,external_id,
                    title,artist,outcome,candidate_id)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                   (batch_id,digest,policy.source_code,c.entity_type,c.source_id,
                    c.title,c.artist,outcome,cid))
                counts["inserted"] += 1
                for field_name, value in (("title",c.title),("artist",c.artist)):
                    original_hash = hashlib.sha256(value.encode("utf-8")).hexdigest()
                    cur.execute("""INSERT INTO t008_evidence
                        (candidate_id,field_name,source_code,source_record_id,acquisition_method,
                         original_data_hash,source_policy_id)
                         VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                        (cid,field_name,policy.source_code,c.source_id,policy.method,
                         original_hash,policy_id))
            cur.execute("SELECT t008_stage_audit(%s,%s::jsonb)",(batch_id,json.dumps(counts)))
    return counts
