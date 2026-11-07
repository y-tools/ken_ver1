-- T008 B-018, executable ONLY on disposable test PostgreSQL.
BEGIN;
DO $$BEGIN IF current_database() NOT IN ('ken_test','t008_test') THEN
 RAISE EXCEPTION 'B018: forbidden outside disposable test DB'; END IF; END$$;
ALTER TABLE t008_publication_preview DROP CONSTRAINT t008_publication_preview_state_check;
ALTER TABLE t008_publication_preview ADD CONSTRAINT t008_publication_preview_state_check
 CHECK(state IN ('published','revoked','superseded'));
ALTER TABLE t008_publication_preview
 ADD COLUMN source_code TEXT, ADD COLUMN entity_type TEXT, ADD COLUMN external_id TEXT;
CREATE UNIQUE INDEX t008_unique_live_preview ON t008_publication_preview
 (source_code,entity_type,external_id) WHERE state='published';
-- Intake/review claims are not the live publication pointer.
CREATE TABLE t008_active_publications(
 source_code TEXT NOT NULL,entity_type TEXT NOT NULL,external_id TEXT NOT NULL,
 candidate_id UUID NOT NULL UNIQUE REFERENCES t008_candidates(id),
 activated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(source_code,entity_type,external_id)
);
CREATE TABLE t008_publication_history(
 id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 source_code TEXT NOT NULL,entity_type TEXT NOT NULL,external_id TEXT NOT NULL,
 candidate_id UUID NOT NULL REFERENCES t008_candidates(id),
 preceding_id UUID REFERENCES t008_candidates(id),
 action TEXT NOT NULL CHECK(action IN ('initial','supersede','revoke')),
 actor TEXT NOT NULL,occurred_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE TRIGGER t008_publication_history_immutable BEFORE UPDATE OR DELETE
 ON t008_publication_history FOR EACH ROW EXECUTE FUNCTION t008_immutable_rows();
CREATE TABLE t008_identity_decisions(
 candidate_id UUID PRIMARY KEY REFERENCES t008_candidates(id),
 compared_candidate_id UUID NOT NULL REFERENCES t008_candidates(id),
 title_evidence_id BIGINT NOT NULL REFERENCES t008_evidence(id),
 artist_evidence_id BIGINT NOT NULL REFERENCES t008_evidence(id),
 decision TEXT NOT NULL CHECK(decision IN ('same_recording','distinct_recording')),
 reviewer_id TEXT NOT NULL,
 rationale TEXT NOT NULL CHECK(length(btrim(rationale))>=10),
 decided_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 CHECK(candidate_id<>compared_candidate_id)
);
CREATE TRIGGER t008_identity_decisions_immutable BEFORE UPDATE OR DELETE
 ON t008_identity_decisions FOR EACH ROW EXECUTE FUNCTION t008_immutable_rows();

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
  artist_evidence_id,decision,reviewer_id,rationale)
 VALUES(p_candidate,p_compared,p_title,p_artist,p_decision,reviewer,p_reason);
 INSERT INTO t008_audit(batch_id,action,details)
 VALUES(c.batch_id,'identity_decision',jsonb_build_object('candidate_id',p_candidate,
   'compared_candidate_id',p_compared,'decision',p_decision,'reviewer_id',reviewer,
   'title_evidence_id',p_title,'artist_evidence_id',p_artist,'reason',p_reason));
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

CREATE OR REPLACE FUNCTION t008_revoke_preview(p_candidate UUID)
RETURNS TEXT LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE c t008_candidates%ROWTYPE; active_id UUID; prior_state TEXT;
BEGIN
 SELECT * INTO STRICT c FROM t008_candidates WHERE id=p_candidate;
 PERFORM pg_advisory_xact_lock(hashtextextended(
 't008:claim:'||c.external_source||':'||c.external_entity_type||':'||c.external_id,0));
 PERFORM 1 FROM t008_candidates WHERE id=p_candidate FOR UPDATE;
 SELECT state INTO prior_state FROM t008_publication_preview WHERE candidate_id=p_candidate;
 IF prior_state='revoked' THEN RETURN 'already_revoked'; END IF;
 IF prior_state<>'published' THEN RAISE EXCEPTION 'T008 only active preview can be revoked'; END IF;
 SELECT candidate_id INTO active_id FROM t008_active_publications
 WHERE source_code=c.external_source AND entity_type=c.external_entity_type
 AND external_id=c.external_id FOR UPDATE;
 IF active_id IS DISTINCT FROM p_candidate THEN
   RAISE EXCEPTION 'T008 revocation target is not currently active'; END IF;
 DELETE FROM t008_active_publications WHERE source_code=c.external_source
 AND entity_type=c.external_entity_type AND external_id=c.external_id;
 UPDATE t008_publication_preview SET state='revoked',revoked_at=now()
 WHERE candidate_id=p_candidate AND state='published';
 INSERT INTO t008_publication_history(source_code,entity_type,external_id,candidate_id,
  preceding_id,action,actor)
 VALUES(c.external_source,c.external_entity_type,c.external_id,p_candidate,p_candidate,
 'revoke',t008_actor());
 INSERT INTO t008_audit(batch_id,action,details)
 VALUES(c.batch_id,'revoked',jsonb_build_object('actor',t008_actor(),'candidate_id',p_candidate));
 RETURN 'revoked';
END $$;
REVOKE ALL ON FUNCTION t008_identity_decide(UUID,UUID,BIGINT,BIGINT,TEXT,TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION t008_identity_decide(UUID,UUID,BIGINT,BIGINT,TEXT,TEXT) TO t008_reviewer;
COMMIT;
