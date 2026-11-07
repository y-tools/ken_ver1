-- T008 B-008. Disposable PostgreSQL 16 only; not a production migration.
-- Schema is additive, except replacing source/method uniqueness with versioned uniqueness
-- and dropping the unsafe same-batch external ID silent-discard index.
BEGIN;

ALTER TABLE t008_source_policies
    ADD COLUMN policy_version INTEGER NOT NULL DEFAULT 1 CHECK(policy_version > 0);
ALTER TABLE t008_source_policies
    DROP CONSTRAINT IF EXISTS t008_source_policies_source_code_acquisition_method_key;
ALTER TABLE t008_source_policies
    ADD CONSTRAINT t008_policy_version_unique UNIQUE(source_code,acquisition_method,policy_version);

CREATE OR REPLACE FUNCTION t008_immutable_rows() RETURNS trigger
LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
BEGIN
  RAISE EXCEPTION 'T008 append-only record cannot be changed: %', TG_TABLE_NAME;
END $$;
CREATE TRIGGER t008_policy_immutable BEFORE UPDATE OR DELETE ON t008_source_policies
 FOR EACH ROW EXECUTE FUNCTION t008_immutable_rows();
CREATE TRIGGER t008_audit_immutable BEFORE UPDATE OR DELETE ON t008_audit
 FOR EACH ROW EXECUTE FUNCTION t008_immutable_rows();

DROP INDEX IF EXISTS t008_candidates_source_record_once;
-- A distinct payload with the same external ID must be retained for review.
CREATE TABLE t008_external_claims (
 source_code TEXT NOT NULL,
 entity_type TEXT NOT NULL CHECK(entity_type IN ('work','recording','release')),
 external_id TEXT NOT NULL,
 candidate_id UUID NOT NULL REFERENCES t008_candidates(id),
 input_digest TEXT NOT NULL,
 PRIMARY KEY(source_code,entity_type,external_id)
);
CREATE TABLE t008_intake_events (
 id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 batch_id UUID NOT NULL REFERENCES t008_batches(id),
 input_digest TEXT NOT NULL,
 source_code TEXT NOT NULL,
 entity_type TEXT NOT NULL,
 external_id TEXT NOT NULL,
 title TEXT NOT NULL,
 artist TEXT NOT NULL,
 outcome TEXT NOT NULL CHECK(outcome IN ('new','duplicate','collision','rejected')),
 candidate_id UUID REFERENCES t008_candidates(id),
 occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 UNIQUE(batch_id,input_digest)
);
CREATE INDEX t008_intake_external ON t008_intake_events(source_code,entity_type,external_id);
CREATE TRIGGER t008_intake_immutable BEFORE UPDATE OR DELETE ON t008_intake_events
 FOR EACH ROW EXECUTE FUNCTION t008_immutable_rows();

-- The evidence's policy ID is a snapshot reference: policy rows cannot be updated.
CREATE OR REPLACE FUNCTION t008_enforce_evidence_source() RETURNS trigger
LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
DECLARE pol t008_source_policies%ROWTYPE;
BEGIN
 SELECT * INTO pol FROM t008_source_policies WHERE id=NEW.source_policy_id;
 IF NOT FOUND OR pol.source_code IS DISTINCT FROM NEW.source_code
    OR pol.acquisition_method IS DISTINCT FROM NEW.acquisition_method
    OR pol.automated_access_allowed IS DISTINCT FROM TRUE
    OR pol.storage_allowed IS DISTINCT FROM TRUE
    OR pol.reviewed_at IS NULL OR pol.expires_at IS NULL
    OR now() NOT BETWEEN pol.reviewed_at AND pol.expires_at
    OR NOT (NEW.field_name=ANY(pol.allowed_fields)) THEN
   RAISE EXCEPTION 'T008 evidence source policy mismatch or expired';
 END IF;
 IF NEW.original_evidence_id IS NOT NULL AND NEW.original_evidence_id >= NEW.id THEN
   RAISE EXCEPTION 'T008 evidence ancestry must precede derived evidence';
 END IF;
 RETURN NEW;
END $$;

