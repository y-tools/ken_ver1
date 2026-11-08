#!/usr/bin/env bash
set -euo pipefail
db=ken_bz_restore_check_20261108
dump=/tmp/ken_songs_bz_preimport_20261108.dump
if [ ! -f "$dump" ]; then echo "ERROR: backup missing"; exit 2; fi
pg_restore -l "$dump" >/dev/null
if psql -At -d postgres -c "select 1 from pg_database where datname='$db'" | grep -q 1; then
  echo "ERROR: restore check database already exists"; exit 3
fi
createdb -T template0 "$db"
echo "RESTORE_START"
if nice -n 12 pg_restore --no-owner --no-privileges -e -d "$db" "$dump" >/tmp/ken_bz_restore_output.log 2>&1; then
    counts=$(psql -At -d "$db" -c "select (select count(*) from songs), (select count(*) from artists), (select count(*) from recordings)")
    echo "RESTORE_COUNTS $counts"
    if [ "$counts" = "1999983|125068|1700000" ]; then
      echo "RESTORE_VERIFIED PASS"
      dropdb "$db"
    else
      echo "RESTORE_VERIFIED FAIL (count mismatch), leaving test DB for inspection"
      exit 4
    fi
else
    echo "RESTORE_FAILED"
    tail -n 15 /tmp/ken_bz_restore_output.log
    exit 5
fi
