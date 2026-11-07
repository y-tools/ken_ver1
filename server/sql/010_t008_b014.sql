-- T008 B-014 disposable test database only.
BEGIN;
DO $$ BEGIN IF current_database() NOT IN ('ken_test','t008_test') THEN
 RAISE EXCEPTION 'T008 B014 forbidden in non-test DB'; END IF; END $$;
-- Explicit approved source-policy versions. CI fixture privileges are isolated:
-- they are not proof of any real third-party commercial-use agreement.
CREATE TABLE t008_policy_authorizations (
 policy_id BIGINT PRIMARY KEY REFERENCES t008_source_policies(id),
 approved_by TEXT NOT NULL CHECK(length(btrim(approved_by))>0),
 scope_method TEXT NOT NULL,
 approved_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TRIGGER t008_policy_auth_immutable BEFORE UPDATE OR DELETE
 ON t008_policy_authorizations FOR EACH ROW EXECUTE FUNCTION t008_immutable_rows();
CREATE OR REPLACE FUNCTION t008_is_fixture_policy(p t008_source_policies)
 RETURNS boolean LANGUAGE sql STABLE SET search_path=pg_catalog,public AS $$
 SELECT (
 p.content_license IN ('test-only','CC0')
 AND lower(btrim(coalesce(p.access_terms,''))) NOT IN
 ('','unknown','undefined','none','null','pending','unreviewed','tbd',
 'n/a','na','not checked','not reviewed','unspecified','不明','未確認','未審査','未定')
 AND (p.source_code='synthetic_fixture'
 OR p.source_code LIKE 'b008_%' OR p.source_code LIKE 'b010_%'
 OR p.source_code LIKE 'b012_%' OR p.source_code LIKE 'pub_%'
 OR p.source_code LIKE 'policyupgrade_%' OR p.source_code LIKE 'policy_race_%'
 OR p.source_code LIKE 'versioned_%' OR p.source_code LIKE 'fixture_private_%')
 ) IS TRUE
$$;
INSERT INTO t008_policy_authorizations(policy_id,approved_by,scope_method)
 SELECT p.id,'ci-fixture-seeded',p.acquisition_method
 FROM t008_source_policies p WHERE t008_is_fixture_policy(p);
CREATE OR REPLACE FUNCTION t008_authorize_fixture_insert() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
 IF t008_is_fixture_policy(NEW) THEN
 INSERT INTO t008_policy_authorizations(policy_id,approved_by,scope_method)
 VALUES(NEW.id,'ci-fixture-insert',NEW.acquisition_method);
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER t008_authorize_fixture_insert AFTER INSERT ON t008_source_policies
 FOR EACH ROW EXECUTE FUNCTION t008_authorize_fixture_insert();
CREATE OR REPLACE FUNCTION t008_policy_storage_ok(p_id BIGINT,p_source TEXT,p_method TEXT)
 RETURNS BOOLEAN LANGUAGE sql STABLE SET search_path=pg_catalog,public AS $$
 SELECT EXISTS(
 SELECT 1 FROM t008_source_policies p
 JOIN t008_policy_authorizations a ON a.policy_id=p.id
 WHERE p.id=p_id AND p.source_code=p_source AND p.acquisition_method=p_method
 AND a.scope_method=p_method
 AND p.automated_access_allowed IS TRUE AND p.storage_allowed IS TRUE
 AND lower(btrim(coalesce(p.content_license,''))) NOT IN
 ('','unknown','undefined','none','null','pending','unreviewed','tbd',
 'n/a','na','not checked','not reviewed','unspecified','不明','未確認','未審査','未定')
 AND lower(btrim(coalesce(p.access_terms,''))) NOT IN
 ('','unknown','undefined','none','null','pending','unreviewed','tbd',
 'n/a','na','not checked','not reviewed','unspecified','不明','未確認','未審査','未定')
 AND p.reviewed_at<=now() AND now()<p.expires_at
 AND p.allowed_fields @> ARRAY['title','artist']::text[]
 AND p.policy_version=(SELECT max(v.policy_version) FROM t008_source_policies v
 WHERE v.source_code=p.source_code AND v.acquisition_method=p.acquisition_method));
$$;
CREATE TABLE t008_reapplications(
 candidate_id UUID PRIMARY KEY REFERENCES t008_candidates(id),
 previous_candidate_id UUID NOT NULL REFERENCES t008_candidates(id),
 requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 CHECK(candidate_id<>previous_candidate_id)
);
CREATE TRIGGER t008_reapplications_immutable BEFORE UPDATE OR DELETE
 ON t008_reapplications FOR EACH ROW EXECUTE FUNCTION t008_immutable_rows();
CREATE OR REPLACE FUNCTION t008_stage_one(
 p_batch UUID,p_title TEXT,p_artist TEXT,p_source TEXT,p_entity_type TEXT,
 p_external_id TEXT,p_policy_id BIGINT,p_content_digest TEXT,p_input_digest TEXT
) RETURNS TEXT LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE pol t008_source_policies%ROWTYPE;
        prior t008_external_claims%ROWTYPE; cid UUID; outcome TEXT; was_revoked boolean := false;
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
 PERFORM pg_advisory_xact_lock(hashtextextended('t008:policy:'||p_source||':'||
    coalesce((SELECT acquisition_method FROM t008_source_policies WHERE id=p_policy_id),''),0));
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
 IF FOUND THEN
   SELECT EXISTS(SELECT 1 FROM t008_publication_preview
     WHERE candidate_id=prior.candidate_id AND state='revoked') INTO was_revoked;
 END IF;
 IF FOUND AND prior.input_digest=expected_content AND NOT was_revoked THEN
   cid=prior.candidate_id;
   outcome='duplicate';
 ELSE
   cid=gen_random_uuid();
   outcome=CASE WHEN was_revoked THEN 'new' WHEN FOUND THEN 'collision' ELSE 'new' END;
   INSERT INTO t008_candidates(id,batch_id,title,artist,title_key,artist_key,
      external_source,external_entity_type,external_id,input_digest,
      source_policy_id,verification)
   VALUES(cid,p_batch,p_title,p_artist,lower(p_title),lower(p_artist),
      p_source,p_entity_type,p_external_id,expected_event,p_policy_id,
      CASE WHEN outcome='collision' OR was_revoked THEN 'review' ELSE 'unverified' END);
   IF was_revoked THEN
      INSERT INTO t008_reapplications(candidate_id,previous_candidate_id)
       VALUES(cid,prior.candidate_id);
      UPDATE t008_external_claims SET candidate_id=cid,input_digest=expected_content
       WHERE source_code=p_source AND entity_type=p_entity_type AND external_id=p_external_id;
      INSERT INTO t008_review_queue(candidate_id,reason)
       VALUES(cid,'reapplication_after_revocation');
   ELSIF outcome='new' THEN
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

COMMIT;
