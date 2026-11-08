-- Artist metadata research tracking (not automatically updated by ordinary edits).
-- Postgres 16+. Run against ken_songs after backup, as database owner.
BEGIN;
ALTER TABLE artists
  ADD COLUMN IF NOT EXISTS last_researched_on DATE;
COMMENT ON COLUMN artists.last_researched_on IS
  'Date on which artist and discography metadata were last investigated (JST calendar date). NULL means unknown/unresearched; not updated on ordinary editor saves.';
COMMIT;
