-- T008 B-012: isolated PostgreSQL 16 hardening after migration 008.
-- Disposable test database ONLY. No changes to legacy songs/API.
BEGIN;
DO $$ BEGIN
 IF current_database() NOT IN ('ken_test','t008_test') THEN
  RAISE EXCEPTION 'T008 migration forbidden outside test DB';
 END IF;
END $$;

-- PostgreSQL array_to_json produces compact JSON arrays; match the Python
-- json.dumps(..., ensure_ascii=False, separators=(',', ':')) fixture encoding.
-- For application rollout, enforce one published canonical specification.
CREATE OR REPLACE FUNCTION t008_content_sha256(p_title text,p_artist text,
 p_external_id text,p_type text)
RETURNS text LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public AS $$
 SELECT encode(sha256(convert_to(array_to_json(ARRAY[
     p_title,p_artist,p_external_id,p_type])::text,'UTF8')),'hex')
$$;
CREATE OR REPLACE FUNCTION t008_event_sha256(p_source text,p_method text,
 p_policy bigint,p_content text)
RETURNS text LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public AS $$
 SELECT encode(sha256(convert_to(
 format('[%s,%s,%s,%s]',to_json(p_source)::text,to_json(p_method)::text,
        p_policy::text,to_json(p_content)::text),'UTF8')),'hex')
$$;

-- Share source-version serialization between new policy insertion and publish.
CREATE OR REPLACE FUNCTION t008_lock_policy_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended(
   't008:policy:'||NEW.source_code||':'||NEW.acquisition_method,0));
 RETURN NEW;
END $$;
CREATE TRIGGER t008_policy_version_serial BEFORE INSERT ON t008_source_policies
FOR EACH ROW EXECUTE FUNCTION t008_lock_policy_insert();

-- Do not allow a verification update without a DB-side audit (including direct SQL
-- by schema owner). The following trigger records all changes, including the reason
-- passed through the reviewer gateway. A blank/missing reason rejects changes.
CREATE OR REPLACE FUNCTION t008_review_audit() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE cid uuid; bid uuid; reason_text text;
BEGIN
 IF NEW.verification IS NOT DISTINCT FROM OLD.verification THEN RETURN NEW; END IF;
 reason_text := nullif(btrim(current_setting('t008.review_reason',true)),'');
 IF reason_text IS NULL THEN
   RAISE EXCEPTION 'T008 verification transition requires reason';
 END IF;
 IF TG_TABLE_NAME='t008_candidates' THEN
   cid:=NEW.id;
 ELSE
   cid:=NEW.candidate_id;
 END IF;
 SELECT batch_id INTO bid FROM t008_candidates WHERE id=cid;
 INSERT INTO t008_audit(batch_id,action,details) VALUES
 (bid,'verification_changed',jsonb_build_object(
    'actor',session_user,'role',current_setting('role',true),
    'candidate_id',cid,'table',TG_TABLE_NAME,
    'record_id',NEW.id::text,
    'before',OLD.verification,'after',NEW.verification,'reason',reason_text,
    'at',clock_timestamp()));
 RETURN NEW;
END $$;
CREATE TRIGGER t008_candidate_verification_audit AFTER UPDATE OF verification ON t008_candidates
FOR EACH ROW EXECUTE FUNCTION t008_review_audit();
CREATE TRIGGER t008_evidence_verification_audit AFTER UPDATE OF verification ON t008_evidence
FOR EACH ROW EXECUTE FUNCTION t008_review_audit();

CREATE OR REPLACE FUNCTION t008_review_mark(p_candidate uuid,p_reason text,
 p_verified boolean DEFAULT true) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
 IF p_reason IS NULL OR btrim(p_reason)='' THEN
   RAISE EXCEPTION 'T008 reviewer reason mandatory';
 END IF;
 -- Lock candidate ahead of evidence, review queue and approval.
 PERFORM 1 FROM t008_candidates WHERE id=p_candidate FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'T008 candidate not found'; END IF;
 IF EXISTS(SELECT 1 FROM t008_publication_preview WHERE candidate_id=p_candidate)
 THEN RAISE EXCEPTION 'T008 published evidence immutable'; END IF;
 PERFORM set_config('t008.review_reason',p_reason,true);
 UPDATE t008_candidates SET verification=
 CASE WHEN p_verified THEN 'verified' ELSE 'review' END WHERE id=p_candidate;
 UPDATE t008_evidence SET verification=
 CASE WHEN p_verified THEN 'verified' ELSE 'unverified' END
 WHERE candidate_id=p_candidate;
 IF p_verified THEN
  UPDATE t008_review_queue SET status='resolved'
  WHERE candidate_id=p_candidate AND status='open';
 ELSE
  INSERT INTO t008_review_queue(candidate_id,reason)
  VALUES(p_candidate,'review_reopened:'||left(p_reason,200));
 END IF;
