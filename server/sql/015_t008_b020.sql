-- T008 B-020, disposable PostgreSQL 16 ONLY.
BEGIN;
DO $$BEGIN IF current_database() NOT IN ('ken_test','t008_test') THEN RAISE EXCEPTION 'T008 disposable only'; END IF; END$$;
-- Upgrade populated 014 schemas without losing preview IDs/history. Reject corrupt
-- preexisting non-null keys instead of silently rewriting them.
DO $$BEGIN
 IF EXISTS(
   SELECT 1 FROM t008_publication_preview p
   LEFT JOIN t008_candidates c ON c.id=p.candidate_id
   WHERE c.id IS NULL OR
     (p.source_code IS NOT NULL AND p.source_code IS DISTINCT FROM c.external_source) OR
     (p.entity_type IS NOT NULL AND p.entity_type IS DISTINCT FROM c.external_entity_type) OR
     (p.external_id IS NOT NULL AND p.external_id IS DISTINCT FROM c.external_id)
 ) THEN RAISE EXCEPTION 'T008 preview key mismatch: manual reconciliation required'; END IF;
END$$;
UPDATE t008_publication_preview p
 SET source_code=c.external_source,
     entity_type=c.external_entity_type,
     external_id=c.external_id
 FROM t008_candidates c WHERE p.candidate_id=c.id
 AND (p.source_code IS NULL OR p.entity_type IS NULL OR p.external_id IS NULL);
ALTER TABLE t008_publication_preview ALTER COLUMN source_code SET NOT NULL,
 ALTER COLUMN entity_type SET NOT NULL, ALTER COLUMN external_id SET NOT NULL;
ALTER TABLE t008_candidates ADD CONSTRAINT t008_candidate_external_tuple UNIQUE
 (id,external_source,external_entity_type,external_id);
ALTER TABLE t008_publication_preview ADD CONSTRAINT t008_preview_identity_fk
 FOREIGN KEY(candidate_id,source_code,entity_type,external_id)
 REFERENCES t008_candidates(id,external_source,external_entity_type,external_id);
ALTER TABLE t008_active_publications ADD CONSTRAINT t008_active_identity_fk
 FOREIGN KEY(candidate_id,source_code,entity_type,external_id)
 REFERENCES t008_candidates(id,external_source,external_entity_type,external_id);
ALTER TABLE t008_evidence ADD CONSTRAINT t008_evidence_candidate_tuple UNIQUE(candidate_id,id);
ALTER TABLE t008_identity_decisions ADD CONSTRAINT t008_title_belongs_to_candidate
 FOREIGN KEY(candidate_id,title_evidence_id) REFERENCES t008_evidence(candidate_id,id);
ALTER TABLE t008_identity_decisions ADD CONSTRAINT t008_artist_belongs_to_candidate
 FOREIGN KEY(candidate_id,artist_evidence_id) REFERENCES t008_evidence(candidate_id,id);
ALTER TABLE t008_identity_decisions ADD COLUMN title_digest TEXT NOT NULL DEFAULT '',
 ADD COLUMN artist_digest TEXT NOT NULL DEFAULT '';
CREATE OR REPLACE FUNCTION t008_evidence_snapshot(p_id BIGINT)
RETURNS TEXT LANGUAGE sql STABLE SET search_path=pg_catalog,public AS $$
 SELECT encode(sha256(convert_to(row_to_json(e)::text,'UTF8')),'hex') FROM t008_evidence e WHERE id=p_id
$$;
CREATE OR REPLACE FUNCTION t008_identity_decide(p_candidate UUID,p_compared UUID,
 p_title BIGINT,p_artist BIGINT,p_decision TEXT,p_reason TEXT)
RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE c t008_candidates%ROWTYPE; other t008_candidates%ROWTYPE; reviewer TEXT;
BEGIN
 reviewer:=t008_reviewer_id();
 IF p_decision NOT IN ('same_recording','distinct_recording')
 OR length(btrim(coalesce(p_reason,'')))<10 THEN
 RAISE EXCEPTION 'T008 explicit decision and explanation required'; END IF;
 SELECT * INTO STRICT c FROM t008_candidates WHERE id=p_candidate;
 SELECT * INTO STRICT other FROM t008_candidates WHERE id=p_compared;
 IF c.external_source IS DISTINCT FROM other.external_source
 OR c.external_entity_type IS DISTINCT FROM other.external_entity_type
 OR c.external_id IS DISTINCT FROM other.external_id THEN
 RAISE EXCEPTION 'T008 identity decision requires the same external key'; END IF;
 -- Identity decisions share the external-key lock used by stage/publish/revoke.
 PERFORM pg_advisory_xact_lock(hashtextextended(
 't008:claim:'||c.external_source||':'||c.external_entity_type||':'||c.external_id,0));
 -- Lock two candidate rows in deterministic order.
 PERFORM 1 FROM t008_candidates WHERE id IN(p_candidate,p_compared) ORDER BY id FOR UPDATE;
 IF EXISTS(SELECT 1 FROM t008_publication_preview WHERE candidate_id=p_candidate)
 THEN RAISE EXCEPTION 'T008 published candidate cannot be re-adjudicated'; END IF;
 IF NOT EXISTS(SELECT 1 FROM t008_evidence WHERE id=p_title AND candidate_id=p_candidate
  AND field_name='title' AND verification='verified')
 OR NOT EXISTS(SELECT 1 FROM t008_evidence WHERE id=p_artist AND candidate_id=p_candidate
  AND field_name='artist' AND verification='verified')
 THEN RAISE EXCEPTION 'T008 individually verified field evidence required'; END IF;
 INSERT INTO t008_identity_decisions(candidate_id,compared_candidate_id,title_evidence_id,
  artist_evidence_id,decision,reviewer_id,rationale,title_digest,artist_digest)
 VALUES(p_candidate,p_compared,p_title,p_artist,p_decision,reviewer,p_reason,
 t008_evidence_snapshot(p_title),t008_evidence_snapshot(p_artist));
 INSERT INTO t008_audit(batch_id,action,details)
 VALUES(c.batch_id,'identity_decision',jsonb_build_object('candidate_id',p_candidate,
   'compared_candidate_id',p_compared,'decision',p_decision,'reviewer_id',reviewer,
   'title_evidence_id',p_title,'artist_evidence_id',p_artist,'reason',p_reason));
END $$;


-- Public visibility never relies on a cached boolean: consult newest policy on EACH read.
-- Historical active pointer may remain until reconciled, but search-visible rows disappear immediately.
CREATE OR REPLACE VIEW t008_visible_publications AS
SELECT a.source_code,a.entity_type,a.external_id,a.candidate_id,p.title,p.artist
FROM t008_active_publications a
JOIN t008_publication_preview p ON p.candidate_id=a.candidate_id
WHERE p.state='published'
 AND p.source_code=a.source_code AND p.entity_type=a.entity_type AND p.external_id=a.external_id
 AND EXISTS(SELECT 1 FROM t008_evidence e WHERE e.candidate_id=a.candidate_id)
 AND NOT EXISTS(
  SELECT 1 FROM (SELECT DISTINCT e.source_code,e.acquisition_method FROM t008_evidence e
  WHERE e.candidate_id=a.candidate_id) x
  WHERE NOT EXISTS(
   SELECT 1 FROM t008_source_policies pol
   WHERE pol.source_code=x.source_code AND pol.acquisition_method=x.acquisition_method
   AND pol.policy_version=(SELECT max(z.policy_version) FROM t008_source_policies z
    WHERE z.source_code=x.source_code AND z.acquisition_method=x.acquisition_method)
   AND pol.publication_allowed IS TRUE
   AND t008_policy_storage_ok(pol.id,pol.source_code,pol.acquisition_method)
   AND EXISTS(SELECT 1 FROM t008_evidence t WHERE t.candidate_id=a.candidate_id
    AND t.source_policy_id=pol.id AND t.field_name='title' AND t.verification='verified')
   AND EXISTS(SELECT 1 FROM t008_evidence t WHERE t.candidate_id=a.candidate_id
    AND t.source_policy_id=pol.id AND t.field_name='artist' AND t.verification='verified')
  )
 );
