-- T008 B-016: lock ordering and immutable published re-acquisition.
-- Disposable synthetic PostgreSQL only; never use as a production migration.
BEGIN;
DO $$ BEGIN IF current_database() NOT IN ('ken_test','t008_test') THEN
 RAISE EXCEPTION 'T008 migration rejected outside test databases'; END IF; END $$;
CREATE TABLE t008_publication_refreshes(
 candidate_id UUID PRIMARY KEY REFERENCES t008_candidates(id),
 previous_candidate_id UUID NOT NULL REFERENCES t008_candidates(id),
 reason TEXT NOT NULL CHECK(reason IN ('content_changed','policy_version_changed')),
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 CHECK(candidate_id<>previous_candidate_id)
);
CREATE TRIGGER t008_publication_refresh_immutable
BEFORE UPDATE OR DELETE ON t008_publication_refreshes
FOR EACH ROW EXECUTE FUNCTION t008_immutable_rows();
CREATE OR REPLACE FUNCTION t008_stage_one(
 p_batch UUID,p_title TEXT,p_artist TEXT,p_source TEXT,p_entity_type TEXT,
 p_external_id TEXT,p_policy_id BIGINT,p_content_digest TEXT,p_input_digest TEXT
) RETURNS TEXT LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE pol t008_source_policies%ROWTYPE;
        prior t008_external_claims%ROWTYPE; cid UUID; outcome TEXT;
        previous_id UUID; previous_policy_id BIGINT; previous_state TEXT;
        has_current_evidence BOOLEAN := FALSE; append_proofs BOOLEAN := TRUE;
        has_prior BOOLEAN := FALSE;
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
 -- Consistent ordering: external-key advisory -> existing candidate row ->
 -- policy advisory -> external-claim row -> evidence/queue.
 -- This is compatible with approve/publish: candidate row -> policy advisory.
 PERFORM pg_advisory_xact_lock(hashtextextended(
   't008:claim:'||p_source||':'||p_entity_type||':'||p_external_id,0));
 SELECT candidate_id INTO previous_id FROM t008_external_claims
 WHERE source_code=p_source AND entity_type=p_entity_type AND external_id=p_external_id;
 IF previous_id IS NOT NULL THEN
   PERFORM 1 FROM t008_candidates WHERE id=previous_id FOR UPDATE;
 END IF;
 -- Never hold a policy lock while waiting for an existing candidate row.
 PERFORM pg_advisory_xact_lock(hashtextextended(
    't008:policy:'||p_source||':'||
    coalesce((SELECT acquisition_method FROM t008_source_policies
              WHERE id=p_policy_id),''),0));
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
 INSERT INTO t008_batches(id) VALUES(p_batch) ON CONFLICT(id) DO NOTHING;
 IF EXISTS(SELECT 1 FROM t008_intake_events
           WHERE batch_id=p_batch AND input_digest=expected_event) THEN
    RETURN 'duplicate';
 END IF;
 SELECT * INTO prior FROM t008_external_claims WHERE source_code=p_source
  AND entity_type=p_entity_type AND external_id=p_external_id FOR UPDATE;
 has_prior:=FOUND;
 IF has_prior AND prior.candidate_id IS DISTINCT FROM previous_id THEN
  RAISE EXCEPTION 'T008 claim changed unexpectedly during serialized intake';
 END IF;
 IF has_prior THEN
  SELECT state INTO previous_state FROM t008_publication_preview
  WHERE candidate_id=prior.candidate_id;
  SELECT source_policy_id INTO previous_policy_id FROM t008_candidates
  WHERE id=prior.candidate_id;
  SELECT EXISTS(SELECT 1 FROM t008_evidence e WHERE
      e.candidate_id=prior.candidate_id AND e.source_policy_id=p_policy_id
      AND e.field_name='title')
   INTO has_current_evidence;
 END IF;
 IF has_prior AND previous_state='published' AND
    prior.input_digest=expected_content AND has_current_evidence THEN
  -- Idempotent re-acquisition: intake event yes, immutable published proof no.
  cid=prior.candidate_id;
  outcome='duplicate';
  append_proofs:=FALSE;
 ELSIF has_prior AND previous_state='revoked' THEN
  -- Prior candidate must remain immutable. Issue a fresh candidate and lineage.
  cid=gen_random_uuid(); outcome='new';
  INSERT INTO t008_candidates(id,batch_id,title,artist,title_key,artist_key,
       external_source,external_entity_type,external_id,input_digest,
       source_policy_id,verification)
   VALUES(cid,p_batch,p_title,p_artist,lower(p_title),lower(p_artist),
       p_source,p_entity_type,p_external_id,expected_event,p_policy_id,'review');
  INSERT INTO t008_reapplications(candidate_id,previous_candidate_id)
   VALUES(cid,prior.candidate_id);
  UPDATE t008_external_claims SET candidate_id=cid,input_digest=expected_content
   WHERE source_code=p_source AND entity_type=p_entity_type AND external_id=p_external_id;
  INSERT INTO t008_review_queue(candidate_id,reason)
   VALUES(cid,'reapplication_after_revocation');
 ELSIF has_prior AND previous_state='published' THEN
  -- New terms or changed content cannot silently modify a published proof.
  cid=gen_random_uuid(); outcome='collision';
  INSERT INTO t008_candidates(id,batch_id,title,artist,title_key,artist_key,
       external_source,external_entity_type,external_id,input_digest,
       source_policy_id,verification)
   VALUES(cid,p_batch,p_title,p_artist,lower(p_title),lower(p_artist),
       p_source,p_entity_type,p_external_id,expected_event,p_policy_id,'review');
  INSERT INTO t008_publication_refreshes(candidate_id,previous_candidate_id,reason)
    VALUES(cid,prior.candidate_id,
      CASE WHEN prior.input_digest<>expected_content THEN 'content_changed'
           ELSE 'policy_version_changed' END);
  UPDATE t008_external_claims SET candidate_id=cid,input_digest=expected_content
   WHERE source_code=p_source AND entity_type=p_entity_type AND external_id=p_external_id;
  INSERT INTO t008_review_queue(candidate_id,reason)
   VALUES(cid,'published_candidate_refresh');
 ELSIF has_prior AND prior.input_digest=expected_content THEN
  cid=prior.candidate_id; outcome='duplicate';
 ELSE
  cid=gen_random_uuid();
  outcome=CASE WHEN has_prior THEN 'collision' ELSE 'new' END;
  INSERT INTO t008_candidates(id,batch_id,title,artist,title_key,artist_key,
       external_source,external_entity_type,external_id,input_digest,
       source_policy_id,verification)
   VALUES(cid,p_batch,p_title,p_artist,lower(p_title),lower(p_artist),
       p_source,p_entity_type,p_external_id,expected_event,p_policy_id,
       CASE WHEN has_prior THEN 'review' ELSE 'unverified' END);
  IF has_prior THEN
    INSERT INTO t008_review_queue(candidate_id,reason)
    VALUES(cid,'external_id_content_conflict');
  ELSE
    INSERT INTO t008_external_claims(source_code,entity_type,external_id,
      candidate_id,input_digest)
    VALUES(p_source,p_entity_type,p_external_id,cid,expected_content);
  END IF;
 END IF;
 INSERT INTO t008_intake_events(batch_id,input_digest,source_code,entity_type,
    external_id,title,artist,outcome,candidate_id,source_policy_id,content_digest)
 VALUES(p_batch,expected_event,p_source,p_entity_type,
    p_external_id,p_title,p_artist,outcome,cid,p_policy_id,expected_content);
 IF append_proofs THEN
 INSERT INTO t008_evidence(candidate_id,field_name,source_code,source_record_id,
   acquisition_method,original_data_hash,source_policy_id)
 VALUES(cid,'title',p_source,p_external_id,pol.acquisition_method,md5(p_title),p_policy_id),
       (cid,'artist',p_source,p_external_id,pol.acquisition_method,md5(p_artist),p_policy_id);
 END IF;
 INSERT INTO t008_audit(batch_id,action,details) VALUES
 (p_batch,'intake_event',jsonb_build_object('actor',t008_actor(),
  'source',p_source,'entity_type',p_entity_type,'outcome',outcome,
  'policy_id',p_policy_id,'event_digest',expected_event));
 RETURN outcome;
END $$;

COMMIT;
