#!/usr/bin/env python3
"""Extend Ken's catalogue from 300,000 to 1,000,000 unique title+artist pairs.

Uses the official MusicBrainz canonical metadata snapshot (CC0).
New records are distributed into on-demand two-character prefix hash buckets.
Canonical metadata does not include a verified recording release year;
such years remain null, rather than guessed.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import sys
import tarfile
import unicodedata
import urllib.request
from pathlib import Path

TARGET = 1_000_000
SOURCE_DATE = "20261103-080003"
SOURCE_FILE = f"musicbrainz-canonical-dump-{SOURCE_DATE}.tar.zst"
SOURCE_URL = f"https://ftp.musicbrainz.org/pub/musicbrainz/canonical_data/musicbrainz-canonical-dump-{SOURCE_DATE}/{SOURCE_FILE}"
DEST = Path("data/musicbrainz_700k")
BUCKETS = 256


def norm(v: object) -> str:
    v = unicodedata.normalize("NFKC", str(v or "")).lower()
    v = "".join(chr(ord(c)-96) if "\u30a1" <= c <= "\u30f6" else c for c in v)
    return re.sub(r"[\s\u3000・ー‐-]", "", v)


def pair_key(t: str, a: str) -> str:
    return norm(t) + "|" + norm(a)


def bucket(v: str) -> int:
    h = 0
    for c in norm(v)[:2]:
        h = (h*131 + ord(c)) % BUCKETS
    return h


def baseline() -> set[str]:
    known: set[str] = set()
    def add(rows):
        for row in rows:
            if isinstance(row,list) and len(row)>=2 and row[0] and row[1]:
                known.add(pair_key(row[0],row[1]))
    add(json.loads(Path("catalog.json").read_text(encoding="utf-8")))
    add(json.loads(Path("data/japanese_popular_10000.json").read_text(encoding="utf-8"))["songs"])
    for group in ["data/vocadb_100k","data/extra_to_300k"]:
        manifest = json.loads(Path(group,"manifest.json").read_text(encoding="utf-8"))
        for file in manifest["files"]:
            add(json.loads(Path(file).read_text(encoding="utf-8")))
    if len(known) != 300_000:
        raise ValueError(f"Expected 300000 known unique title/artist pairs, got {len(known)}")
    return known


def stream_records():
    import zstandard as zstd
    req = urllib.request.Request(SOURCE_URL, headers={"User-Agent":"Ken-Denmoku metadata index builder (github.com/y-tools/ken_ver1)"})
    with urllib.request.urlopen(req,timeout=120) as response:
        decoder = zstd.ZstdDecompressor(max_window_size=2**31)
        with decoder.stream_reader(response) as stream:
            with tarfile.open(fileobj=stream,mode="r|") as archive:
                found=False
                for member in archive:
                    print("Archive member:",member.name,"size:",member.size,flush=True)
                    if not member.isfile() or not member.name.endswith("canonical_musicbrainz_data.csv"):
                        continue
                    found=True
                    extracted=archive.extractfile(member)
                    if extracted is None:
                        raise ValueError("Could not extract canonical music metadata")
                    class StreamAdapter(io.RawIOBase):
                        def readable(self):
                            return True
                        def seekable(self):
                            return False
                        def readinto(self,b):
                            part=extracted.read(len(b))
                            if part is None:
                                return 0
                            b[:len(part)]=part
                            return len(part)
                    buffered=io.BufferedReader(StreamAdapter(),buffer_size=1<<20)
                    wrapper=io.TextIOWrapper(buffered,encoding="utf-8-sig",errors="replace",newline="")
                    reader=csv.DictReader(wrapper)
                    fields=set(reader.fieldnames or [])
                    required={"recording_name","artist_credit_name","recording_mbid"}
                    if not required.issubset(fields):
                        raise ValueError(f"Canonical CSV headers changed: {sorted(fields)}")
                    for row in reader:
                        yield row
                    break
                if not found:
                    raise RuntimeError("Canonical metadata CSV missing from official dump")


def main():
    known=baseline()
    needed=TARGET-len(known)
    os.makedirs(DEST,exist_ok=True)
    data=[[] for _ in range(BUCKETS)]
    added=0
    inspected=0
    for row in stream_records():
        inspected+=1
        title=(row.get("recording_name") or "").strip()
        artist=(row.get("artist_credit_name") or "").strip()
        mbid=(row.get("recording_mbid") or "").strip()
        if not title or not artist or len(title)>190 or len(artist)>150:
            continue
        if artist.lower() in {"unknown","unknown artist","various artists"}:
            continue
        k=pair_key(title,artist)
        if k in known:
            continue
        tn,an=norm(title),norm(artist)
        if len(tn)<2 or len(an)<2:
            continue
        known.add(k)
        # [title, artist, verified release year (unknown), MusicBrainz recording ID]
        item=[title,artist,None,mbid]
        title_bucket,artist_bucket=bucket(title),bucket(artist)
        data[title_bucket].append(item)
        if artist_bucket != title_bucket:
            data[artist_bucket].append(item)
        added+=1
        if inspected % 500_000 == 0:
            print(f"Read {inspected:,} canonical rows, selected {added:,}/{needed:,}",flush=True)
        if added==needed:
            break
    if added != needed or len(known)!=TARGET:
        raise RuntimeError(f"Insufficient valid official metadata: selected={added}, total={len(known)}, target={TARGET}")
    print(f"Verified {TARGET:,} unique title/artist pairs; source rows scanned={inspected:,}",flush=True)
    files=[]
    for n,rows in enumerate(data):
        filename=DEST/f"bucket_{n:02x}.json"
        filename.write_text(json.dumps(rows,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
        files.append(filename.as_posix())
    manifest={
      "schema":"musicbrainz-on-demand-prefix-v1",
      "targetUnique":TARGET,
      "baselineUnique":300000,
      "additionalUnique":needed,
      "count":needed,
      "sourceRowsScanned":inspected,
      "source":SOURCE_URL,
      "license":"MusicBrainz canonical metadata CC0",
      "scope":"Worldwide recording metadata, not a popularity chart",
      "search":"prefix title or artist, minimum two normalized characters",
      "releaseYear":"Unknown unless separately verified",
      "fileCount":len(files),
      "bucketCount":BUCKETS,
      "bucketCopies":sum(map(len,data)),
      "files":files,
    }
    (DEST/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in manifest.items() if k!="files"},ensure_ascii=False,indent=2),flush=True)


if __name__=="__main__":
    main()
