-- T008 B-016 individual issue resolution row locking, disposable test DB only.
BEGIN;
DO $$ BEGIN IF current_database() NOT IN ('ken_test','t008_test') THEN
 RAISE EXCEPTION 'T008 migration restricted to test database'; END IF; END $$;
CREATE OR REPLACE FUNCTION t008_resolve_issue(p_issue BIGINT,p_reason TEXT)
RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE item t008_review_queue%ROWTYPE; rid text;
BEGIN
 rid:=t008_reviewer_id();
 IF nullif(btrim(p_reason),'') IS NULL THEN RAISE EXCEPTION 'T008 reason required'; END IF;
 SELECT candidate_id INTO STRICT item.candidate_id FROM t008_review_queue WHERE id=p_issue;
 PERFORM 1 FROM t008_candidates WHERE id=item.candidate_id FOR UPDATE;
 SELECT * INTO STRICT item FROM t008_review_queue WHERE id=p_issue FOR UPDATE;
 IF EXISTS(SELECT 1 FROM t008_publication_preview WHERE candidate_id=item.candidate_id)
 THEN RAISE EXCEPTION 'T008 preview immutable'; END IF;
 IF item.status<>'open' THEN RAISE EXCEPTION 'T008 issue already resolved'; END IF;
 IF NOT EXISTS(SELECT 1 FROM t008_evidence WHERE candidate_id=item.candidate_id
 AND field_name='title' AND verification='verified')
 OR NOT EXISTS(SELECT 1 FROM t008_evidence WHERE candidate_id=item.candidate_id
 AND field_name='artist' AND verification='verified')
 THEN RAISE EXCEPTION 'T008 individually verified title and artist required'; END IF;
 UPDATE t008_review_queue SET status='resolved' WHERE id=p_issue AND status='open';
 IF NOT FOUND THEN RAISE EXCEPTION 'T008 issue was concurrently resolved'; END IF;
 INSERT INTO t008_review_decisions(candidate_id,issue_id,reviewer_id,reason,decision)
 VALUES(item.candidate_id,p_issue,rid,p_reason,'resolved');
 INSERT INTO t008_audit(batch_id,action,details)
 SELECT c.batch_id,'issue_resolved',jsonb_build_object(
 'reviewer_id',rid,'candidate_id',c.id,'issue_id',p_issue,'reason',p_reason)
 FROM t008_candidates c WHERE c.id=item.candidate_id;
END $$;

COMMIT;