REVOKE ALL ON t008_visible_publications FROM PUBLIC;
-- Restrict direct access to the publication pointer; no public API wired yet.
CREATE OR REPLACE FUNCTION t008_reconcile_visibility(p_candidate UUID)
RETURNS TEXT LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE c t008_candidates%ROWTYPE; active_id UUID;
BEGIN
 SELECT * INTO STRICT c FROM t008_candidates WHERE id=p_candidate;
 PERFORM pg_advisory_xact_lock(hashtextextended(
 't008:claim:'||c.external_source||':'||c.external_entity_type||':'||c.external_id,0));
 PERFORM 1 FROM t008_candidates WHERE id=p_candidate FOR UPDATE;
 SELECT candidate_id INTO active_id FROM t008_active_publications WHERE
 source_code=c.external_source AND entity_type=c.external_entity_type
 AND external_id=c.external_id FOR UPDATE;
 IF active_id IS DISTINCT FROM p_candidate THEN RETURN 'not_active'; END IF;
 IF EXISTS(SELECT 1 FROM t008_visible_publications WHERE candidate_id=p_candidate)
 THEN RETURN 'visible'; END IF;
 DELETE FROM t008_active_publications WHERE source_code=c.external_source
 AND entity_type=c.external_entity_type AND external_id=c.external_id;
 UPDATE t008_publication_preview SET state='revoked',revoked_at=now()
 WHERE candidate_id=p_candidate AND state='published';
 INSERT INTO t008_publication_history(source_code,entity_type,external_id,candidate_id,
 preceding_id,action,actor) VALUES(c.external_source,c.external_entity_type,c.external_id,
 p_candidate,p_candidate,'revoke',t008_actor());
 INSERT INTO t008_audit(batch_id,action,details) VALUES(c.batch_id,'license_visibility_revoked',
 jsonb_build_object('candidate_id',p_candidate,'actor',t008_actor()));
 RETURN 'revoked';
END $$;
CREATE OR REPLACE FUNCTION t008_publish_preview(p_candidate UUID,p_fail BOOLEAN DEFAULT FALSE)
RETURNS TEXT LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE c t008_candidates%ROWTYPE; active t008_active_publications%ROWTYPE;
 approval t008_approval_revisions%ROWTYPE; d t008_identity_decisions%ROWTYPE;
 previous UUID; preview_state TEXT; lineage_ok BOOLEAN;
