-- T008 B-010: disposable PostgreSQL 16 concurrency/permission/proof hardening.
-- Apply AFTER 004,005,006,007. NOT a production migration.
BEGIN;

ALTER TABLE t008_candidates ADD COLUMN source_policy_id BIGINT REFERENCES t008_source_policies(id);
ALTER TABLE t008_candidates ALTER COLUMN source_policy_id SET NOT NULL;
ALTER TABLE t008_intake_events ADD COLUMN source_policy_id BIGINT REFERENCES t008_source_policies(id);
ALTER TABLE t008_intake_events ALTER COLUMN source_policy_id SET NOT NULL;
ALTER TABLE t008_intake_events ADD COLUMN content_digest TEXT NOT NULL;

CREATE OR REPLACE FUNCTION t008_policy_storage_ok(p_id BIGINT,p_source TEXT,p_method TEXT)
RETURNS BOOLEAN LANGUAGE sql STABLE SET search_path=public,pg_temp AS $$
SELECT EXISTS(
 SELECT 1 FROM t008_source_policies p
 WHERE p.id=p_id AND p.source_code=p_source AND p.acquisition_method=p_method
 AND p.automated_access_allowed AND p.storage_allowed
 AND p.content_license IS NOT NULL AND lower(btrim(p.content_license)) NOT IN ('','unknown','pending','unreviewed','未確認')
 AND p.access_terms IS NOT NULL AND lower(btrim(p.access_terms)) NOT IN ('','unknown','pending','unreviewed','未確認')
 AND p.reviewed_at IS NOT NULL AND p.expires_at IS NOT NULL
 AND now() >= p.reviewed_at AND now() < p.expires_at
 AND p.allowed_fields @> ARRAY['title','artist']::text[]
 AND p.policy_version=(SELECT max(v.policy_version) FROM t008_source_policies v
                       WHERE v.source_code=p.source_code AND v.acquisition_method=p.acquisition_method)
);
$$;

CREATE OR REPLACE FUNCTION t008_candidate_gate() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE pol t008_source_policies%ROWTYPE;
BEGIN
 SELECT * INTO pol FROM t008_source_policies WHERE id=NEW.source_policy_id;
 IF NOT FOUND OR NEW.external_source IS DISTINCT FROM pol.source_code
 OR NEW.external_id IS NULL OR btrim(NEW.external_id)=''
 OR NEW.external_entity_type NOT IN ('work','recording','release')
 OR btrim(NEW.title)='' OR btrim(NEW.artist)=''
 OR NEW.verification NOT IN ('unverified','review')
 OR NOT t008_policy_storage_ok(pol.id,pol.source_code,pol.acquisition_method)
 THEN RAISE EXCEPTION 'T008 candidate lacks valid reviewed storage policy'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER t008_candidate_gate_insert BEFORE INSERT ON t008_candidates
 FOR EACH ROW EXECUTE FUNCTION t008_candidate_gate();

-- Lock parent candidate for any evidence mutation. Once previewed or revoked,
-- both candidate and evidence are immutable, including for owner connections.
CREATE OR REPLACE FUNCTION t008_evidence_lock() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE cid UUID;
BEGIN
 cid=CASE WHEN TG_OP='DELETE' THEN OLD.candidate_id ELSE NEW.candidate_id END;
 IF TG_OP='UPDATE' AND NEW.candidate_id IS DISTINCT FROM OLD.candidate_id THEN
  RAISE EXCEPTION 'T008 evidence candidate reassignment forbidden';
 END IF;
 PERFORM 1 FROM t008_candidates WHERE id=cid FOR UPDATE;
 IF EXISTS(SELECT 1 FROM t008_publication_preview WHERE candidate_id=cid) THEN
  RAISE EXCEPTION 'T008 published or revoked proof is immutable';
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER t008_evidence_parent_lock BEFORE INSERT OR UPDATE OR DELETE ON t008_evidence
 FOR EACH ROW EXECUTE FUNCTION t008_evidence_lock();

CREATE OR REPLACE FUNCTION t008_candidate_lock() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM t008_publication_preview WHERE candidate_id=OLD.id) THEN
  RAISE EXCEPTION 'T008 published or revoked candidate is immutable';
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER t008_candidate_update_lock BEFORE UPDATE OR DELETE ON t008_candidates
 FOR EACH ROW EXECUTE FUNCTION t008_candidate_lock();