CREATE TABLE t008_approvals (
 candidate_id UUID PRIMARY KEY REFERENCES t008_candidates(id),
 content_digest TEXT NOT NULL,
 proof_digest TEXT NOT NULL,
 approved_by TEXT NOT NULL,
 approved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 note TEXT NOT NULL DEFAULT ''
);
CREATE TRIGGER t008_approval_immutable BEFORE UPDATE OR DELETE ON t008_approvals
 FOR EACH ROW EXECUTE FUNCTION t008_immutable_rows();

-- Preview is NOT the existing songs table and is not wired into the public API.
CREATE TABLE t008_publication_preview (
 candidate_id UUID PRIMARY KEY REFERENCES t008_candidates(id),
 title TEXT NOT NULL,
 artist TEXT NOT NULL,
 approved_by TEXT NOT NULL,
 approved_at TIMESTAMPTZ NOT NULL,
 proof_digest TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'published' CHECK(state IN ('published','revoked')),
 published_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 revoked_at TIMESTAMPTZ
);
CREATE INDEX t008_preview_state ON t008_publication_preview(state);

CREATE OR REPLACE FUNCTION t008_proof_digest(p_candidate UUID)
RETURNS TEXT LANGUAGE sql STABLE SET search_path=public,pg_temp AS $$
 SELECT md5(coalesce(string_agg(
    e.id::text || ':' || e.field_name || ':' || e.original_data_hash || ':'
    || e.source_policy_id::text || ':' || e.verification, '|' ORDER BY e.id),''))
 FROM t008_evidence e WHERE e.candidate_id=p_candidate
$$;

CREATE OR REPLACE FUNCTION t008_check_publishable(p_candidate UUID)
RETURNS void LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
DECLARE c t008_candidates%ROWTYPE;
BEGIN
 SELECT * INTO c FROM t008_candidates WHERE id=p_candidate;
 IF NOT FOUND OR c.verification <> 'verified' THEN
    RAISE EXCEPTION 'T008 candidate must be verified';
 END IF;
 IF EXISTS(SELECT 1 FROM t008_review_queue WHERE candidate_id=p_candidate AND status='open') THEN
    RAISE EXCEPTION 'T008 candidate has unresolved review';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM t008_evidence WHERE candidate_id=p_candidate AND field_name='title' AND verification='verified')
 OR NOT EXISTS(SELECT 1 FROM t008_evidence WHERE candidate_id=p_candidate AND field_name='artist' AND verification='verified')
 THEN RAISE EXCEPTION 'T008 title and artist evidence must be verified'; END IF;
 IF EXISTS(
   SELECT 1 FROM t008_evidence e
   LEFT JOIN t008_source_policies p ON p.id=e.source_policy_id
   WHERE e.candidate_id=p_candidate AND (
      p.id IS NULL OR e.verification <> 'verified'
      OR p.publication_allowed IS DISTINCT FROM TRUE
      OR p.storage_allowed IS DISTINCT FROM TRUE
      OR p.automated_access_allowed IS DISTINCT FROM TRUE
      OR p.reviewed_at IS NULL OR p.expires_at IS NULL
      OR now() NOT BETWEEN p.reviewed_at AND p.expires_at
      OR NOT(e.field_name=ANY(p.allowed_fields))
      OR EXISTS(SELECT 1 FROM t008_source_policies newer
                WHERE newer.source_code=p.source_code
                  AND newer.acquisition_method=p.acquisition_method
                  AND newer.policy_version>p.policy_version)
    )
 ) THEN RAISE EXCEPTION 'T008 evidence policy not currently publishable'; END IF;
END $$;

CREATE OR REPLACE FUNCTION t008_actor() RETURNS TEXT
LANGUAGE sql STABLE SET search_path=public,pg_temp AS $$
 SELECT CASE WHEN current_setting('role',true) IN ('', 'none') THEN session_user
             ELSE current_setting('role',true) END
$$;

CREATE OR REPLACE FUNCTION t008_stage_audit(p_batch UUID,p_details JSONB)
RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
BEGIN
 INSERT INTO t008_audit(batch_id,action,details)
 VALUES(p_batch,'staged',jsonb_build_object('actor',t008_actor(),'counts',p_details));
END $$;

