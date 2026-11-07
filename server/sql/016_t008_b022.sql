-- B-022: wall-clock license checks and serialized reconciliation (disposable PG only).
BEGIN;
DO $$BEGIN
 IF current_database() NOT IN ('ken_test','t008_test','t008_upgrade') THEN
 RAISE EXCEPTION 'B-022 disposable database only'; END IF;
END$$;
-- clock_timestamp() must be evaluated per statement, not fixed to
-- the transaction start; function volatility must reflect that.
CREATE OR REPLACE FUNCTION t008_policy_storage_ok(p_id BIGINT,p_source TEXT,p_method TEXT)
RETURNS BOOLEAN LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
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
 AND p.reviewed_at<=clock_timestamp() AND clock_timestamp()<p.expires_at
 AND p.allowed_fields @> ARRAY['title','artist']::text[]
 AND p.policy_version=(SELECT max(v.policy_version) FROM t008_source_policies v
  WHERE v.source_code=p.source_code AND v.acquisition_method=p.acquisition_method));
$$;
-- Same global locking order: external key -> candidate -> source policy -> pointer.
CREATE OR REPLACE FUNCTION t008_reconcile_visibility(p_candidate UUID)
RETURNS TEXT LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE c t008_candidates%ROWTYPE; active_id UUID;
BEGIN
 SELECT * INTO STRICT c FROM t008_candidates WHERE id=p_candidate;
 PERFORM pg_advisory_xact_lock(hashtextextended(
 't008:claim:'||c.external_source||':'||c.external_entity_type||':'||c.external_id,0));
 PERFORM 1 FROM t008_candidates WHERE id=p_candidate FOR UPDATE;
 -- Wait for all in-flight policy inserts and reacquire current policy facts
 -- before making an irreversible revoke decision.
 PERFORM t008_lock_candidate_sources(p_candidate);
 SELECT candidate_id INTO active_id FROM t008_active_publications
 WHERE source_code=c.external_source AND entity_type=c.external_entity_type
 AND external_id=c.external_id FOR UPDATE;
 IF active_id IS DISTINCT FROM p_candidate THEN RETURN 'not_active'; END IF;
 IF EXISTS(SELECT 1 FROM t008_visible_publications WHERE candidate_id=p_candidate)
 THEN RETURN 'visible'; END IF;
 DELETE FROM t008_active_publications WHERE source_code=c.external_source
 AND entity_type=c.external_entity_type AND external_id=c.external_id;
 UPDATE t008_publication_preview SET state='revoked',revoked_at=clock_timestamp()
 WHERE candidate_id=p_candidate AND state='published';
 INSERT INTO t008_publication_history(source_code,entity_type,external_id,candidate_id,
 preceding_id,action,actor) VALUES(c.external_source,c.external_entity_type,c.external_id,
 p_candidate,p_candidate,'revoke',t008_actor());
 INSERT INTO t008_audit(batch_id,action,details) VALUES(c.batch_id,'license_visibility_revoked',
 jsonb_build_object('candidate_id',p_candidate,'actor',t008_actor()));
 RETURN 'revoked';
END $$;
COMMIT;
