-- Backfill provenance for the existing imports. Safe to run again.
-- Run as the kenimport database owner AFTER the main metadata import.
BEGIN;
INSERT INTO source_song_links(song_id,source_id,external_id,source_title,source_artist)
SELECT r.song_id,src.id,r.musicbrainz_recording_id::text,s.title,a.name
FROM recordings r
JOIN songs s ON s.id=r.song_id
JOIN artists a ON a.id=s.primary_artist_id
JOIN source_catalogs src ON src.code='musicbrainz'
WHERE r.musicbrainz_recording_id IS NOT NULL
ON CONFLICT(source_id,external_id) DO NOTHING;

INSERT INTO release_evidence(song_id,source_id,source_external_id,release_year,precision)
SELECT s.id,s.release_source_id,NULL,s.release_year,'year'
FROM songs s
WHERE s.release_precision='year' AND s.release_source_id IS NOT NULL
AND NOT EXISTS (
  SELECT 1 FROM release_evidence e
  WHERE e.song_id=s.id AND e.source_id=s.release_source_id
    AND e.precision='year' AND e.release_year=s.release_year
);
COMMIT;