CREATE OR REPLACE FUNCTION t008_approve_candidate(p_candidate UUID, p_note TEXT DEFAULT '')
RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE c t008_candidates%ROWTYPE;
BEGIN
 PERFORM t008_check_publishable(p_candidate);
 SELECT * INTO STRICT c FROM t008_candidates WHERE id=p_candidate FOR UPDATE;
 INSERT INTO t008_approvals(candidate_id,content_digest,proof_digest,approved_by,note)
 VALUES(p_candidate,c.input_digest,t008_proof_digest(p_candidate),t008_actor(),p_note);
 INSERT INTO t008_audit(batch_id,action,details)
 VALUES(c.batch_id,'approved',jsonb_build_object('actor',t008_actor(),'candidate_id',p_candidate));
END $$;

CREATE OR REPLACE FUNCTION t008_publish_preview(p_candidate UUID,p_fail BOOLEAN DEFAULT FALSE)
RETURNS TEXT LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE c t008_candidates%ROWTYPE; a t008_approvals%ROWTYPE; old_state TEXT;
BEGIN
 PERFORM t008_check_publishable(p_candidate);
 SELECT * INTO STRICT c FROM t008_candidates WHERE id=p_candidate FOR UPDATE;
 SELECT * INTO a FROM t008_approvals WHERE candidate_id=p_candidate;
 IF NOT FOUND OR a.content_digest IS DISTINCT FROM c.input_digest
    OR a.proof_digest IS DISTINCT FROM t008_proof_digest(p_candidate)
 THEN RAISE EXCEPTION 'T008 approval missing or stale'; END IF;
 SELECT state INTO old_state FROM t008_publication_preview WHERE candidate_id=p_candidate;
 IF old_state='revoked' THEN RAISE EXCEPTION 'T008 revoked preview needs a new approval revision'; END IF;
 IF old_state='published' THEN RETURN 'already_published'; END IF;
 INSERT INTO t008_publication_preview(candidate_id,title,artist,approved_by,approved_at,proof_digest)
 VALUES(p_candidate,c.title,c.artist,a.approved_by,a.approved_at,a.proof_digest);
 INSERT INTO t008_audit(batch_id,action,details) VALUES
 (c.batch_id,'published',jsonb_build_object('actor',t008_actor(),'candidate_id',p_candidate,
  'after',jsonb_build_object('title',c.title,'artist',c.artist),'before',null));
 IF p_fail THEN RAISE EXCEPTION 'T008 synthetic publication failure'; END IF;
 RETURN 'published';
END $$;

CREATE OR REPLACE FUNCTION t008_revoke_preview(p_candidate UUID)
RETURNS TEXT LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE bid UUID; num INTEGER;
BEGIN
 SELECT batch_id INTO bid FROM t008_candidates WHERE id=p_candidate;
 UPDATE t008_publication_preview SET state='revoked',revoked_at=now()
 WHERE candidate_id=p_candidate AND state='published';
 GET DIAGNOSTICS num=ROW_COUNT;
 IF num=0 THEN
   IF EXISTS(SELECT 1 FROM t008_publication_preview WHERE candidate_id=p_candidate AND state='revoked')
   THEN RETURN 'already_revoked'; END IF;
   RAISE EXCEPTION 'T008 no published preview';
 END IF;
 INSERT INTO t008_audit(batch_id,action,details) VALUES
 (bid,'revoked',jsonb_build_object('actor',t008_actor(),'candidate_id',p_candidate));
 RETURN 'revoked';
END $$;

-- PostgreSQL grants function EXECUTE to PUBLIC by default: explicitly revoke.
REVOKE ALL ON FUNCTION t008_proof_digest(UUID) FROM PUBLIC;
REVOKE ALL ON FUNCTION t008_check_publishable(UUID) FROM PUBLIC;
REVOKE ALL ON FUNCTION t008_actor() FROM PUBLIC;
REVOKE ALL ON FUNCTION t008_stage_audit(UUID,JSONB) FROM PUBLIC;
REVOKE ALL ON FUNCTION t008_approve_candidate(UUID,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION t008_publish_preview(UUID,BOOLEAN) FROM PUBLIC;
REVOKE ALL ON FUNCTION t008_revoke_preview(UUID) FROM PUBLIC;
COMMIT;
