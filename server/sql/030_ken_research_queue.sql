-- Ken daily research queue. All records are non-public until the guarded worker promotes them.
-- Idempotent; use psql -v ON_ERROR_STOP=1 -f on a backed-up PostgreSQL database.
BEGIN;
CREATE TABLE IF NOT EXISTS ken_research_runs (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  lane TEXT NOT NULL CHECK(lane IN ('artists','songs')),
  status TEXT NOT NULL DEFAULT 'running' CHECK(status IN ('running','succeeded','failed')),
  discovered INT NOT NULL DEFAULT 0,
  staged INT NOT NULL DEFAULT 0,
  promoted INT NOT NULL DEFAULT 0,
  error TEXT,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ken_research_runs_recent ON ken_research_runs(started_at DESC);
CREATE TABLE IF NOT EXISTS ken_research_artists (
  artist_mbid UUID PRIMARY KEY,
  name TEXT NOT NULL CHECK(length(btrim(name)) BETWEEN 1 AND 200),
  country TEXT,
  artist_type TEXT,
  source_url TEXT NOT NULL,
  wikidata_qid TEXT,
  official_url TEXT,
  source_count SMALLINT NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'candidate' CHECK(status IN
    ('candidate','review','verified','registered','rejected')),
  master_artist_id BIGINT REFERENCES artists(id) ON DELETE SET NULL,
  review_reason TEXT,
  first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_checked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  registered_at TIMESTAMPTZ,
  CHECK (master_artist_id IS NULL OR status='registered')
);
CREATE INDEX IF NOT EXISTS ken_research_artist_queue ON ken_research_artists(status,last_checked_at);
CREATE TABLE IF NOT EXISTS ken_research_songs (
  recording_mbid UUID PRIMARY KEY,
  artist_mbid UUID NOT NULL REFERENCES ken_research_artists(artist_mbid),
  title TEXT NOT NULL CHECK(length(btrim(title)) BETWEEN 1 AND 300),
  source_url TEXT NOT NULL,
  first_release_date TEXT,
  artist_credit_verified BOOLEAN NOT NULL DEFAULT false,
  work_mbid UUID,
  status TEXT NOT NULL DEFAULT 'candidate' CHECK(status IN
    ('candidate','review','verified','registered','rejected')),
  master_song_id BIGINT REFERENCES songs(id) ON DELETE SET NULL,
  review_reason TEXT,
  first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_checked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  registered_at TIMESTAMPTZ,
  CHECK (master_song_id IS NULL OR status='registered')
);
CREATE INDEX IF NOT EXISTS ken_research_song_queue ON ken_research_songs(artist_mbid,status,last_checked_at);
CREATE TABLE IF NOT EXISTS ken_research_state (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS ken_research_events (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  lane TEXT NOT NULL CHECK(lane IN ('artists','songs')),
  item_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  detail JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ken_research_events_recent ON ken_research_events(created_at DESC);
-- Local systemd worker will use a dedicated restricted Postgres role.
-- No privileges are granted to public read-only search users.
REVOKE ALL ON ken_research_runs,ken_research_artists,ken_research_songs,
    ken_research_state,ken_research_events FROM PUBLIC;
COMMIT;
