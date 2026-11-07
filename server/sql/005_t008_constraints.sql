-- T008 B-006 hardening of isolated Phase 0 schema; disposable DB only.
BEGIN;
ALTER TABLE t008_source_policies ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;
ALTER TABLE t008_source_policies ADD CONSTRAINT t008_policy_review_window
 CHECK (reviewed_at IS NULL OR expires_at IS NULL OR expires_at > reviewed_at);
ALTER TABLE t008_evidence ADD COLUMN source_policy_id BIGINT REFERENCES t008_source_policies(id);
ALTER TABLE t008_evidence ADD COLUMN original_candidate_id UUID;
ALTER TABLE t008_evidence ADD CONSTRAINT t008_evidence_parent_match CHECK
 (original_evidence_id IS NULL OR original_candidate_id = candidate_id);
ALTER TABLE t008_evidence ADD CONSTRAINT t008_evidence_parent_pair CHECK
 ((original_evidence_id IS NULL AND original_candidate_id IS NULL)
 OR (original_evidence_id IS NOT NULL AND original_candidate_id IS NOT NULL));
ALTER TABLE t008_evidence ADD CONSTRAINT t008_evidence_id_candidate UNIQUE (id,candidate_id);
ALTER TABLE t008_evidence ADD CONSTRAINT t008_evidence_parent_fk
 FOREIGN KEY(original_evidence_id,original_candidate_id)
 REFERENCES t008_evidence(id,candidate_id);
ALTER TABLE t008_evidence ALTER COLUMN source_policy_id SET NOT NULL;
ALTER TABLE t008_candidates ADD COLUMN IF NOT EXISTS input_digest TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS t008_candidates_source_record_once
 ON t008_candidates(batch_id,external_source,external_entity_type,external_id)
 WHERE external_source IS NOT NULL AND external_entity_type IS NOT NULL AND external_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS t008_candidates_batch_payload_once
 ON t008_candidates(batch_id,input_digest) WHERE input_digest IS NOT NULL;
-- Evidence rows are restricted to a declared matching source and access method.
CREATE OR REPLACE FUNCTION t008_enforce_evidence_source() RETURNS trigger
 LANGUAGE plpgsql AS $$
 DECLARE pol t008_source_policies%ROWTYPE;
 BEGIN
  SELECT * INTO pol FROM t008_source_policies WHERE id=NEW.source_policy_id;
  IF NOT FOUND OR pol.source_code IS DISTINCT FROM NEW.source_code
    OR pol.acquisition_method IS DISTINCT FROM NEW.acquisition_method THEN
    RAISE EXCEPTION 'T008 evidence source policy mismatch';
  END IF;
  IF NEW.original_evidence_id IS NOT NULL AND NEW.original_evidence_id >= NEW.id THEN
    RAISE EXCEPTION 'T008 evidence ancestry must precede derived evidence';
  END IF;
  RETURN NEW;
 END $$;
CREATE TRIGGER t008_evidence_source_guard BEFORE INSERT OR UPDATE ON t008_evidence
 FOR EACH ROW EXECUTE FUNCTION t008_enforce_evidence_source();
-- Staging role provisioned separately by a DBA; no production grants included.
COMMIT;
