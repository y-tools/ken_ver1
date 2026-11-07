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
    with conn.cursor() as cur:
        cur.execute("""SELECT id,content_license,access_terms,allowed_fields,
                      automated_access_allowed,storage_allowed,publication_allowed,
                      reviewed_at,expires_at,policy_version
                      FROM t008_source_policies
                      WHERE source_code=%s AND acquisition_method=%s
                      ORDER BY policy_version DESC LIMIT 1""",
                    (policy.source_code,policy.method))
        row=cur.fetchone()
        if row is None:
            raise PermissionError("T008 source policy is not provisioned")
        policy_id=row[0]
        stored=SourcePolicy(policy.source_code,policy.method,row[1],row[2],
                frozenset(row[3]),row[4],row[5],row[6],True,row[7],row[8],row[9])
        if stored != policy or not acquisition_allowed(stored,policy.method,{"title","artist"},now):
            raise PermissionError("T008 source policy is invalid, stale or differs")
    counts = {"inserted": 0, "duplicate": 0, "collision": 0, "rejected": 0}
    # The database function owns and serializes the missing-claim case.
    # Hashes identify (1) logical content and (2) a source+method+policy intake event.
    # Sorted records prevent lock-order cycles for concurrent multi-record batches.
    prepared = []
    for c in candidates:
        if not c.title.strip() or not c.artist.strip() or not c.source_id.strip() or c.entity_type not in ("work","recording","release"):
            counts["rejected"] += 1
            continue
        content_digest = fingerprint(c)
        event_digest = hashlib.sha256(json.dumps(
            [policy.source_code,policy.method,policy_id,content_digest],
            separators=(",",":")).encode("utf-8")).hexdigest()
        prepared.append((c,content_digest,event_digest))
    prepared.sort(key=lambda entry:(policy.source_code,entry[0].entity_type,
                      entry[0].source_id,entry[2]))
    with conn.transaction():
        with conn.cursor() as cur:
            for i,(c,content_digest,event_digest) in enumerate(prepared):
                if fail_after is not None and i >= fail_after:
                    raise RuntimeError("Synthetic injected batch failure")
                cur.execute("""SELECT t008_stage_one(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (batch_id,c.title,c.artist,policy.source_code,c.entity_type,
                     c.source_id,policy_id,content_digest,event_digest))
                result = cur.fetchone()[0]
                if result in ("new","collision"):
                    counts["inserted"] += 1
                if result == "collision":
                    counts["collision"] += 1
                if result == "duplicate":
                    counts["duplicate"] += 1
            cur.execute("SELECT t008_stage_audit(%s,%s::jsonb)",(batch_id,json.dumps(counts)))
    return counts
