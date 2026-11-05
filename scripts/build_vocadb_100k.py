#!/usr/bin/env python3
"""Build exactly 100,000 *new* VocaDB song-search candidates from public metadata.

This is an additional Vocaloid/UTAU-focused catalog, NOT a Japanese sales chart.
Source: VocaDB (database content CC BY, https://vocadb.net), archived by
amiadesu/VocaDBSongs at Hugging Face (dataset metadata marked MIT).
No lyrics, images, media, or recordings are downloaded or redistributed.
"""
from __future__ import annotations
import csv
import datetime as dt
import json
import re
import sys
import unicodedata
from pathlib import Path

TARGET = 100_000
PER_SHARD = 5_000
SOURCE = "amiadesu/VocaDBSongs"
DATA_FOLDER = Path("data/vocadb_100k")
JP_CHARS = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")

def normalize(value: object) -> str:
    v = unicodedata.normalize("NFKC", str(value or "")).casefold()
    v = "".join(chr(ord(c) - 96) if "\u30a1" <= c <= "\u30f6" else c for c in v)
    return re.sub(r"[\s\u3000・ー‐-]", "", v)

def key(title: str, artist: str) -> str:
    return normalize(title) + "|" + normalize(artist)

def existing_keys() -> set[str]:
    keys = set()
    global_rows = json.loads(Path("catalog.json").read_text(encoding="utf-8"))
    japan = json.loads(Path("data/japanese_popular_10000.json").read_text(encoding="utf-8"))
    for song in [*global_rows, *japan["songs"]]:
        if isinstance(song, list) and len(song) >= 2 and song[0] and song[1]:
            keys.add(key(song[0], song[1]))
    return keys

def integer(value: object) -> int:
    try:
        return int(value or 0)
    except (ValueError, TypeError):
        return 0

def release_year(value: object):
    text = str(value or "")
    match = re.match(r"^((?:19|20)\d{2})(?:-\d{2}-\d{2})?", text)
    if match:
        year = int(match.group(1))
        if 1950 <= year <= dt.datetime.now(dt.timezone.utc).year:
            return year
    return None

def main() -> None:
    try:
        from huggingface_hub import hf_hub_download
    except ImportError as exc:
        raise RuntimeError("Install 'huggingface_hub[hf_xet]' first") from exc
    known = existing_keys()
    path = hf_hub_download(repo_id=SOURCE, filename="vocadb.csv", repo_type="dataset")
    # Keep only core factual metadata, removing alternate versions and existing songs.
    best = {}
    raw_count = 0
    eligible = 0
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        csv.field_size_limit(sys.maxsize)
        reader = csv.DictReader(fh)
        needed = {"name", "defaultName", "artistString", "songType", "favoritedTimes", "ratingScore", "publishDate"}
        missing = needed.difference(reader.fieldnames or [])
        if missing:
            raise RuntimeError("Dataset columns changed: " + ", ".join(sorted(missing)))
        for item in reader:
            raw_count += 1
            title = (item.get("name") or item.get("defaultName") or "").strip()
            artist = (item.get("artistString") or "").strip()
            if not title or not artist or len(title) > 190 or len(artist) > 150:
                continue
            if artist.lower() in {"unknown", "unknown artist", "various artists", "various"}:
                continue
            status = (item.get("status") or "").strip()
            if status.lower() in {"deleted", "draft"}:
                continue
            identity = key(title, artist)
            if identity in known:
                continue
            lang = (item.get("defaultNameLanguage") or "").lower()
            jp = int("japanese" in lang or bool(JP_CHARS.search(title + artist)))
            typ = (item.get("songType") or "").lower()
            original = int(typ == "original")
            favorites = integer(item.get("favoritedTimes"))
            score = integer(item.get("ratingScore"))
            year = release_year(item.get("publishDate"))
            song_id = integer(item.get("id"))
            rank = (jp, original, favorites, score, int(year is not None), song_id)
            rec = (rank, [title, artist, year, song_id])
            old = best.get(identity)
            if old is None or rank > old[0]:
                best[identity] = rec
            eligible += 1
            if raw_count % 100_000 == 0:
                print(f"examined={raw_count:,} candidate_unique={len(best):,}", flush=True)
    if len(best) < TARGET:
        raise RuntimeError(f"Only {len(best):,} distinct new titles, need {TARGET:,}. No false totals are written.")
    ranked = sorted(best.values(), key=lambda rec: rec[0], reverse=True)
    chosen = ranked[:TARGET]
    if len(set(key(v[1][0], v[1][1]) for v in chosen)) != TARGET:
        raise AssertionError("Duplicate key detected after ranking")
    DATA_FOLDER.mkdir(parents=True, exist_ok=True)
    # Remove stale shards from earlier build to prevent accidental overcounts.
    for old in DATA_FOLDER.glob("part_*.json"):
        old.unlink()
    files = []
    for start in range(0, TARGET, PER_SHARD):
        filename = f"part_{start // PER_SHARD + 1:03d}.json"
        rows = [v[1] for v in chosen[start:start + PER_SHARD]]
        target_file = DATA_FOLDER / filename
        target_file.write_text(json.dumps(rows, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        files.append(str(target_file).replace("\\", "/"))
    japanese = sum(item[0][0] for item in chosen)
    missing_year = sum(item[1][2] is None for item in chosen)
    manifest = {
        "schema": "vocadb-100k-v1",
        "count": TARGET,
        "files": files,
        "source": "VocaDB via amiadesu/VocaDBSongs",
        "sourceUrl": "https://vocadb.net/",
        "datasetUrl": "https://huggingface.co/datasets/amiadesu/VocaDBSongs",
        "license": "VocaDB database metadata: CC BY (attribution required)",
        "scope": "Vocaloid/UTAU-associated metadata, not an official J-pop chart",
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "sourceRowsExamined": raw_count,
        "newSongCandidates": len(best),
        "japaneseScriptOrLanguageCount": japanese,
        "missingReleaseYearCount": missing_year,
    }
    (DATA_FOLDER / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k:v for k,v in manifest.items() if k != "files"}, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
