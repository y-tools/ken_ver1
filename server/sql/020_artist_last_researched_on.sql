-- Artist metadata research tracking (not automatically updated by ordinary edits).
-- Postgres 16+. Run against ken_songs after backup, as database owner.
BEGIN;
ALTER TABLE artists
  ADD COLUMN IF NOT EXISTS last_researched_on DATE;
COMMENT ON COLUMN artists.last_researched_on IS
  'Date on which artist and discography metadata were last investigated (JST calendar date). NULL means unknown/unresearched; not updated on ordinary editor saves.';
-- Existing audit CHECK must recognize the new dedicated research-date action.
ALTER TABLE ken_admin_audit DROP CONSTRAINT IF EXISTS ken_admin_audit_action_check;
ALTER TABLE ken_admin_audit ADD CONSTRAINT ken_admin_audit_action_check
  CHECK(action IN ('artist_update','song_update','artist_alias_upsert',
                   'song_alias_upsert','artist_research_date_update'));
COMMIT;
