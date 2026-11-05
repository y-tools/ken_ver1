#!/usr/bin/env bash
set -euo pipefail
if [[ "$(id -u)" -ne 0 ]]; then echo 'Run as root' >&2; exit 1; fi
cd /opt/ken-song-api
test -f server/sql/003_admin_editor.sql
test -x .venv/bin/python
if ! id keneditor >/dev/null 2>&1; then
 useradd --system --no-create-home --shell /usr/sbin/nologin keneditor
fi
if [[ "$(runuser -u postgres -- psql -Atc \"SELECT 1 FROM pg_roles WHERE rolname='keneditor'\")" != '1' ]]; then
 runuser -u postgres -- psql -v ON_ERROR_STOP=1 -c 'CREATE ROLE keneditor LOGIN'
fi
runuser -u kenimport -- psql -d ken_songs -v ON_ERROR_STOP=1 -f server/sql/003_admin_editor.sql
runuser -u postgres -- psql -d ken_songs -v ON_ERROR_STOP=1 <<'SQL'
GRANT CONNECT ON DATABASE ken_songs TO keneditor;
GRANT USAGE ON SCHEMA public TO keneditor;
GRANT SELECT ON artists,songs,artist_names,song_names,source_catalogs,ken_admin_audit TO keneditor;
GRANT UPDATE ON artists,songs TO keneditor;
GRANT INSERT,UPDATE ON artist_names,song_names TO keneditor;
GRANT INSERT ON release_evidence,ken_admin_audit TO keneditor;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO keneditor;
SQL
runuser -u keneditor -- psql -d ken_songs -v ON_ERROR_STOP=1 -Atc 'SELECT COUNT(*) FROM songs' >/dev/null
if [[ ! -f /etc/ken-song-admin.env ]]; then
 .venv/bin/python - <<'PY'
from pathlib import Path
import secrets
from argon2 import PasswordHasher
secret=secrets.token_urlsafe(30)
hashed=PasswordHasher().hash(secret)
path=Path('/root/ken-song-editor-initial-password.txt')
with path.open('x') as f: f.write(secret+'\n')
path.chmod(0o600)
env=Path('/etc/ken-song-admin.env')
with env.open('x') as f:
 f.write('KEN_ADMIN_DATABASE_URL=postgresql:///ken_songs?host=/var/run/postgresql\n')
 f.write('KEN_ALLOWED_ORIGINS=https://y-tools.github.io\n')
 f.write("KEN_ADMIN_PASSWORD_HASH='"+hashed+"'\n")
env.chmod(0o600)
PY
fi
install -o root -g root -m 644 server/ken-song-admin.service /etc/systemd/system/ken-song-admin.service
systemctl daemon-reload
systemctl enable --now ken-song-admin
systemctl is-active --quiet ken-song-admin
echo 'Dedicated editor API service is active (credentials kept on VPS)'
