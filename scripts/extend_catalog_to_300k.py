#!/usr/bin/env python3
"""Extend Ken Denmoku's unique song search catalog to exactly 300,000 records.

Keeps the existing Wikidata/Japanese and VocaDB 100k files untouched, selects
only additional original VocaDB metadata records, and emits JSON shards.
VocaDB database metadata requires attribution (CC BY). This is not a J-pop chart.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import math
import re
import sys
import unicodedata
from pathlib import Path

GOAL = 300_000
PER_SHARD = 5_000
SOURCE = "amiadesu/VocaDBSongs"
OUTPUT = Path("data/extra_to_300k")
JP_CHARS = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")


def normalize(value: object) -> str:
    value = unicodedata.normalize("NFKC", str(value or "")).lower()
    value = "".join(chr(ord(c) - 96) if "\u30a1" <= c <= "\u30f6" else c for c in value)
    return re.sub(r"[\s\u3000・ー‐-]", "", value)


def song_key(title: str, artist: str) -> str:
    return normalize(title) + "|" + normalize(artist)


def parse_source(path: Path, collection: object) -> list:
    if not isinstance(collection, list):
        raise RuntimeError(f"{path}: expected list of songs")
    return collection


def load_known() -> tuple[set[str], dict[str, int]]:
    names = set()
    counts = {}

    def insert(label: str, songs: object) -> None:
        songs = parse_source(Path(label), songs)
        counts[label] = len(songs)
        for song in songs:
            if not isinstance(song, list) or len(song) < 2 or not song[0] or not song[1]:
                continue
            names.add(song_key(song[0], song[1]))

    insert("world", json.loads(Path("catalog.json").read_text(encoding="utf-8")))
    japanese = json.loads(Path("data/japanese_popular_10000.json").read_text(encoding="utf-8"))
    if japanese.get("schema") != "jp-catalog-v1":
        raise RuntimeError("Unrecognized Japanese data format")
    insert("japanese", japanese["songs"])

    base = Path("data/vocadb_100k")
    manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema") != "vocadb-100k-v1" or manifest.get("count") != 100_000:
        raise RuntimeError("Expected existing verified VocaDB 100k catalog")
    count = 0
    for file in manifest.get("files", []):
        path = Path(file)
        if path.parent != base or not path.name.startswith("part_"):
            raise RuntimeError(f"Unsafe catalog shard path: {path}")
        songs = json.loads(path.read_text(encoding="utf-8"))
        insert("previous:" + path.name, songs)
        count += len(songs)
    if count != 100_000:
        raise RuntimeError(f"Existing VocaDB dataset has {count} songs instead of 100,000")
    counts["vocadb"] = count
    return names, counts


def to_int(value: object) -> int:
    try:
        return int(value or 0)
    except (ValueError, TypeError):
        return 0


def release_year(value: object) -> int | None:
    match = re.match(r"^((?:19|20)\d{2})(?:-\d{2}-\d{2})?", str(value or ""))
    if not match:
        return None
    year = int(match.group(1))
    return year if 1950 <= year <= dt.datetime.now(dt.timezone.utc).year else None


def main() -> None:
    try:
        from huggingface_hub import hf_hub_download
    except ImportError as exc:
        raise RuntimeError("Install huggingface_hub[hf_xet]") from exc

    baseline, counts = load_known()
    baseline_unique = len(baseline)
    needed = GOAL - baseline_unique
    if needed <= 0:
        raise RuntimeError(f"Existing catalog already has {baseline_unique} songs (target {GOAL})")
    print(f"Baseline unique: {baseline_unique:,}; additional songs needed: {needed:,}", flush=True)

    raw_path = hf_hub_download(repo_id=SOURCE, filename="vocadb.csv", repo_type="dataset")
    best: dict[str, tuple[tuple, list]] = {}
    examined = 0
    with open(raw_path, "r", encoding="utf-8-sig", newline="") as stream:
        csv.field_size_limit(sys.maxsize)
        reader = csv.DictReader(stream)
        required = {"name", "defaultName", "artistString", "songType", "favoritedTimes", "ratingScore", "publishDate"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise RuntimeError("VocaDB columns changed: " + ", ".join(sorted(missing)))
        for entry in reader:
            examined += 1
            title = (entry.get("name") or entry.get("defaultName") or "").strip()
            artist = (entry.get("artistString") or "").strip()
            if not title or not artist or len(title) > 190 or len(artist) > 150:
                continue
            if artist.lower() in {"unknown", "unknown artist", "various", "various artists"}:
                continue
            if (entry.get("status") or "").strip().lower() in {"deleted", "draft"}:
                continue
            key = song_key(title, artist)
            if key in baseline:
                continue
            lang = (entry.get("defaultNameLanguage") or "").lower()
            jp = int("japanese" in lang or bool(JP_CHARS.search(title + artist)))
            original = int((entry.get("songType") or "").lower() == "original")
            favorites = to_int(entry.get("favoritedTimes"))
            rating = to_int(entry.get("ratingScore"))
            year = release_year(entry.get("publishDate"))
            song_id = to_int(entry.get("id"))
            rank = (jp, original, favorites, rating, int(year is not None), song_id)
            candidate = (rank, [title, artist, year, song_id])
            old = best.get(key)
            if old is None or rank > old[0]:
                best[key] = candidate
            if examined % 200_000 == 0:
                print(f"Examined={examined:,}, unique new candidates={len(best):,}", flush=True)

    if len(best) < needed:
        raise RuntimeError(f"Only {len(best):,} new candidates for {needed:,} required")
    selected = sorted(best.values(), key=lambda record: record[0], reverse=True)[:needed]
    extension_keys = {song_key(row[1][0], row[1][1]) for row in selected}
    if len(extension_keys) != needed or extension_keys.intersection(baseline):
        raise RuntimeError("Duplicate detected in selected extension")
    if len(baseline | extension_keys) != GOAL:
        raise RuntimeError("Unable to verify exactly 300,000 unique songs")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    for stale in OUTPUT.glob("part_*.json"):
        stale.unlink()
    files = []
    for begin in range(0, needed, PER_SHARD):
        destination = OUTPUT / f"part_{begin // PER_SHARD + 1:03d}.json"
        rows = [entry[1] for entry in selected[begin:begin + PER_SHARD]]
        destination.write_text(json.dumps(rows, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        files.append(destination.as_posix())
    manifest = {
        "schema": "vocadb-to-300k-v1",
        "targetUnique": GOAL,
        "baselineUnique": baseline_unique,
        "count": needed,
        "files": files,
        "source": "VocaDB via amiadesu/VocaDBSongs",
        "sourceUrl": "https://vocadb.net/",
        "datasetUrl": "https://huggingface.co/datasets/amiadesu/VocaDBSongs",
        "license": "VocaDB database metadata CC BY, with attribution",
        "scope": "Vocaloid and UTAU associated songs; not a Japanese sales ranking",
        "sourceRowsExamined": examined,
        "additionalCandidates": len(best),
        "japaneseScriptOrLanguageCount": sum(entry[0][0] for entry in selected),
        "missingReleaseYearCount": sum(entry[1][2] is None for entry in selected),
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "baseline": baseline_unique,
        "added": needed,
        "finalUnique": baseline_unique + needed,
        "files": len(files),
        "missingYear": manifest["missingReleaseYearCount"],
        "sourceRowsExamined": examined,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
