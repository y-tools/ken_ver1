-- T008 B-014 individual evidence/issue review with trusted TEST login identity.
-- Disposable environment only. Real app must authenticate and bind unique principals.
BEGIN;
DO $$ BEGIN IF current_database() NOT IN ('ken_test','t008_test') THEN
 RAISE EXCEPTION 'T008 review fixture only'; END IF; END $$;

CREATE TABLE t008_reviewer_principals (
 login_name TEXT PRIMARY KEY,
 reviewer_id TEXT NOT NULL UNIQUE,
 enabled BOOLEAN NOT NULL DEFAULT TRUE
);
INSERT INTO t008_reviewer_principals(login_name,reviewer_id)
VALUES('postgres','CI-REVIEWER-POSTGRES');
CREATE TABLE t008_review_decisions (
 decision_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 candidate_id UUID NOT NULL REFERENCES t008_candidates(id),
 evidence_id BIGINT REFERENCES t008_evidence(id),
 issue_id BIGINT REFERENCES t008_review_queue(id),
 reviewer_id TEXT NOT NULL,
 reason TEXT NOT NULL CHECK(length(btrim(reason))>0),
 decision TEXT NOT NULL CHECK(decision IN ('verified','rejected','resolved','reopened')),
 decided_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 CHECK(((evidence_id IS NOT NULL)::int + (issue_id IS NOT NULL)::int)=1)
);
CREATE TRIGGER t008_review_decisions_immutable BEFORE UPDATE OR DELETE
 ON t008_review_decisions FOR EACH ROW EXECUTE FUNCTION t008_immutable_rows();

CREATE OR REPLACE FUNCTION t008_reviewer_id() RETURNS TEXT
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE rid text;
BEGIN
 SELECT reviewer_id INTO rid FROM t008_reviewer_principals
 WHERE login_name=session_user AND enabled IS TRUE;
 IF rid IS NULL THEN RAISE EXCEPTION 'T008 reviewer login not authorized'; END IF;
 RETURN rid;
END $$;
CREATE OR REPLACE FUNCTION t008_review_evidence(p_evidence BIGINT,p_reason TEXT)
RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE ev t008_evidence%ROWTYPE; rid text;
BEGIN
 rid:=t008_reviewer_id();
 IF nullif(btrim(p_reason),'') IS NULL THEN RAISE EXCEPTION 'T008 reason required'; END IF;
 SELECT * INTO STRICT ev FROM t008_evidence WHERE id=p_evidence;
 PERFORM 1 FROM t008_candidates WHERE id=ev.candidate_id FOR UPDATE;
 IF EXISTS(SELECT 1 FROM t008_publication_preview WHERE candidate_id=ev.candidate_id)
 THEN RAISE EXCEPTION 'T008 preview evidence immutable'; END IF;
 PERFORM set_config('t008.review_reason',p_reason,true);
 UPDATE t008_evidence SET verification='verified' WHERE id=p_evidence;
 INSERT INTO t008_review_decisions(candidate_id,evidence_id,reviewer_id,reason,decision)
 VALUES(ev.candidate_id,p_evidence,rid,p_reason,'verified');
 INSERT INTO t008_audit(batch_id,action,details)
 SELECT c.batch_id,'evidence_reviewed',jsonb_build_object(
 'reviewer_id',rid,'candidate_id',c.id,'evidence_id',p_evidence,'reason',p_reason)
 FROM t008_candidates c WHERE c.id=ev.candidate_id;
