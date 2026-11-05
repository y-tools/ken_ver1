-- Per-entity optimistic concurrency & append-only audit of admin changes.
BEGIN;
CREATE TABLE IF NOT EXISTS ken_admin_audit(
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  action TEXT NOT NULL CHECK (action IN ('artist_update','song_update','artist_alias_upsert','song_alias_upsert')),
  entity_type TEXT NOT NULL CHECK (entity_type IN ('artist','song')),
  entity_id BIGINT NOT NULL,
  before_json JSONB NOT NULL,
  after_json JSONB NOT NULL,
  actor TEXT NOT NULL DEFAULT 'admin',
  changed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ken_admin_audit_entity ON ken_admin_audit (entity_type,entity_id,changed_at DESC);
INSERT INTO source_catalogs(code,display_name,source_url,license_id,attribution)
VALUES('ken_admin_manual','Ken admin curated release dates',NULL,'user_editor','User supplied official source URLs')
ON CONFLICT(code) DO NOTHING;
COMMIT;
