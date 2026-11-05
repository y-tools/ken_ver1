#!/usr/bin/env python3
"""Extend Ken Denmoku to 2,000,000 distinct title+artist pairs.

The additional million uses official MusicBrainz canonical recording metadata
(CC0), with unknown release dates left blank. For the whole 2M catalog, make
a separate on-demand phonetic index for Japanese-script names. Readings are
automatic and approximate (pykakasi); not authoritative artist/song aliases.
Official English translated names are never invented.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from collections import defaultdict

from build_musicbrainz_to_1m import baseline, stream_records, norm, pair_key, bucket

GOAL = 2_000_000
BATCH = 256
EXTRA = Path("data/musicbrainz_next_1m")
READINGS = Path("data/song_readings")
JAPANESE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
HAN = re.compile(r"[\u3400-\u9fff]")
LATIN_ONLY = re.compile(r"^[\x00-\x7f]+$")
EXCLUDE = {"unknown", "unknown artist", "various artists"}


def previous_songs():
    """One pass over old datasets; all duplicate copies are removed by key."""
    yield from json.loads(Path("catalog.json").read_text(encoding="utf-8"))
    yield from json.loads(Path("data/japanese_popular_10000.json").read_text(encoding="utf-8"))["songs"]
    for folder in ["data/vocadb_100k","data/extra_to_300k","data/musicbrainz_700k"]:
        manifest = json.loads(Path(folder,"manifest.json").read_text(encoding="utf-8"))
        for file in manifest["files"]:
            yield from json.loads(Path(file).read_text(encoding="utf-8"))


def pronounce(text: str, kakasi) -> tuple[str, str, str, str]:
    """Return (hiragana, katakana, romaji, English literal).

    Romanization for Japanese text is estimated. ASCII text is kept exactly
    when it is already the spelling, but this is not translated English.
    """
    original = text.strip()
    if not original:
        return ("","","","")
    if not JAPANESE.search(original):
        if LATIN_ONLY.fullmatch(original) and re.search(r"[A-Za-z]", original):
            return ("","",original,original)
        return ("","","","")
    parts = kakasi.convert(original)
    hira = "".join(p["hira"] for p in parts).strip()
    kata = "".join(p["kana"] for p in parts).strip()
    roma = " ".join(p["hepburn"] for p in parts).strip()
    if not hira or hira == original and HAN.search(original):
        # Not all Han characters have reliable Japanese pronunciation.
        return ("","","","")
    english = ""
    return (hira,kata,roma,english)


def reading_row(row, kakasi):
    title, artist = row[:2]
    th,tk,tr,te=pronounce(title,kakasi)
    ah,ak,ar,ae=pronounce(artist,kakasi)
    # This separate index is only needed for Japanese-script names. On ASCII
    # original titles, the English/Roman spelling is already the source title.
    if not JAPANESE.search(title+artist):
        return None
    if not (th or tk or tr or ah or ak or ar):
        return None
    return [title,artist,row[2] if len(row)>2 else None,th,tk,tr,te,ah,ak,ar,ae]


def publish_buckets(folder: Path, groups: list, name: str, manifest: dict):
    folder.mkdir(parents=True,exist_ok=True)
    for stale in folder.glob("bucket_*.json"):
        stale.unlink()
    for n,records in enumerate(groups):
        file=folder/f"bucket_{n:02x}.json"
        file.write_text(json.dumps(records,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    manifest.update({"files":[str(folder/f"bucket_{n:02x}.json").replace("\\","/") for n in range(BATCH)]})
    (folder/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")


def main():
    from pykakasi import kakasi
    converter=kakasi()
    previous=baseline()
    originals=[]
    for row in previous_songs():
        if not isinstance(row,list) or len(row)<2 or not row[0] or not row[1]:
            continue
        identity=pair_key(row[0],row[1])
        if identity not in previous:
            previous.add(identity)
        # Only retain the Japanese-script subset of existing rows for
        # pronunciation. Extra copies will be suppressed separately.
        if JAPANESE.search(row[0]+row[1]):
            originals.append(row)
    if len(previous)!=1_000_000:
        raise ValueError(f"Expected 1,000,000 existing unique songs; found {len(previous):,}")
    print(f"Existing unique metadata: {len(previous):,}",flush=True)
    required=GOAL-len(previous)
    new_groups=[[] for _ in range(BATCH)]
    candidate_japanese=[]
    counter=0
    examined=0
    for row in stream_records():
        examined+=1
        title=(row.get("recording_name") or "").strip()
        artist=(row.get("artist_credit_name") or "").strip()
        mbid=(row.get("recording_mbid") or "").strip()
        if not title or not artist or len(title)>190 or len(artist)>150:
            continue
        if artist.lower() in EXCLUDE:
            continue
        identity=pair_key(title,artist)
        if identity in previous or len(norm(title))<2 or len(norm(artist))<2:
            continue
        previous.add(identity)
        item=[title,artist,None,mbid]
        a,b=bucket(title),bucket(artist)
        new_groups[a].append(item)
        if a!=b:
            new_groups[b].append(item)
        if JAPANESE.search(title+artist):
            candidate_japanese.append(item)
        counter+=1
        if examined%500_000==0:
            print(f"Examined {examined:,}, new {counter:,}/{required:,}",flush=True)
        if counter==required:
            break
    if counter != required or len(previous) != GOAL:
        raise RuntimeError(f"Insufficient new records: {counter} of {required} required")
    assert counter==1_000_000
    publish_buckets(EXTRA,new_groups,"recording",{
        "schema":"musicbrainz-next-million-v1",
        "baselineUnique":1_000_000,
        "additionalUnique":counter,
        "targetUnique":GOAL,
        "source":"https://ftp.musicbrainz.org/pub/musicbrainz/canonical_data/musicbrainz-canonical-dump-20261103-080003/musicbrainz-canonical-dump-20261103-080003.tar.zst",
        "license":"MusicBrainz canonical metadata CC0",
        "sourceRowsScanned":examined,
        "bucketCount":BATCH,
        "bucketCopies":sum(map(len,new_groups)),
        "sourceFields":["recording_name","artist_credit_name","recording_mbid"],
    })
    print(f"New metadata verified, {GOAL:,} total unique; generating Japanese readings",flush=True)
    del new_groups

    reading_groups=[[] for _ in range(BATCH)]
    seen=set()
    reading_count=0
    from itertools import chain
    for item in chain(originals,candidate_japanese):
        k=pair_key(item[0],item[1])
        if k in seen:
            continue
        seen.add(k)
        record=reading_row(item,converter)
        if record is None:
            continue
        variants=[item[0],item[1],record[3],record[4],record[5],record[7],record[8],record[9]]
        places={bucket(value) for value in variants if len(norm(value))>=2}
        for p in places:
            reading_groups[p].append(record)
        reading_count+=1
        if reading_count%100_000==0:
            print(f"Generated {reading_count:,} estimated Japanese title/artist readings",flush=True)
    publish_buckets(READINGS,reading_groups,"reading",{
        "schema":"ken-phonetic-2m-v1",
        "totalUnique":GOAL,
        "indexedJapaneseUnique":reading_count,
        "indexScope":"Japanese-script names from all old and new sources",
        "columns":["title","artist","year","titleHiragana","titleKatakana","titleRomaji","titleEnglish","artistHiragana","artistKatakana","artistRomaji","artistEnglish"],
        "bucketCount":BATCH,
        "bucketCopies":sum(map(len,reading_groups)),
        "generation":"pykakasi automated Japanese conversion; approximate, not verified",
        "english":"No invented English translations. Native Latin spellings are preserved in source names.",
        "license":"Generated index from CC0 (MusicBrainz/Wikidata) and CC BY (VocaDB) metadata. Attribution in README.",
    })
    print(json.dumps({
        "targetUnique":GOAL,"additional":counter,
        "japaneseReadingCandidates":len(originals)+len(candidate_japanese),
        "uniqueAutoReadings":reading_count,
        "phoneticCopies":sum(map(len,reading_groups))
    },ensure_ascii=False,indent=2),flush=True)


if __name__=="__main__":
    main()
