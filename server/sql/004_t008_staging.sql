-- T008 Phase 0: ADDITIVE staging schema. Apply ONLY to disposable PostgreSQL.
-- Never modifies songs/artists/recordings or the legacy importer.
BEGIN;
CREATE TABLE IF NOT EXISTS t008_source_policies (
 id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 source_code TEXT NOT NULL,
 acquisition_method TEXT NOT NULL,
 content_license TEXT NOT NULL,
 access_terms TEXT NOT NULL,
 allowed_fields TEXT[] NOT NULL DEFAULT '{}',
 automated_access_allowed BOOLEAN NOT NULL DEFAULT FALSE,
 storage_allowed BOOLEAN NOT NULL DEFAULT FALSE,
 publication_allowed BOOLEAN NOT NULL DEFAULT FALSE,
 reviewed_at TIMESTAMPTZ,
 UNIQUE(source_code,acquisition_method)
);
CREATE TABLE IF NOT EXISTS t008_batches (
 id UUID PRIMARY KEY,
 status TEXT NOT NULL DEFAULT 'staging'
  CHECK(status IN ('staging','review','approved','rejected','rolled_back')),
 started_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS t008_candidates (
 id UUID PRIMARY KEY,
 batch_id UUID NOT NULL REFERENCES t008_batches(id),
 title TEXT NOT NULL,
 artist TEXT NOT NULL,
 title_key TEXT NOT NULL,
 artist_key TEXT NOT NULL,
 external_source TEXT,
 external_entity_type TEXT CHECK(external_entity_type IN ('work','recording','release')),
 external_id TEXT,
 verification TEXT NOT NULL DEFAULT 'unverified'
  CHECK(verification IN ('unverified','review','verified','rejected')),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS t008_candidates_match ON t008_candidates(title_key,artist_key);
CREATE INDEX IF NOT EXISTS t008_candidates_review ON t008_candidates(verification,batch_id);
CREATE TABLE IF NOT EXISTS t008_evidence (
 id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 candidate_id UUID NOT NULL REFERENCES t008_candidates(id),
 field_name TEXT NOT NULL,
 source_code TEXT NOT NULL,
 source_record_id TEXT,
 acquisition_method TEXT NOT NULL,
 original_data_hash TEXT NOT NULL,
 source_url TEXT,
 original_evidence_id BIGINT REFERENCES t008_evidence(id),
 transform_name TEXT,
 verification TEXT NOT NULL DEFAULT 'unverified',
 captured_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS t008_review_queue (
 id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 candidate_id UUID NOT NULL REFERENCES t008_candidates(id),
 reason TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','resolved')),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS t008_recording_works (
 recording_external_id TEXT NOT NULL,
 work_external_id TEXT NOT NULL,
 source_code TEXT NOT NULL,
 relation_type TEXT NOT NULL,
 PRIMARY KEY(source_code,recording_external_id,work_external_id,relation_type)
);
CREATE TABLE IF NOT EXISTS t008_audit (
 id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 batch_id UUID REFERENCES t008_batches(id),
 action TEXT NOT NULL,
 details JSONB NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- No promotion function, trigger, view, or automatic legacy merge is intentionally created.
COMMIT;