BEGIN
 SELECT * INTO STRICT c FROM t008_candidates WHERE id=p_candidate;
 -- Common ordering for stage/publish/revoke: external advisory -> candidate -> policy.
 PERFORM pg_advisory_xact_lock(hashtextextended(
 't008:claim:'||c.external_source||':'||c.external_entity_type||':'||c.external_id,0));
 SELECT * INTO STRICT c FROM t008_candidates WHERE id=p_candidate FOR UPDATE;
 SELECT * INTO active FROM t008_active_publications WHERE source_code=c.external_source
 AND entity_type=c.external_entity_type AND external_id=c.external_id FOR UPDATE;
 previous:=active.candidate_id;
 IF previous IS NOT NULL AND previous<>p_candidate THEN
  PERFORM 1 FROM t008_candidates WHERE id=previous FOR UPDATE;
 END IF;
 PERFORM t008_lock_candidate_sources(p_candidate);
 PERFORM t008_check_publishable(p_candidate);
 SELECT * INTO approval FROM t008_approval_revisions WHERE candidate_id=p_candidate
 ORDER BY revision DESC LIMIT 1;
 IF NOT FOUND OR approval.content_digest IS DISTINCT FROM t008_candidate_digest(p_candidate)
 OR approval.proof_digest IS DISTINCT FROM t008_proof_digest(p_candidate)
 THEN RAISE EXCEPTION 'T008 stale or missing approval'; END IF;
 SELECT state INTO preview_state FROM t008_publication_preview WHERE candidate_id=p_candidate;
 IF preview_state='published' AND previous=p_candidate THEN RETURN 'already_published'; END IF;
 IF preview_state IS NOT NULL THEN RAISE EXCEPTION 'T008 retired preview not publishable'; END IF;
 SELECT * INTO d FROM t008_identity_decisions WHERE candidate_id=p_candidate;
 IF d.candidate_id IS NOT NULL AND (
  d.title_digest IS DISTINCT FROM t008_evidence_snapshot(d.title_evidence_id)
  OR d.artist_digest IS DISTINCT FROM t008_evidence_snapshot(d.artist_evidence_id)
  OR NOT EXISTS(SELECT 1 FROM t008_evidence WHERE id=d.title_evidence_id AND candidate_id=p_candidate AND verification='verified')
  OR NOT EXISTS(SELECT 1 FROM t008_evidence WHERE id=d.artist_evidence_id AND candidate_id=p_candidate AND verification='verified'))
 THEN RAISE EXCEPTION 'T008 identity evidence changed'; END IF;
 SELECT EXISTS(SELECT 1 FROM t008_reapplications WHERE candidate_id=p_candidate)
 INTO lineage_ok;
 IF previous IS NOT NULL AND previous<>p_candidate THEN
   IF d.candidate_id IS NULL OR d.compared_candidate_id<>previous
   OR d.decision<>'same_recording' THEN
     RAISE EXCEPTION 'T008 active revision requires verified same-recording decision';
   END IF;
 ELSIF EXISTS(SELECT 1 FROM t008_candidates x WHERE
     x.external_source=c.external_source AND x.external_entity_type=c.external_entity_type
     AND x.external_id=c.external_id AND x.id<>c.id)
     AND NOT lineage_ok AND d.candidate_id IS NULL THEN
   RAISE EXCEPTION 'T008 multiple matching external ID candidates require identity adjudication';
 END IF;
 IF d.decision='distinct_recording' THEN
 RAISE EXCEPTION 'T008 distinct recording cannot share active external identifier'; END IF;
 IF previous IS NULL THEN
 INSERT INTO t008_active_publications(source_code,entity_type,external_id,candidate_id)
 VALUES(c.external_source,c.external_entity_type,c.external_id,p_candidate);
 ELSE
 UPDATE t008_publication_preview SET state='superseded' WHERE candidate_id=previous
 AND state='published';
 IF NOT FOUND THEN RAISE EXCEPTION 'T008 active pointer and preview mismatch'; END IF;
 UPDATE t008_active_publications SET candidate_id=p_candidate,activated_at=now()
 WHERE source_code=c.external_source AND entity_type=c.external_entity_type
 AND external_id=c.external_id;
 END IF;
 INSERT INTO t008_publication_preview(candidate_id,title,artist,approved_by,approved_at,
  proof_digest,source_code,entity_type,external_id)
 VALUES(p_candidate,c.title,c.artist,approval.approved_by,approval.approved_at,
  approval.proof_digest,c.external_source,c.external_entity_type,c.external_id);
 INSERT INTO t008_publication_history(source_code,entity_type,external_id,candidate_id,
  preceding_id,action,actor)
 VALUES(c.external_source,c.external_entity_type,c.external_id,p_candidate,previous,
 CASE WHEN previous IS NULL THEN 'initial' ELSE 'supersede' END,t008_actor());
 INSERT INTO t008_audit(batch_id,action,details) VALUES(c.batch_id,'published',
 jsonb_build_object('candidate_id',p_candidate,'previous_id',previous,'actor',t008_actor()));
 IF p_fail THEN RAISE EXCEPTION 'T008 synthetic publication failure'; END IF;
 RETURN 'published';
END $$;


REVOKE ALL ON FUNCTION t008_reconcile_visibility(UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION t008_reconcile_visibility(UUID) TO t008_publisher;
REVOKE ALL ON t008_publication_preview,t008_active_publications,t008_identity_decisions FROM PUBLIC;
REVOKE ALL ON FUNCTION t008_publish_preview(UUID,BOOLEAN),t008_revoke_preview(UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION t008_publish_preview(UUID,BOOLEAN),t008_revoke_preview(UUID) TO t008_publisher;
COMMIT;
