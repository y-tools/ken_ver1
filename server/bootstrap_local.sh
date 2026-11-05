#!/usr/bin/env bash
# Idempotent VPS-only setup; intentionally does not modify Minecraft, Caddy or the firewall.
set -euo pipefail
if [[ "$(id -u)" -ne 0 ]]; then echo 'Run as root' >&2; exit 1; fi
command -v psql >/dev/null
command -v runuser >/dev/null
pg_isready -q -h 127.0.0.1 || { echo 'Local PostgreSQL unavailable' >&2; exit 1; }
[[ "$(runuser -u postgres -- psql -Atc 'SHOW listen_addresses')" == 'localhost' ]] || { echo 'PostgreSQL must be localhost-only' >&2; exit 1; }
for user in kenapi kenimport; do
  if ! id "$user" >/dev/null 2>&1; then
    useradd --system --no-create-home --shell /usr/sbin/nologin "$user"
  fi
  if [[ "$(runuser -u postgres -- psql -Atc "SELECT 1 FROM pg_roles WHERE rolname='$user'")" != '1' ]]; then
    runuser -u postgres -- psql -v ON_ERROR_STOP=1 -c "CREATE ROLE $user LOGIN"
  fi
done
if [[ "$(runuser -u postgres -- psql -Atc "SELECT 1 FROM pg_database WHERE datname='ken_songs'")" != '1' ]]; then
  runuser -u postgres -- createdb -O kenimport ken_songs
fi
runuser -u kenimport -- psql -v ON_ERROR_STOP=1 -d ken_songs -f /opt/ken-song-api/server/sql/001_init.sql
runuser -u postgres -- psql -v ON_ERROR_STOP=1 -d ken_songs <<'SQL'
REVOKE ALL ON DATABASE ken_songs FROM PUBLIC;
GRANT CONNECT ON DATABASE ken_songs TO kenapi;
GRANT CONNECT ON DATABASE ken_songs TO kenimport;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO kenapi;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO kenapi;
ALTER DEFAULT PRIVILEGES FOR ROLE kenimport IN SCHEMA public GRANT SELECT ON TABLES TO kenapi;
ALTER ROLE kenapi IN DATABASE ken_songs SET default_transaction_read_only=on;
ALTER ROLE kenapi IN DATABASE ken_songs SET statement_timeout='3s';
SQL
runuser -u kenapi -- psql -d ken_songs -v ON_ERROR_STOP=1 -Atc 'SELECT COUNT(*) FROM songs' >/dev/null
echo 'Ken song DB schema and read-only API role ready'
