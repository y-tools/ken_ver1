#!/usr/bin/env bash
# Local daily backup (not a substitute for offsite backups).
set -euo pipefail
umask 077
dir=/var/backups/ken-songs
install -d -o kenimport -g kenimport -m 700 "$dir"
stamp="$(date +%Y%m%d-%H%M%S)"
tmp="$dir/.$stamp.dump.partial"
dest="$dir/$stamp.dump"
trap 'rm -f "$tmp"' EXIT
runuser -u kenimport -- pg_dump -Fc --no-owner --no-acl -d ken_songs -f "$tmp"
test -s "$tmp"
mv "$tmp" "$dest"
chown kenimport:kenimport "$dest"
chmod 600 "$dest"
find "$dir" -maxdepth 1 -type f -name '*.dump' -mtime +14 -delete
trap - EXIT
echo "Local backup saved: $dest"
