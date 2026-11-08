#!/usr/bin/env python3
"""Ken research worker: two bounded, restartable lanes. No passwords in prompts.

Uses only MusicBrainz CC0 core artist/recording data and the Wikidata CC0
entity API. Additional discovery sites are for separate manual research;
the worker never scrapes them. Promotion requires independent identity
verification. Unknown dates/readings remain NULL. No delete/overwrite.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
import unicodedata
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

MB = "https://musicbrainz.org"
WD = "https://www.wikidata.org"
UA = "KenDenmokuResearch/0.2 (https://github.com/y-tools/ken_ver1)"
TK_MBID = "6114677c-fa8f-4d87-960a-3f1169aaef89"
TK_ARTIST_ID = 643167
NON_SONG = re.compile(r"(?:\binterview\b|\bdocumentary\b|\btrailer\b|\bmusic video\b|"
                      r"\bbehind the scenes\b|^mc(?:\s|$)|^_fragment|"
                      r"ノンクレジット|(?:^|\s)talk(?:\s|$))", re.I)
VERSION = re.compile(r"(?:\blive\b|\bremix\b|\binstrumental\b|\bacoustic\b|"
                     r"\btv size\b|\bversion\b|\bedit\b|"
                     r"\bfirst take\b|\bbootleg\b|\breconstructed\b)", re.I)


def key(text):
    value = unicodedata.normalize("NFKC", str(text)).casefold()
    value = "".join(chr(ord(c)-96) if "\u30a1" <= c <= "\u30f6" else c for c in value)
    return re.sub(r"[\s\u3000・ー‐-]", "", value)


def valid_mbid(s):
    try:
        return str(uuid.UUID(str(s))) == str(s).lower()
    except (ValueError, TypeError):
        return False


def valid_qid(s):
    return isinstance(s, str) and bool(re.fullmatch(r"Q[1-9][0-9]{0,12}", s))


def safe_title(s):
    return bool(isinstance(s, str) and 1 <= len(s.strip()) <= 300 and
                not NON_SONG.search(s) and not VERSION.search(s))


class Client:
    def __init__(self, opener=None, sleep=time.sleep):
        self.opener = opener or urllib.request.urlopen
        self.sleep = sleep
        self.last_request = 0.0

    def get(self, url, retries=4):
        if not (url.startswith(MB + "/ws/2/") or
                re.fullmatch(r"https://www.wikidata.org/wiki/Special:EntityData/Q[1-9][0-9]{0,12}\.json", url)):
            raise ValueError("Unsupported source URL")
        for attempt in range(retries):
            delay = max(0.0, 1.2 - (time.monotonic()-self.last_request))
            if delay:
                self.sleep(delay)
            self.last_request = time.monotonic()
            try:
                req = urllib.request.Request(url, headers={
                    "User-Agent": UA, "Accept": "application/json"})
                with self.opener(req, timeout=25) as response:
                    payload = json.load(response)
                if not isinstance(payload, dict):
                    raise ValueError("Unexpected data format")
                return payload
            except urllib.error.HTTPError as exc:
                if exc.code not in (429, 500, 502, 503, 504) or attempt == retries-1:
                    raise
                retry_after = exc.headers.get("Retry-After", "")
                try:
                    wait = float(retry_after)
                except ValueError:
                    wait = 0
                self.sleep(min(60, max(2**(attempt+1), wait)))
            except (urllib.error.URLError, TimeoutError):
                if attempt == retries-1:
                    raise
                self.sleep(min(60, 2**(attempt+1)))
        raise RuntimeError("Request retry exhausted")

    def artist_search(self, offset, limit=5):
        q = urllib.parse.urlencode({
            "query": "country:JP", "fmt": "json",
            "limit": limit, "offset": offset})
        return self.get(MB + "/ws/2/artist/?" + q).get("artists", [])

    def artist(self, mbid):
        return self.get(MB + "/ws/2/artist/" + mbid + "?inc=url-rels&fmt=json")

    def wikidata(self, qid):
        return self.get(WD + "/wiki/Special:EntityData/" + qid + ".json")

    def recordings(self, mbid, offset=0, limit=25):
        query = urllib.parse.urlencode({
            "artist": mbid, "limit": limit, "offset": offset,
            "fmt": "json"})
        return self.get(MB + "/ws/2/recording?" + query).get("recordings", [])


def artist_identity(client, payload):
    """Must have Japanese activity and cross-database MBID assertion."""
    mbid = payload.get("id")
    if not valid_mbid(mbid) or payload.get("country") != "JP":
        return False, None, None, "country_or_id_unconfirmed"
    rels = payload.get("relations") or []
    wd_urls = [r.get("url", {}).get("resource", "") for r in rels
               if r.get("type") == "wikidata" and isinstance(r.get("url"), dict)]
    qids = [u.rsplit("/", 1)[-1] for u in wd_urls if u.startswith("https://www.wikidata.org/wiki/")]
    official = [r.get("url", {}).get("resource", "") for r in rels
                if r.get("type") == "official homepage" and isinstance(r.get("url"), dict)]
    official = [u for u in official if u.startswith("https://") and len(u) <= 600]
    if not qids or not official:
        return False, qids[0] if qids else None, official[0] if official else None, "independent_identity_or_official_url_missing"
    qid = qids[0]
    if not valid_qid(qid):
        return False, None, official[0], "invalid_wikidata_id"
    try:
        wd = client.wikidata(qid).get("entities", {}).get(qid, {})
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError):
        return False, qid, official[0], "wikidata_unavailable"
    mbclaims = wd.get("claims", {}).get("P434", [])
    ids = [claim.get("mainsnak", {}).get("datavalue", {}).get("value") for claim in mbclaims]
    if mbid not in ids:
        return False, qid, official[0], "wikidata_musicbrainz_mismatch"
    return True, qid, official[0], ""


def credits_include_artist(row, artist_mbid):
    credits = row.get("artist-credit") or []
    return any(isinstance(x, dict) and isinstance(x.get("artist"), dict) and
               x["artist"].get("id") == artist_mbid for x in credits)


def init_artist_rows(db):
    """TK seed is a known, previously curated live artist, not a new discovery."""
    db.execute("""INSERT INTO ken_research_artists
        (artist_mbid,name,country,source_url,status,master_artist_id,source_count,registered_at)
        VALUES (%s,%s,'JP',%s,'registered',%s,2,now())
        ON CONFLICT (artist_mbid) DO NOTHING""",
        (TK_MBID, "TK from 凛として時雨",
         MB+"/artist/"+TK_MBID, TK_ARTIST_ID))


def record_event(db, lane, item_id, event, detail):
    db.execute("""INSERT INTO ken_research_events(lane,item_id,event_type,detail)
        VALUES(%s,%s,%s,%s::jsonb)""",
        (lane, str(item_id), event, json.dumps(detail, ensure_ascii=False)))


def artist_lane(db, client, budget=5):
    offset_row = db.execute("SELECT value FROM ken_research_state WHERE key='artist_offset'").fetchone()
    offset = int(offset_row["value"]) if offset_row else 0
    discovered = staged = promoted = 0
    listings = client.artist_search(offset, budget)
    for listing in listings:
        offset += 1
        mbid = listing.get("id")
        if not valid_mbid(mbid):
            continue
        discovered += 1
        item = client.artist(mbid)
        name = item.get("name", "")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 200:
            continue
        valid, qid, official, reason = artist_identity(client, item)
        country = item.get("country")
        status = "verified" if valid else "review"
        with db.transaction():
            db.execute("""INSERT INTO ken_research_artists
                (artist_mbid,name,country,artist_type,source_url,wikidata_qid,official_url,
                 source_count,status,review_reason,last_checked_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
                ON CONFLICT(artist_mbid) DO UPDATE SET
                 last_checked_at=now(), source_count=EXCLUDED.source_count,
                 review_reason=CASE WHEN ken_research_artists.status='registered'
                     THEN ken_research_artists.review_reason ELSE EXCLUDED.review_reason END,
                 status=CASE WHEN ken_research_artists.status='registered'
                     THEN 'registered' ELSE EXCLUDED.status END""",
                (mbid, name, country, item.get("type"), MB+"/artist/"+mbid,
                 qid, official, 2 if valid else 1, status, reason or None))
            staged += 1
            if valid:
                normalized = key(name)
                existing = db.execute(
                    "SELECT id FROM artists WHERE name_key=%s", (normalized,)).fetchone()
                if existing:
                    record_event(db, "artists", mbid, "review_existing_name", {
                        "name": name, "existing_id": existing["id"]})
                    db.execute("""UPDATE ken_research_artists SET status='review',
                       review_reason='existing_normalized_name_requires_human_match'
                       WHERE artist_mbid=%s AND status<>'registered'""", (mbid,))
                elif len(normalized) >= 2:
                    # Name identity and Wiki ↔ MusicBrainz linkage were verified.
                    row = db.execute("""INSERT INTO artists(name,name_key,identity_status)
                        VALUES(%s,%s,'source_confirmed')
                        ON CONFLICT(name_key) DO NOTHING RETURNING id""",
                        (name, normalized)).fetchone()
                    if row:
                        db.execute("""UPDATE ken_research_artists SET status='registered',
                          master_artist_id=%s,registered_at=now(),review_reason=NULL
                          WHERE artist_mbid=%s""", (row["id"], mbid))
                        record_event(db,"artists",mbid,"registered",{
                            "artist_id":row["id"],"wikidata":qid,"source":MB+"/artist/"+mbid})
                        promoted += 1
    if not listings:
        offset = 0
    with db.transaction():
        db.execute("""INSERT INTO ken_research_state(key,value) VALUES('artist_offset',%s)
             ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now()""", (str(offset),))
    return discovered, staged, promoted


def song_lane(db, client, budget=25):
    init_artist_rows(db)
    artist = db.execute("""SELECT artist_mbid,master_artist_id FROM ken_research_artists
        WHERE status='registered' AND master_artist_id IS NOT NULL
        ORDER BY last_checked_at ASC,artist_mbid LIMIT 1""").fetchone()
    if not artist:
        return 0,0,0
    mbid = str(artist["artist_mbid"])
    offset_key = "song_offset:"+mbid
    row=db.execute("SELECT value FROM ken_research_state WHERE key=%s", (offset_key,)).fetchone()
    offset=int(row["value"]) if row else 0
    records=client.recordings(mbid,offset,budget)
    discovered=staged=promoted=0
    for rec in records:
        rid=rec.get("id")
        title=rec.get("title","")
        if not valid_mbid(rid) or not isinstance(title,str) or not 1 <= len(title.strip()) <= 300:
            continue
        discovered+=1
        credit_ok=credits_include_artist(rec,mbid)
        clean=safe_title(title)
        reason = ("artist_credit_mismatch" if not credit_ok else
                  "version_or_non_song_requires_review" if not clean else None)
        status="verified" if not reason else "review"
        with db.transaction():
            db.execute("""INSERT INTO ken_research_songs
                 (recording_mbid,artist_mbid,title,source_url,first_release_date,
                  artist_credit_verified,status,review_reason)
                 VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
                 ON CONFLICT(recording_mbid) DO UPDATE SET last_checked_at=now()""",
                 (rid,mbid,title,MB+"/recording/"+rid,
                  rec.get("first-release-date"),credit_ok,status,reason))
            staged+=1
            if not reason:
                title_key=key(title)
                same=db.execute("""SELECT id FROM songs WHERE title_key=%s AND primary_artist_id=%s""",
                                (title_key,artist["master_artist_id"])).fetchone()
                # Existing title may be a version or variant; link recording only
                # after manual review. New unambiguous songs may be promoted.
                if same:
                    db.execute("""UPDATE ken_research_songs SET status='review',
                        review_reason='existing_title_requires_version_review'
                        WHERE recording_mbid=%s AND status<>'registered'""",(rid,))
                elif len(title_key)>=2:
                    row=db.execute("""INSERT INTO songs(title,title_key,primary_artist_id,
                          identity_status) VALUES(%s,%s,%s,'provisional')
                          ON CONFLICT(title_key,primary_artist_id) DO NOTHING RETURNING id""",
                          (title,title_key,artist["master_artist_id"])).fetchone()
                    if row:
                        # Preserve MBID and source without guessing song release date/readings.
                        db.execute("""INSERT INTO recordings(song_id,musicbrainz_recording_id)
                            VALUES(%s,%s) ON CONFLICT(musicbrainz_recording_id) DO NOTHING""",
                            (row["id"],rid))
                        db.execute("""UPDATE ken_research_songs SET status='registered',
                            master_song_id=%s,registered_at=now(),review_reason=NULL
                            WHERE recording_mbid=%s""",(row["id"],rid))
                        record_event(db,"songs",rid,"registered",{
                            "song_id":row["id"],"artist_id":artist["master_artist_id"]})
                        promoted+=1
        offset+=1
    if len(records) < budget:
        offset = 0
    with db.transaction():
        db.execute("""INSERT INTO ken_research_state(key,value) VALUES(%s,%s)
            ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now()""",
            (offset_key,str(offset)))
        db.execute("UPDATE ken_research_artists SET last_checked_at=now() WHERE artist_mbid=%s",(mbid,))
    return discovered,staged,promoted


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--lane",choices=["artists","songs"],required=True)
    parser.add_argument("--max-items",type=int,default=None)
    parser.add_argument("--dry-run",action="store_true")
    args=parser.parse_args()
    budget=args.max_items or (5 if args.lane=="artists" else 25)
    if not 1 <= budget <= (5 if args.lane=="artists" else 25):
        parser.error("Limit is 5 artists or 25 recordings per invocation")
    if args.dry_run:
        print("DRY_RUN; no network/DB writes. Verify in disposable DB first.")
        return
    dbname=os.environ.get("KEN_RESEARCH_DATABASE","ken_songs")
    if dbname not in ("ken_songs","ken_test"):
        raise SystemExit("Unknown database")
    client=Client()
    with psycopg.connect("dbname="+dbname,row_factory=dict_row,autocommit=True) as db:
        # Prevent overlapping workers and concurrent queue processing.
        locked=db.execute("SELECT pg_try_advisory_lock(214748,20261109) AS ok").fetchone()["ok"]
        if not locked: raise RuntimeError("Another research worker running")
        with db.transaction():
            run=db.execute("""INSERT INTO ken_research_runs(lane)
                VALUES(%s) RETURNING id""",(args.lane,)).fetchone()["id"]
        try:
            counts=(artist_lane(db,client,budget) if args.lane=="artists"
                    else song_lane(db,client,budget))
        except Exception as error:
            with db.transaction():
                db.execute("""UPDATE ken_research_runs SET status='failed',
                    error=%s,finished_at=now() WHERE id=%s""",(str(error)[:400],run))
            raise
        else:
            with db.transaction():
                db.execute("""UPDATE ken_research_runs SET
                    status='succeeded',discovered=%s,staged=%s,promoted=%s,
                    finished_at=now() WHERE id=%s""",(*counts,run))
            print(json.dumps({"lane":args.lane,"run_id":run,
                "discovered":counts[0],"staged":counts[1],
                "promoted":counts[2]},ensure_ascii=False))


if __name__=="__main__":
    main()
