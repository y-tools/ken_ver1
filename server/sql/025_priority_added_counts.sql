-- Kenの優先リクエスト: 対応結果の項目を追加
--   表示順: アーティスト / 楽曲名 / メモ / 投稿日 / 対応日 / 追加アーティスト名 / 追加楽曲数 / 完了日時
BEGIN;
ALTER TABLE ken_priority_requests
  ADD COLUMN IF NOT EXISTS added_artist_name TEXT
    CHECK (added_artist_name IS NULL OR length(btrim(added_artist_name)) BETWEEN 1 AND 120),
  ADD COLUMN IF NOT EXISTS added_song_count INTEGER
    CHECK (added_song_count IS NULL OR added_song_count BETWEEN 0 AND 100000);
COMMENT ON COLUMN ken_priority_requests.added_artist_name IS '追加アーティスト名';
COMMENT ON COLUMN ken_priority_requests.added_song_count  IS '追加楽曲数';
DO $$
DECLARE r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['ken_search','kenapi'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('GRANT UPDATE (added_artist_name, added_song_count) ON ken_priority_requests TO %I', r);
    END IF;
  END LOOP;
END $$;
COMMIT;
