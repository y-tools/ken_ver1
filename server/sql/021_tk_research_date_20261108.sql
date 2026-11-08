-- Record the date of the completed TK from 凛として時雨 research.
-- Safe to rerun: does not overwrite a different existing research date.
BEGIN;
DO $$
DECLARE
  artist_record RECORD;
BEGIN
  SELECT id,name,last_researched_on
    INTO artist_record
    FROM artists WHERE id=643167 FOR UPDATE;
  IF artist_record.id IS NULL OR artist_record.name <> 'TK from 凛として時雨' THEN
    RAISE EXCEPTION 'TK artist id/name mismatch; cancel';
  END IF;
  IF artist_record.last_researched_on IS NULL THEN
    UPDATE artists
      SET last_researched_on=DATE '2026-11-08',updated_at=now()
      WHERE id=643167;
    INSERT INTO ken_admin_audit(action,entity_type,entity_id,before_json,after_json,actor)
      VALUES('artist_research_date_update','artist',643167,
        '{"lastResearchedOn":null}'::jsonb,
        '{"lastResearchedOn":"2026-11-08"}'::jsonb,'research-import');
  ELSIF artist_record.last_researched_on <> DATE '2026-11-08' THEN
    RAISE EXCEPTION 'A different research date already exists: %',artist_record.last_researched_on;
  END IF;
END
$$;
COMMIT;
