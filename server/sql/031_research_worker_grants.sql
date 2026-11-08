-- Run as PostgreSQL owner after server/sql/030_ken_research_queue.sql.
-- The unprivileged worker can only append catalog entities and maintain its own queue.
BEGIN;
DO $$
BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='kenresearch') THEN
  CREATE ROLE kenresearch LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
 END IF;
END $$;
GRANT CONNECT ON DATABASE ken_songs TO kenresearch;
GRANT USAGE ON SCHEMA public TO kenresearch;
GRANT SELECT,INSERT ON artists,songs,recordings TO kenresearch;
GRANT SELECT ON artist_names,song_names,source_catalogs,source_song_links TO kenresearch;
GRANT SELECT,INSERT,UPDATE ON ken_research_runs,ken_research_artists,
  ken_research_songs,ken_research_state TO kenresearch;
GRANT SELECT,INSERT ON ken_research_events TO kenresearch;
GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO kenresearch;
REVOKE DELETE,TRUNCATE,REFERENCES,TRIGGER ON artists,songs,recordings,
  ken_research_runs,ken_research_artists,ken_research_songs,ken_research_state,
  ken_research_events FROM kenresearch;
COMMIT;