END $$;

-- Protect reviewer privilege boundary: no direct verification writes.
REVOKE UPDATE(verification) ON t008_candidates,t008_evidence FROM t008_reviewer;
REVOKE UPDATE(status) ON t008_review_queue FROM t008_reviewer;
REVOKE ALL ON FUNCTION t008_review_mark(uuid,text,boolean) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION t008_review_mark(uuid,text,boolean) TO t008_reviewer;

-- Block direct audit fabrication by stage writers; only SECURITY DEFINER gateway
-- can create trusted intake audit entries.
REVOKE EXECUTE ON FUNCTION t008_stage_audit(UUID,JSONB) FROM t008_stage_writer;

-- Input digest revalidation occurs at the DB trust boundary, BEFORE any writes.
CREATE OR REPLACE FUNCTION t008_stage_one(
 p_batch UUID,p_title TEXT,p_artist TEXT,p_source TEXT,p_entity_type TEXT,
 p_external_id TEXT,p_policy_id BIGINT,p_content_digest TEXT,p_input_digest TEXT
) RETURNS TEXT LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE pol t008_source_policies%ROWTYPE;
        prior t008_external_claims%ROWTYPE; cid UUID; outcome TEXT;
        expected_content TEXT; expected_event TEXT;
BEGIN
 IF current_database() NOT IN ('ken_test','t008_test') THEN
   RAISE EXCEPTION 'T008 staging forbidden outside disposable databases';
 END IF;
 IF p_title IS NULL OR btrim(p_title)='' OR p_artist IS NULL OR btrim(p_artist)=''
 OR p_external_id IS NULL OR btrim(p_external_id)=''
 OR p_entity_type NOT IN ('work','recording','release')
 OR p_source IS NULL OR btrim(p_source)='' THEN
   RAISE EXCEPTION 'T008 invalid stage payload';
 END IF;
 SELECT * INTO pol FROM t008_source_policies WHERE id=p_policy_id;
 IF NOT FOUND OR pol.source_code IS DISTINCT FROM p_source
 OR NOT t008_policy_storage_ok(p_policy_id,p_source,pol.acquisition_method) THEN
   RAISE EXCEPTION 'T008 unreviewed or expired storage policy';
 END IF;
 expected_content:=t008_content_sha256(p_title,p_artist,p_external_id,p_entity_type);
 expected_event:=t008_event_sha256(p_source,pol.acquisition_method,
                                     p_policy_id,expected_content);
 IF p_content_digest IS DISTINCT FROM expected_content
 OR p_input_digest IS DISTINCT FROM expected_event THEN
   RAISE EXCEPTION 'T008 digest mismatch: input metadata not trusted';
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(
     't008:claim:'||p_source||':'||p_entity_type||':'||p_external_id,0));
 INSERT INTO t008_batches(id) VALUES(p_batch) ON CONFLICT(id) DO NOTHING;
 IF EXISTS(SELECT 1 FROM t008_intake_events
           WHERE batch_id=p_batch AND input_digest=expected_event) THEN
    RETURN 'duplicate';
 END IF;
 SELECT * INTO prior FROM t008_external_claims WHERE source_code=p_source
   AND entity_type=p_entity_type AND external_id=p_external_id FOR UPDATE;
 IF FOUND AND prior.input_digest=expected_content THEN
   cid=prior.candidate_id;
   outcome='duplicate';
 ELSE
   cid=gen_random_uuid();
   outcome=CASE WHEN FOUND THEN 'collision' ELSE 'new' END;
   INSERT INTO t008_candidates(id,batch_id,title,artist,title_key,artist_key,
      external_source,external_entity_type,external_id,input_digest,
      source_policy_id,verification)
   VALUES(cid,p_batch,p_title,p_artist,lower(p_title),lower(p_artist),
      p_source,p_entity_type,p_external_id,expected_event,p_policy_id,
      CASE WHEN outcome='collision' THEN 'review' ELSE 'unverified' END);
   IF outcome='new' THEN
      INSERT INTO t008_external_claims(source_code,entity_type,external_id,candidate_id,input_digest)
      VALUES(p_source,p_entity_type,p_external_id,cid,expected_content);
   ELSE
      INSERT INTO t008_review_queue(candidate_id,reason)
      VALUES(cid,'external_id_content_conflict');
   END IF;
 END IF;
 INSERT INTO t008_intake_events(batch_id,input_digest,source_code,entity_type,
    external_id,title,artist,outcome,candidate_id,source_policy_id,content_digest)
 VALUES(p_batch,expected_event,p_source,p_entity_type,
    p_external_id,p_title,p_artist,outcome,cid,p_policy_id,expected_content);
 INSERT INTO t008_evidence(candidate_id,field_name,source_code,source_record_id,
   acquisition_method,original_data_hash,source_policy_id)
 VALUES(cid,'title',p_source,p_external_id,pol.acquisition_method,md5(p_title),p_policy_id),
       (cid,'artist',p_source,p_external_id,pol.acquisition_method,md5(p_artist),p_policy_id);
 INSERT INTO t008_audit(batch_id,action,details) VALUES
 (p_batch,'intake_event',jsonb_build_object('actor',t008_actor(),
  'source',p_source,'entity_type',p_entity_type,'outcome',outcome,
  'policy_id',p_policy_id,'event_digest',expected_event));
 RETURN outcome;
