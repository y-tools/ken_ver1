-- Kenの優先リクエスト: 管理画面から登録する「優先して調査・登録してほしい」楽曲/アーティスト。
-- 楽曲カタログ(songs/artists)とは別テーブル。検索API(ken_search)はこの表だけに追記できる。
BEGIN;
CREATE TABLE IF NOT EXISTS ken_priority_requests (
  id            BIGSERIAL PRIMARY KEY,
  kind          TEXT NOT NULL CHECK (kind IN ('song','artist')),
  artist_name   TEXT NOT NULL CHECK (length(btrim(artist_name)) BETWEEN 1 AND 120),
  song_title    TEXT CHECK (song_title IS NULL OR length(btrim(song_title)) BETWEEN 1 AND 120),
  note          TEXT NOT NULL DEFAULT '' CHECK (length(note) <= 300),
  status        TEXT NOT NULL DEFAULT 'requested' CHECK (status IN ('requested','registered','rejected')),
  requested_by  TEXT NOT NULL DEFAULT '' CHECK (length(requested_by) <= 80),
  requested_uid UUID,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ken_priority_requests_song_needs_title CHECK (
    (kind = 'song' AND song_title IS NOT NULL) OR (kind = 'artist' AND song_title IS NULL)
  )
);
COMMENT ON TABLE ken_priority_requests IS 'Kenの優先リクエスト（優先楽曲登録・優先アーティストリクエスト）';
CREATE INDEX IF NOT EXISTS ken_priority_requests_created_idx ON ken_priority_requests (created_at DESC);
-- 同じ内容の未処理リクエストは1件にまとめる
CREATE UNIQUE INDEX IF NOT EXISTS ken_priority_requests_open_unique
  ON ken_priority_requests (kind, lower(btrim(artist_name)), lower(btrim(coalesce(song_title,''))))
  WHERE status = 'requested';
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ken_search') THEN
    GRANT SELECT, INSERT ON ken_priority_requests TO ken_search;
    GRANT USAGE ON SEQUENCE ken_priority_requests_id_seq TO ken_search;
  END IF;
END $$;
COMMIT;