CREATE OR REPLACE FUNCTION t008_actor() RETURNS TEXT
LANGUAGE sql STABLE SET search_path=public,pg_temp AS $$
 SELECT session_user || ' [role:' ||
 coalesce(nullif(current_setting('role',true),''),'none') || ']'
$$;

CREATE OR REPLACE FUNCTION t008_candidate_digest(p_candidate UUID)
RETURNS TEXT LANGUAGE sql STABLE SET search_path=public,pg_temp AS $$
 SELECT md5(coalesce((SELECT row_to_json(c)::text FROM t008_candidates c
                      WHERE c.id=p_candidate),''))
$$;
CREATE OR REPLACE FUNCTION t008_proof_digest(p_candidate UUID)
RETURNS TEXT LANGUAGE sql STABLE SET search_path=public,pg_temp AS $$
 SELECT md5(coalesce(string_agg(row_to_json(e)::text,'|' ORDER BY e.id),''))
 FROM t008_evidence e WHERE e.candidate_id=p_candidate
$$;

-- Function writes run as the schema owner; the caller cannot write tables directly.
-- Advisory transaction lock serializes the absent-claim case across connections.
CREATE OR REPLACE FUNCTION t008_stage_one(
 p_batch UUID,p_title TEXT,p_artist TEXT,p_source TEXT,p_entity_type TEXT,
 p_external_id TEXT,p_policy_id BIGINT,p_content_digest TEXT,p_input_digest TEXT
) RETURNS TEXT LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE pol t008_source_policies%ROWTYPE;
        prior t008_external_claims%ROWTYPE; cid UUID; outcome TEXT;
BEGIN
 IF current_database() NOT IN ('ken_test','t008_test') THEN
   RAISE EXCEPTION 'T008 staging forbidden outside disposable databases';
 END IF;
 IF p_title IS NULL OR btrim(p_title)='' OR p_artist IS NULL OR btrim(p_artist)=''
 OR p_external_id IS NULL OR btrim(p_external_id)=''
 OR p_entity_type NOT IN ('work','recording','release')
 OR p_content_digest IS NULL OR p_input_digest IS NULL THEN
   RAISE EXCEPTION 'T008 invalid stage payload';
 END IF;
 SELECT * INTO pol FROM t008_source_policies WHERE id=p_policy_id;
 IF NOT FOUND OR pol.source_code IS DISTINCT FROM p_source
 OR NOT t008_policy_storage_ok(p_policy_id,p_source,pol.acquisition_method) THEN
   RAISE EXCEPTION 'T008 unreviewed or expired storage policy';
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(
     't008:claim:'||p_source||':'||p_entity_type||':'||p_external_id,0));
 INSERT INTO t008_batches(id) VALUES(p_batch) ON CONFLICT(id) DO NOTHING;
 IF EXISTS(SELECT 1 FROM t008_intake_events
           WHERE batch_id=p_batch AND input_digest=p_input_digest) THEN
    RETURN 'duplicate';
 END IF;
 SELECT * INTO prior FROM t008_external_claims WHERE source_code=p_source
   AND entity_type=p_entity_type AND external_id=p_external_id FOR UPDATE;
 IF FOUND AND prior.input_digest=p_content_digest THEN
   cid=prior.candidate_id;
   outcome='duplicate';
 ELSE
   cid=gen_random_uuid();
   outcome=CASE WHEN FOUND THEN 'collision' ELSE 'new' END;
   INSERT INTO t008_candidates(id,batch_id,title,artist,title_key,artist_key,
      external_source,external_entity_type,external_id,input_digest,
      source_policy_id,verification)
   VALUES(cid,p_batch,p_title,p_artist,lower(p_title),lower(p_artist),
      p_source,p_entity_type,p_external_id,p_input_digest,p_policy_id,
      CASE WHEN outcome='collision' THEN 'review' ELSE 'unverified' END);
   IF outcome='new' THEN
      INSERT INTO t008_external_claims(source_code,entity_type,external_id,candidate_id,input_digest)
      VALUES(p_source,p_entity_type,p_external_id,cid,p_content_digest);
   ELSE
      INSERT INTO t008_review_queue(candidate_id,reason)
      VALUES(cid,'external_id_content_conflict');
   END IF;
 END IF;
 INSERT INTO t008_intake_events(batch_id,input_digest,source_code,entity_type,
    external_id,title,artist,outcome,candidate_id,source_policy_id,content_digest)
 VALUES(p_batch,p_input_digest,p_source,p_entity_type,
    p_external_id,p_title,p_artist,outcome,cid,p_policy_id,p_content_digest);
 INSERT INTO t008_evidence(candidate_id,field_name,source_code,source_record_id,
   acquisition_method,original_data_hash,source_policy_id)
 VALUES(cid,'title',p_source,p_external_id,pol.acquisition_method,md5(p_title),p_policy_id),
       (cid,'artist',p_source,p_external_id,pol.acquisition_method,md5(p_artist),p_policy_id);
 RETURN outcome;