END $$;
REVOKE ALL ON FUNCTION t008_stage_one(UUID,TEXT,TEXT,TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION t008_stage_one(UUID,TEXT,TEXT,TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT)
TO t008_stage_writer;

-- New policy evidence supersedes earlier versions only when it has been
-- independently verified; old evidence remains immutable audit history.
CREATE OR REPLACE FUNCTION t008_check_publishable(p_candidate UUID)
RETURNS void LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
DECLARE c t008_candidates%ROWTYPE; src RECORD; pol t008_source_policies%ROWTYPE;
BEGIN
 SELECT * INTO c FROM t008_candidates WHERE id=p_candidate;
 IF NOT FOUND OR c.verification <> 'verified' THEN
   RAISE EXCEPTION 'T008 candidate must be verified';
 END IF;
 IF EXISTS(SELECT 1 FROM t008_review_queue WHERE candidate_id=p_candidate AND status='open') THEN
   RAISE EXCEPTION 'T008 unresolved review queue';
 END IF;
 -- Each source/method pair that contributed evidence needs verified title AND artist
 -- under its latest policy version. Earlier versions are retained but not authoritative.
 FOR src IN SELECT DISTINCT source_code,acquisition_method FROM t008_evidence
            WHERE candidate_id=p_candidate
 LOOP
   SELECT * INTO pol FROM t008_source_policies p WHERE p.source_code=src.source_code
   AND p.acquisition_method=src.acquisition_method
   ORDER BY policy_version DESC LIMIT 1;
   IF NOT FOUND OR pol.publication_allowed IS DISTINCT FROM TRUE
      OR NOT t008_policy_storage_ok(pol.id,pol.source_code,pol.acquisition_method)
      OR NOT EXISTS(SELECT 1 FROM t008_evidence e
                    WHERE e.candidate_id=p_candidate
                    AND e.source_policy_id=pol.id AND e.field_name='title'
                    AND e.verification='verified')
      OR NOT EXISTS(SELECT 1 FROM t008_evidence e
                    WHERE e.candidate_id=p_candidate
                    AND e.source_policy_id=pol.id AND e.field_name='artist'
                    AND e.verification='verified')
      OR EXISTS(SELECT 1 FROM t008_evidence e
                WHERE e.candidate_id=p_candidate AND e.source_policy_id=pol.id
                AND e.verification<>'verified')
   THEN RAISE EXCEPTION 'T008 current verified evidence missing for source %',src.source_code;
   END IF;
 END LOOP;
 IF NOT FOUND AND NOT EXISTS(
     SELECT 1 FROM t008_evidence WHERE candidate_id=p_candidate) THEN
   RAISE EXCEPTION 'T008 no evidence';
 END IF;
END $$;

-- Candidate is locked before source-policy advisory keys to give a defined
-- order among review, publication and evidence edits. Source policy INSERT
-- serializes against the same keys even for as-yet-absent new versions.
CREATE OR REPLACE FUNCTION t008_lock_candidate_sources(p_candidate uuid)
RETURNS void LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
DECLARE v RECORD;
BEGIN
 FOR v IN SELECT DISTINCT e.source_code,e.acquisition_method FROM t008_evidence e
          WHERE e.candidate_id=p_candidate
          ORDER BY e.source_code,e.acquisition_method
 LOOP
   PERFORM pg_advisory_xact_lock(hashtextextended(
      't008:policy:'||v.source_code||':'||v.acquisition_method,0));
 END LOOP;
END $$;

-- Append-only approval revisions allow reapproval after refreshed evidence,
-- but never for a preview already published or permanently revoked.
CREATE TABLE t008_approval_revisions (
 candidate_id UUID NOT NULL REFERENCES t008_candidates(id),
 revision INTEGER NOT NULL CHECK(revision > 0),
 content_digest TEXT NOT NULL,
 proof_digest TEXT NOT NULL,
 approved_by TEXT NOT NULL,
 approved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 note TEXT NOT NULL,
 PRIMARY KEY(candidate_id,revision)
);
CREATE TRIGGER t008_approval_revision_immutable
BEFORE UPDATE OR DELETE ON t008_approval_revisions
FOR EACH ROW EXECUTE FUNCTION t008_immutable_rows();

CREATE OR REPLACE FUNCTION t008_approve_candidate(p_candidate UUID,p_note TEXT DEFAULT '')
RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE c t008_candidates%ROWTYPE; latest t008_approval_revisions%ROWTYPE;
        next_revision integer; cd text; ed text;
BEGIN
 SELECT * INTO STRICT c FROM t008_candidates WHERE id=p_candidate FOR UPDATE;
 PERFORM t008_lock_candidate_sources(p_candidate);
 PERFORM t008_check_publishable(p_candidate);
 IF EXISTS(SELECT 1 FROM t008_publication_preview WHERE candidate_id=p_candidate) THEN
  RAISE EXCEPTION 'T008 preview already published or revoked';
 END IF;
 cd:=t008_candidate_digest(p_candidate);
 ed:=t008_proof_digest(p_candidate);
 SELECT * INTO latest FROM t008_approval_revisions
 WHERE candidate_id=p_candidate ORDER BY revision DESC LIMIT 1;
 IF FOUND AND latest.content_digest=cd AND latest.proof_digest=ed THEN
   RAISE EXCEPTION 'T008 approval for this exact evidence already exists';
 END IF;
 next_revision:=coalesce(latest.revision,0)+1;
 IF next_revision=1 THEN
  INSERT INTO t008_approvals(candidate_id,content_digest,proof_digest,approved_by,note)
  VALUES(p_candidate,cd,ed,t008_actor(),p_note);
 END IF;
 INSERT INTO t008_approval_revisions
 (candidate_id,revision,content_digest,proof_digest,approved_by,note)
 VALUES(p_candidate,next_revision,cd,ed,t008_actor(),p_note);
 INSERT INTO t008_audit(batch_id,action,details)
 VALUES(c.batch_id,'approved',jsonb_build_object('actor',t008_actor(),
       'candidate_id',p_candidate,'revision',next_revision));
END $$;

CREATE OR REPLACE FUNCTION t008_publish_preview(p_candidate UUID,p_fail BOOLEAN DEFAULT FALSE)
RETURNS TEXT LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE c t008_candidates%ROWTYPE; a t008_approval_revisions%ROWTYPE; old_state TEXT;
BEGIN
 SELECT * INTO STRICT c FROM t008_candidates WHERE id=p_candidate FOR UPDATE;
 PERFORM t008_lock_candidate_sources(p_candidate);
 PERFORM t008_check_publishable(p_candidate);
 SELECT * INTO a FROM t008_approval_revisions WHERE candidate_id=p_candidate
 ORDER BY revision DESC LIMIT 1;
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
COMMIT;