END $$;
CREATE OR REPLACE FUNCTION t008_resolve_issue(p_issue BIGINT,p_reason TEXT)
RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE item t008_review_queue%ROWTYPE; rid text;
BEGIN
 rid:=t008_reviewer_id();
 IF nullif(btrim(p_reason),'') IS NULL THEN RAISE EXCEPTION 'T008 reason required'; END IF;
 SELECT * INTO STRICT item FROM t008_review_queue WHERE id=p_issue;
 PERFORM 1 FROM t008_candidates WHERE id=item.candidate_id FOR UPDATE;
 IF EXISTS(SELECT 1 FROM t008_publication_preview WHERE candidate_id=item.candidate_id)
 THEN RAISE EXCEPTION 'T008 preview immutable'; END IF;
 IF item.status<>'open' THEN RAISE EXCEPTION 'T008 issue already resolved'; END IF;
 IF NOT EXISTS(SELECT 1 FROM t008_evidence WHERE candidate_id=item.candidate_id
 AND field_name='title' AND verification='verified')
 OR NOT EXISTS(SELECT 1 FROM t008_evidence WHERE candidate_id=item.candidate_id
 AND field_name='artist' AND verification='verified')
 THEN RAISE EXCEPTION 'T008 individually verified title and artist required'; END IF;
 UPDATE t008_review_queue SET status='resolved' WHERE id=p_issue;
 INSERT INTO t008_review_decisions(candidate_id,issue_id,reviewer_id,reason,decision)
 VALUES(item.candidate_id,p_issue,rid,p_reason,'resolved');
 INSERT INTO t008_audit(batch_id,action,details)
 SELECT c.batch_id,'issue_resolved',jsonb_build_object(
 'reviewer_id',rid,'candidate_id',c.id,'issue_id',p_issue,'reason',p_reason)
 FROM t008_candidates c WHERE c.id=item.candidate_id;
END $$;
CREATE OR REPLACE FUNCTION t008_finalize_review(p_candidate UUID,p_reason TEXT)
RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE rid text;
BEGIN
 rid:=t008_reviewer_id();
 IF nullif(btrim(p_reason),'') IS NULL THEN RAISE EXCEPTION 'T008 reason required'; END IF;
 PERFORM 1 FROM t008_candidates WHERE id=p_candidate FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'T008 candidate missing'; END IF;
 IF EXISTS(SELECT 1 FROM t008_review_queue WHERE candidate_id=p_candidate
 AND status='open') OR EXISTS(SELECT 1 FROM t008_evidence
 WHERE candidate_id=p_candidate AND verification<>'verified')
 THEN RAISE EXCEPTION 'T008 pending item-level review'; END IF;
 PERFORM set_config('t008.review_reason',p_reason,true);
 UPDATE t008_candidates SET verification='verified' WHERE id=p_candidate;
 INSERT INTO t008_audit(batch_id,action,details)
 SELECT batch_id,'review_finalized',jsonb_build_object('reviewer_id',rid,
  'candidate_id',p_candidate,'reason',p_reason)
 FROM t008_candidates WHERE id=p_candidate;
END $$;

-- Existing helper remains only for test fixtures without conflicts; all
-- pending issues need explicit evidence-and-issue decisions.
CREATE OR REPLACE FUNCTION t008_review_mark(p_candidate UUID,p_reason TEXT,
 p_verified BOOLEAN DEFAULT TRUE)
RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM t008_review_queue WHERE candidate_id=p_candidate
 AND status='open') THEN RAISE EXCEPTION 'T008 cannot bulk-resolve open conflicts'; END IF;
 IF nullif(btrim(p_reason),'') IS NULL THEN RAISE EXCEPTION 'T008 reason required'; END IF;
 PERFORM 1 FROM t008_candidates WHERE id=p_candidate FOR UPDATE;
 PERFORM set_config('t008.review_reason',p_reason,true);
 UPDATE t008_candidates SET verification=
 CASE WHEN p_verified THEN 'verified' ELSE 'review' END WHERE id=p_candidate;
 UPDATE t008_evidence SET verification=
 CASE WHEN p_verified THEN 'verified' ELSE 'unverified' END
 WHERE candidate_id=p_candidate;
 IF NOT p_verified THEN
 INSERT INTO t008_review_queue(candidate_id,reason)
 VALUES(p_candidate,'review_reopened:'||left(p_reason,200));
 END IF;
END $$;
REVOKE ALL ON FUNCTION t008_reviewer_id(),t008_review_evidence(BIGINT,TEXT),
 t008_resolve_issue(BIGINT,TEXT),t008_finalize_review(UUID,TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION t008_review_evidence(BIGINT,TEXT),
 t008_resolve_issue(BIGINT,TEXT),t008_finalize_review(UUID,TEXT) TO t008_reviewer;
COMMIT;
