-- T008 disposable role proof. Never run on the production VPS without DBA review.
BEGIN;
DO $$
BEGIN
 IF current_database() NOT IN ('ken_test','t008_test') THEN
  RAISE EXCEPTION 'T008 role setup restricted to disposable databases';
 END IF;
END $$;
DO $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='t008_stage_writer') THEN
  CREATE ROLE t008_stage_writer NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
 END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='t008_reviewer') THEN
  CREATE ROLE t008_reviewer NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
 END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='t008_publisher') THEN
  CREATE ROLE t008_publisher NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
 END IF;
END $$;
GRANT USAGE ON SCHEMA public TO t008_stage_writer,t008_reviewer,t008_publisher;
GRANT SELECT ON t008_source_policies TO t008_stage_writer,t008_reviewer,t008_publisher;
GRANT SELECT,INSERT ON t008_batches,t008_candidates,t008_evidence,
 t008_review_queue,t008_external_claims,t008_intake_events TO t008_stage_writer;
GRANT USAGE,SELECT ON SEQUENCE t008_evidence_id_seq,t008_review_queue_id_seq,
 t008_intake_events_id_seq TO t008_stage_writer;
GRANT EXECUTE ON FUNCTION t008_stage_audit(UUID,JSONB) TO t008_stage_writer;
GRANT SELECT ON t008_candidates,t008_evidence,t008_review_queue,t008_approvals,
 t008_publication_preview TO t008_reviewer,t008_publisher;
GRANT UPDATE(verification) ON t008_candidates,t008_evidence TO t008_reviewer;
GRANT UPDATE(status) ON t008_review_queue TO t008_reviewer;
GRANT EXECUTE ON FUNCTION t008_approve_candidate(UUID,TEXT) TO t008_reviewer;
GRANT EXECUTE ON FUNCTION t008_publish_preview(UUID,BOOLEAN),
 t008_revoke_preview(UUID) TO t008_publisher;
-- PostgreSQL PUBLIC is not allowed to call security definer functions;
-- legacy tables are deliberately never granted here.
COMMIT;
