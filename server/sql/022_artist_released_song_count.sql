-- Independently verified count of released, distinct song titles for an artist.
-- This is NOT the count of rows currently imported into Ken's Denmoku.
-- Apply after 020_artist_last_researched_on.sql. Existing artists remain unknown (NULL).
BEGIN;
ALTER TABLE artists
  ADD COLUMN IF NOT EXISTS released_song_count INTEGER,
  ADD COLUMN IF NOT EXISTS released_song_count_source_url TEXT;
ALTER TABLE artists DROP CONSTRAINT IF EXISTS artists_released_song_count_valid;
ALTER TABLE artists ADD CONSTRAINT artists_released_song_count_valid CHECK (
  (released_song_count IS NULL AND released_song_count_source_url IS NULL)
  OR (
    released_song_count IS NOT NULL
    AND released_song_count BETWEEN 0 AND 1000000
    AND released_song_count_source_url IS NOT NULL
    AND length(released_song_count_source_url) <= 600
    AND released_song_count_source_url LIKE 'https://%'
  )
);
COMMENT ON COLUMN artists.released_song_count IS
  'Manually researched number of distinct, officially released song titles; NULL=unverified. Different from COUNT(songs) in this DB.';
COMMENT ON COLUMN artists.released_song_count_source_url IS
  'HTTPS reference supporting the separately researched total of released songs.';
ALTER TABLE ken_admin_audit DROP CONSTRAINT IF EXISTS ken_admin_audit_action_check;
ALTER TABLE ken_admin_audit ADD CONSTRAINT ken_admin_audit_action_check
  CHECK(action IN ('artist_update','song_update','artist_alias_upsert',
                   'song_alias_upsert','artist_research_date_update',
                   'artist_released_song_count_update'));
COMMIT;
