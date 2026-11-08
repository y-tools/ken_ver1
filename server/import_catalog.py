#!/usr/bin/env python3
"""Stage-by-stage import of the existing Ken Denmoku JSON catalogue.

Run on the VPS only after inspecting disk/RAM and making a backup.
Run with --max-files 1 first. Paths are relative to the repository root.
No network access or API calls. Only metadata and estimated readings are loaded.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
import uuid
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
# All non-TK source datasets were removed on 2026-11-09. Never reimport them.
# Only the 98-row TK-only catalog is valid for a disposable test import.
DATASETS = {
    "tk_only": ("catalog.json", "musicbrainz", "TK curated MusicBrainz metadata", "CC0", "https://musicbrainz.org"),
}

NAME_COLUMNS = [
    ("title_hira", "title", "hiragana"),
    ("title_kata", "title", "katakana"),
    ("title_romaji", "title", "romaji"),
    ("title_english", "title", "english"),
    ("artist_hira", "artist", "hiragana"),
    ("artist_kata", "artist", "katakana"),
    ("artist_romaji", "artist", "romaji"),
    ("artist_english", "artist", "english"),
]


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", str(value)).casefold()
    value = "".join(chr(ord(ch) - 96) if "\u30a1" <= ch <= "\u30f6" else ch for ch in value)
    return re.sub(r"[\s\u3000・ー‐-]", "", value)


def filenames(dataset: str):
    path = ROOT / DATASETS[dataset][0]
    if not path.exists():
        raise FileNotFoundError(path)
    if path.name == "manifest.json":
        manifest = json.loads(path.read_text(encoding="utf-8"))
        for filename in manifest.get("files", []):
            resolved = (ROOT / filename).resolve()
            if ROOT.resolve() not in resolved.parents:
                raise RuntimeError(f"Path outside repository: {filename}")
            yield resolved
    else:
        yield path


def rows_in(path: Path, dataset: str):
    raw = json.loads(path.read_text(encoding="utf-8"))
    entries = raw.get("songs", []) if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        raise ValueError(f"Malformed catalog: {path}")
    for row in entries:
        if not isinstance(row, list) or len(row) < 2:
            continue
        title, artist = str(row[0]).strip(), str(row[1]).strip()
        if not title or not artist or len(title) > 300 or len(artist) > 200:
            continue
        title_key, artist_key = normalize(title), normalize(artist)
        if not title_key or not artist_key:
            continue
        year = None
        if len(row) > 2 and isinstance(row[2], int) and 1850 <= row[2] <= 2100:
            year = row[2]
        mbid = None
        if dataset.startswith("mb_") and len(row) > 3 and isinstance(row[3], str):
            try:
                mbid = uuid.UUID(row[3])
            except ValueError:
                pass
        yield (title,title_key,artist,artist_key,year,mbid)


def register_source(cur, dataset: str):
    _, key, display, license_id, link = DATASETS[dataset]
    cur.execute(
        """INSERT INTO source_catalogs(code,display_name,source_url,license_id,attribution)
           VALUES (%s,%s,%s,%s,%s)
           ON CONFLICT (code) DO UPDATE SET display_name=EXCLUDED.display_name
           RETURNING id""", (key,display,link,license_id,display)
    )
    return cur.fetchone()[0]


def prepare_stage(cur):
    cur.execute("""CREATE TEMP TABLE IF NOT EXISTS ken_stage(
        title TEXT, title_key TEXT, artist TEXT, artist_key TEXT,
        release_year SMALLINT, mbid UUID
    ) ON COMMIT PRESERVE ROWS""")


def insert_batch(conn, batch, source_id):
    if not batch:
        return
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("TRUNCATE ken_stage")
            with cur.copy("COPY ken_stage (title,title_key,artist,artist_key,release_year,mbid) FROM STDIN") as copy:
                for row in batch:
                    copy.write_row(row)
            cur.execute("""
                INSERT INTO artists(name,name_key)
                SELECT DISTINCT ON (artist_key) artist,artist_key
                FROM ken_stage ORDER BY artist_key,artist
                ON CONFLICT (name_key) DO NOTHING
            """)
            cur.execute("""
                INSERT INTO songs(title,title_key,primary_artist_id,release_year,release_precision,release_source_id)
                SELECT DISTINCT ON (st.title_key,a.id)
                    st.title,st.title_key,a.id,st.release_year,
                    CASE WHEN st.release_year IS NOT NULL THEN 'year' ELSE 'unknown' END,
                    CASE WHEN st.release_year IS NOT NULL THEN %s::bigint ELSE NULL END
                FROM ken_stage st JOIN artists a ON a.name_key=st.artist_key
                ORDER BY st.title_key,a.id,st.release_year NULLS LAST
                ON CONFLICT(title_key,primary_artist_id) DO NOTHING
            """, (source_id,))
            cur.execute("""
                INSERT INTO recordings(song_id,musicbrainz_recording_id)
                SELECT DISTINCT ON (st.mbid) s.id,st.mbid
                FROM ken_stage st JOIN artists a ON a.name_key=st.artist_key
                JOIN songs s ON s.title_key=st.title_key AND s.primary_artist_id=a.id
                WHERE st.mbid IS NOT NULL
                ORDER BY st.mbid,s.id
                ON CONFLICT(musicbrainz_recording_id) DO NOTHING
            """)


def import_catalog(conn, dataset, max_files, batch_size):
    with conn.cursor() as cur:
        sid = register_source(cur,dataset)
        prepare_stage(cur)
    conn.commit()
    scanned = 0
    for index, path in enumerate(filenames(dataset)):
        if max_files and index >= max_files:
            break
        pending=[]
        for row in rows_in(path,dataset):
            pending.append(row)
            scanned+=1
            if len(pending) >= batch_size:
                insert_batch(conn,pending,sid)
                pending=[]
        insert_batch(conn,pending,sid)
        print(f"{dataset}: processed {path.name}, total input rows={scanned:,}",flush=True)
    print(f"{dataset}: {scanned:,} source rows processed (duplicates ignored)",flush=True)


def import_readings(conn, max_files):
    folder=ROOT / "data/song_readings"
    meta=json.loads((folder/"manifest.json").read_text(encoding="utf-8"))
    if meta.get("schema") != "ken-phonetic-2m-v1":
        raise ValueError("Unexpected pronunciation dataset")
    with conn.cursor() as cur:
        cur.execute("""CREATE TEMP TABLE IF NOT EXISTS ken_reading_stage(
           title_key TEXT,artist_key TEXT,
           title_hira TEXT,title_kata TEXT,title_romaji TEXT,title_english TEXT,
           artist_hira TEXT,artist_kata TEXT,artist_romaji TEXT,artist_english TEXT,
           title_hira_key TEXT,title_kata_key TEXT,title_romaji_key TEXT,title_english_key TEXT,
           artist_hira_key TEXT,artist_kata_key TEXT,artist_romaji_key TEXT,artist_english_key TEXT
        ) ON COMMIT PRESERVE ROWS""")
    conn.commit()
    scanned=0
    for index, filename in enumerate(meta["files"]):
        if max_files and index>=max_files:
            break
        path=(ROOT / filename).resolve()
        if ROOT.resolve() not in path.parents:
            raise RuntimeError("Invalid source path")
        rows=json.loads(path.read_text(encoding="utf-8"))
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("TRUNCATE ken_reading_stage")
                with cur.copy("COPY ken_reading_stage FROM STDIN") as copy:
                    for row in rows:
                        if not isinstance(row,list) or len(row)<11 or not row[0] or not row[1]:
                            continue
                        values=[str(row[n] or "")[:300] for n in (3,4,5,6,7,8,9,10)]
                        copy.write_row((normalize(row[0]),normalize(row[1]),
                            *values,*(normalize(v) for v in values)))
                        scanned+=1
                # Single-pass insertion is substantially cheaper than 6 separate
                # joins against 2M songs on a 4GB shared VPS.
                cur.execute("""
                    INSERT INTO song_names(song_id,kind,value,search_key,verification)
                    SELECT DISTINCT s.id,v.kind,v.value,v.search_key,'estimated'
                    FROM ken_reading_stage st
                    JOIN artists a ON a.name_key=st.artist_key
                    JOIN songs s ON s.title_key=st.title_key AND s.primary_artist_id=a.id
                    CROSS JOIN LATERAL (VALUES
                      ('hiragana',st.title_hira,st.title_hira_key),
                      ('katakana',st.title_kata,st.title_kata_key),
                      ('romaji',st.title_romaji,st.title_romaji_key)
                    ) AS v(kind,value,search_key)
                    WHERE v.value <> '' AND v.search_key <> ''
                    ON CONFLICT(song_id,kind,search_key) DO NOTHING
                """)
                cur.execute("""
                    INSERT INTO artist_names(artist_id,kind,value,search_key,verification)
                    SELECT DISTINCT a.id,v.kind,v.value,v.search_key,'estimated'
                    FROM ken_reading_stage st
                    JOIN artists a ON a.name_key=st.artist_key
                    CROSS JOIN LATERAL (VALUES
                      ('hiragana',st.artist_hira,st.artist_hira_key),
                      ('katakana',st.artist_kata,st.artist_kata_key),
                      ('romaji',st.artist_romaji,st.artist_romaji_key)
                    ) AS v(kind,value,search_key)
                    WHERE v.value <> '' AND v.search_key <> ''
                    ON CONFLICT(artist_id,kind,search_key) DO NOTHING
                """)
        print(f"readings: processed {path.name}; rows={scanned:,}",flush=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--dataset",required=True,choices=[*DATASETS,"readings"])
    parser.add_argument("--max-files",type=int,default=1,
                        help="Conservative default: one file. Set 0 for all after reviewing VPS capacity.")
    parser.add_argument("--batch-size",type=int,default=2000)
    args=parser.parse_args()
    if args.max_files<0 or not 100<=args.batch_size<=10000:
        parser.error("max-files must be >=0 and batch-size 100..10000")
    import os
    dsn=os.getenv("KEN_IMPORT_DATABASE_URL")
    if not dsn:
        parser.error("KEN_IMPORT_DATABASE_URL must be set through VPS environment configuration")
    with psycopg.connect(dsn,autocommit=False) as conn:
        if args.dataset=="readings":
            import_readings(conn,args.max_files)
        else:
            import_catalog(conn,args.dataset,args.max_files,args.batch_size)
    print("Finished; check actual unique counts before changing frontend API URL.")


if __name__=="__main__":
    main()
