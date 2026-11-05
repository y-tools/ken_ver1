#!/usr/bin/env python3
"""Manually verified official song and artist names.

Input UTF-8 CSV columns:
title,artist,target,kind,value,source_url

target = title|artist, kind = hiragana|katakana|romaji|english.
This command never generates English translations or guesses pronunciations.
Default is dry run; --apply requires --reviewer. Use VPS peer-auth credentials.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import psycopg

from import_catalog import normalize


def load_entries(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"title", "artist", "target", "kind", "value", "source_url"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("CSV requires " + ", ".join(sorted(required)))
        items = []
        for line, row in enumerate(reader, start=2):
            title = (row["title"] or "").strip()
            artist = (row["artist"] or "").strip()
            target = (row["target"] or "").strip()
            kind = (row["kind"] or "").strip()
            value = (row["value"] or "").strip()
            url = (row["source_url"] or "").strip()
            if target not in {"title", "artist"} or kind not in {"hiragana", "katakana", "romaji", "english"}:
                raise ValueError(f"Line {line}: bad target/kind")
            if not title or not artist or not value or len(value)>300:
                raise ValueError(f"Line {line}: missing/oversized title, artist or value")
            parts=urlparse(url)
            if parts.scheme!="https" or not parts.netloc or parts.username or parts.password:
                raise ValueError(f"Line {line}: source_url must be an official HTTPS page")
            items.append({"title":title,"artist":artist,"target":target,"kind":kind,"value":value,"url":url})
        return items


def apply(conn, items, reviewer, commit):
    found=0
    missing=[]
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO source_catalogs(code,display_name,source_url,license_id,attribution)
                           VALUES('official_reviewed','Manually checked official artist/label sources',
                                  NULL,'source_reference','Official source URLs stored per alias')
                           ON CONFLICT(code) DO UPDATE SET display_name=EXCLUDED.display_name
                           RETURNING id""")
            source_id=cur.fetchone()[0]
            for row in items:
                cur.execute("""SELECT s.id,a.id FROM songs s JOIN artists a ON a.id=s.primary_artist_id
                               WHERE s.title_key=%s AND a.name_key=%s""",
                            (normalize(row["title"]),normalize(row["artist"])))
                record=cur.fetchone()
                if not record:
                    missing.append(f'{row["title"]} / {row["artist"]}')
                    continue
                song_id,artist_id=record
                table="song_names" if row["target"]=="title" else "artist_names"
                id_col="song_id" if row["target"]=="title" else "artist_id"
                entity_id=song_id if row["target"]=="title" else artist_id
                # Never overwrite a different spelling. Keep alternative readings
                # side-by-side, each with its own verified source and reviewer.
                cur.execute(
                    f"""INSERT INTO {table}
                         ({id_col},kind,value,search_key,verification,source_id,source_url,checked_at,reviewed_by)
                         VALUES(%s,%s,%s,%s,'source_confirmed',%s,%s,%s,%s)
                         ON CONFLICT({id_col},kind,search_key)
                         DO UPDATE SET verification='source_confirmed',
                                       source_id=EXCLUDED.source_id,
                                       source_url=EXCLUDED.source_url,
                                       checked_at=EXCLUDED.checked_at,
                                       reviewed_by=EXCLUDED.reviewed_by""",
                    (entity_id,row["kind"],row["value"],normalize(row["value"]),
                     source_id,row["url"],datetime.now(timezone.utc),reviewer)
                )
                found+=1
        if not commit:
            conn.rollback()
    return found, missing


def main():
    p=argparse.ArgumentParser()
    p.add_argument("csv_file",type=Path)
    p.add_argument("--reviewer",required=True,help="Human reviewer, not an AI model")
    p.add_argument("--apply",action="store_true",help="Actually commit; otherwise dry run")
    args=p.parse_args()
    items=load_entries(args.csv_file)
    dsn=os.getenv("KEN_IMPORT_DATABASE_URL")
    if not dsn:
        p.error("Set KEN_IMPORT_DATABASE_URL on the VPS (do not commit credentials)")
    with psycopg.connect(dsn) as conn:
        matched,missing=apply(conn,items,args.reviewer,args.apply)
    print(f"Verified candidate rows: {len(items)}; matched: {matched}; not found: {len(missing)}")
    if missing:
        for label in missing[:20]:print("NOT FOUND:",label)
    print("COMMITTED" if args.apply else "DRY RUN; no changes saved")
    if missing:
        sys.exit(2)


if __name__=="__main__":
    main()