END $$;

CREATE OR REPLACE FUNCTION t008_approve_candidate(p_candidate UUID,p_note TEXT DEFAULT '')
RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE c t008_candidates%ROWTYPE;
BEGIN
 SELECT * INTO STRICT c FROM t008_candidates WHERE id=p_candidate FOR UPDATE;
 PERFORM t008_check_publishable(p_candidate);
 IF EXISTS(SELECT 1 FROM t008_publication_preview WHERE candidate_id=p_candidate) THEN
  RAISE EXCEPTION 'T008 preview was already published or revoked';
 END IF;
 INSERT INTO t008_approvals(candidate_id,content_digest,proof_digest,approved_by,note)
 VALUES(p_candidate,t008_candidate_digest(p_candidate),
        t008_proof_digest(p_candidate),t008_actor(),p_note);
 INSERT INTO t008_audit(batch_id,action,details)
 VALUES(c.batch_id,'approved',jsonb_build_object('actor',t008_actor(),'candidate_id',p_candidate));
END $$;

CREATE OR REPLACE FUNCTION t008_publish_preview(p_candidate UUID,p_fail BOOLEAN DEFAULT FALSE)
RETURNS TEXT LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE c t008_candidates%ROWTYPE; a t008_approvals%ROWTYPE; old_state TEXT;
BEGIN
 SELECT * INTO STRICT c FROM t008_candidates WHERE id=p_candidate FOR UPDATE;
 PERFORM t008_check_publishable(p_candidate);
 SELECT * INTO a FROM t008_approvals WHERE candidate_id=p_candidate;
 IF NOT FOUND OR a.content_digest IS DISTINCT FROM t008_candidate_digest(p_candidate)
 OR a.proof_digest IS DISTINCT FROM t008_proof_digest(p_candidate)
 THEN RAISE EXCEPTION 'T008 approval missing or stale'; END IF;
 SELECT state INTO old_state FROM t008_publication_preview WHERE candidate_id=p_candidate;
 IF old_state='revoked' THEN RAISE EXCEPTION 'T008 permanent revocation: new candidate ID required'; END IF;
 IF old_state='published' THEN RETURN 'already_published'; END IF;
 INSERT INTO t008_publication_preview(candidate_id,title,artist,approved_by,approved_at,proof_digest)
 VALUES(p_candidate,c.title,c.artist,a.approved_by,a.approved_at,a.proof_digest);
 INSERT INTO t008_audit(batch_id,action,details)
 VALUES(c.batch_id,'published',jsonb_build_object('actor',t008_actor(),'candidate_id',p_candidate,
  'after',jsonb_build_object('title',c.title,'artist',c.artist),'before',null));
 IF p_fail THEN RAISE EXCEPTION 'T008 synthetic publication failure'; END IF;
 RETURN 'published';
END $$;

-- Revoke all direct DML from the stage role and grant only the audited gateway.
REVOKE ALL ON t008_batches,t008_candidates,t008_evidence,t008_review_queue,
 t008_external_claims,t008_intake_events FROM t008_stage_writer;
GRANT SELECT ON t008_batches,t008_candidates,t008_evidence,t008_review_queue,
 t008_external_claims,t008_intake_events TO t008_stage_writer;
REVOKE USAGE ON SEQUENCE t008_evidence_id_seq,t008_review_queue_id_seq,
 t008_intake_events_id_seq FROM t008_stage_writer;
REVOKE EXECUTE ON FUNCTION t008_stage_audit(UUID,JSONB) FROM t008_stage_writer;
REVOKE ALL ON FUNCTION t008_stage_one(UUID,TEXT,TEXT,TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION t008_candidate_digest(UUID) FROM PUBLIC;
REVOKE ALL ON FUNCTION t008_policy_storage_ok(BIGINT,TEXT,TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION t008_stage_one(UUID,TEXT,TEXT,TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT)
 TO t008_stage_writer;
COMMIT;
