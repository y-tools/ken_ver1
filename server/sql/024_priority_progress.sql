-- Kenの優先リクエスト: 項目 = アーティスト / 楽曲名 / メモ / 投稿日 / 対応日 / 完了日時
--   artist_name / song_title / note / created_at(投稿日) / handled_at(対応日) / completed_at(完了日時)
-- 状態: requested(リクエスト済み) → in_progress(対応中) → done(対応完了)
-- 対応完了のものは管理画面の×で消し込み(cleared_at)。行は削除せず一覧から外す。
BEGIN;
ALTER TABLE ken_priority_requests
  ADD COLUMN IF NOT EXISTS handled_at   TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS cleared_at   TIMESTAMPTZ;
UPDATE ken_priority_requests SET status='done', completed_at=coalesce(completed_at, updated_at)
 WHERE status='registered';
ALTER TABLE ken_priority_requests DROP CONSTRAINT IF EXISTS ken_priority_requests_status_check;
ALTER TABLE ken_priority_requests ADD CONSTRAINT ken_priority_requests_status_check
  CHECK (status IN ('requested','in_progress','done','rejected'));
ALTER TABLE ken_priority_requests DROP CONSTRAINT IF EXISTS ken_priority_requests_clear_only_done;
ALTER TABLE ken_priority_requests ADD CONSTRAINT ken_priority_requests_clear_only_done
  CHECK (cleared_at IS NULL OR status = 'done');
COMMENT ON COLUMN ken_priority_requests.created_at   IS '投稿日';
COMMENT ON COLUMN ken_priority_requests.handled_at   IS '対応日';
COMMENT ON COLUMN ken_priority_requests.completed_at IS '完了日時';
COMMENT ON COLUMN ken_priority_requests.cleared_at   IS '管理画面で消し込んだ日時（一覧から非表示）';
DROP INDEX IF EXISTS ken_priority_requests_open_unique;
CREATE UNIQUE INDEX ken_priority_requests_open_unique
  ON ken_priority_requests (kind, lower(btrim(artist_name)), lower(btrim(coalesce(song_title,''))))
  WHERE status IN ('requested','in_progress');
DO $$
DECLARE r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['ken_search','kenapi'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('GRANT UPDATE (status, handled_at, completed_at, cleared_at, updated_at) ON ken_priority_requests TO %I', r);
    END IF;
  END LOOP;
END $$;
COMMIT;
