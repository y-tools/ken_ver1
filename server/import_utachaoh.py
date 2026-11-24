#!/usr/bin/env python3
"""歌っちゃ王（YouTube @uta-cha-oh）動画一覧CSVを utachaoh_videos に取り込む。

使い方（VPS上）:
  KEN_IMPORT_DATABASE_URL=... python import_utachaoh.py /tmp/utachaoh_list.csv [--dry-run]

CSVの列: No, アーティスト, 曲名, 種別, 動画タイトル, URL
- アーティスト名・曲名は動画タイトルから付け直す（"曲名/アーティスト" 形式）
- 読みは Kenのデンモク楽曲DB（artist_names / song_names）にあればそれを使い、
  なければ pykakasi で自動推定（verification='estimated'）
- 人が確認済み（human_confirmed）の読みは上書きしない
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import unicodedata



def normalize(value: str) -> str:
    """import_catalog.normalize / api.main.norm と同じ正規化。"""
    value = unicodedata.normalize("NFKC", str(value)).casefold()
    value = "".join(chr(ord(ch) - 96) if "\u30a1" <= ch <= "\u30f6" else ch for ch in value)
    return re.sub(r"[\s\u3000\u30fb\u30fc\u2010-]", "", value)


JP_CHARS = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff\u3005\u3006]")
YOUTUBE_ID = re.compile(r"(?:v=|youtu\.be/|/shorts/)([A-Za-z0-9_-]{11})")
SPLIT = re.compile(r"^(.*)/\s*([^/]+/{0,2})$")


def clean_title(title: str) -> tuple[str, str, str]:
    """動画タイトル → (アーティスト, 曲名, 種別)."""
    s = unicodedata.normalize("NFC", title).strip()
    kinds: list[str] = []
    if re.search(r"#shorts", s, re.I):
        kinds.append("ショート")
        s = re.sub(r"\s*#shorts", "", s, flags=re.I)
    if "【立体音響カラオケ】" in s:
        kinds.append("立体音響")
    elif "生コーラス" in s:
        kinds.append("生コーラス")
        kinds.append("ガイドなし" if re.search(r"ガイド(メロ)?な|ガイなし", s) else "ガイドあり")
    elif "【ガイドなし】" in s:
        kinds.append("ガイドなし")
    elif "【カラオケ】" in s:
        kinds.append("ガイドあり")
    s = re.sub(r"【[^】]*】", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    artist, song = "", s
    m = SPLIT.match(s)
    if m:
        song, artist = m.group(1).strip(), m.group(2).strip()
        # "アーティスト - アニメ『…』OP" などの付記を落とす
        artist = re.split(r"\s+-\s+", artist, maxsplit=1)[0].strip()
    else:
        song = re.split(r"\s+-\s+", s, maxsplit=1)[0].strip()
    return artist, song, "・".join(kinds)


def is_latin(value: str) -> bool:
    return bool(value) and not JP_CHARS.search(value) and bool(re.search(r"[A-Za-z]", value))


class Reader:
    """pykakasi による推定読み。"""

    def __init__(self) -> None:
        import pykakasi  # 遅延import（--dry-run の構文確認時も必要）
        self.k = pykakasi.kakasi()
        self.cache: dict[str, tuple[str, str, str]] = {}

    def __call__(self, value: str) -> tuple[str, str, str]:
        """→ (ひらがな, カタカナ, ヘボン式ローマ字)。英字のみの名前はかなを空にする。"""
        if value in self.cache:
            return self.cache[value]
        if not value or not JP_CHARS.search(value):
            result = ("", "", "")
        else:
            items = self.k.convert(value)
            hira = "".join(i["hira"] for i in items).strip()
            kata = "".join(i["kana"] for i in items).strip()
            roma = " ".join(i["hepburn"] for i in items if i["hepburn"]).strip()
            result = (hira, kata, roma)
        self.cache[value] = result
        return result


BEST = {"human_confirmed": 0, "source_confirmed": 1, "derived_from_confirmed": 2, "estimated": 3}


def main_db_readings(cur, table_names: str, id_col: str, ids: list[int]) -> dict[int, dict[str, str]]:
    out: dict[int, dict[str, tuple[int, str]]] = {}
    if not ids:
        return {}
    cur.execute(
        f"SELECT {id_col}, kind, value, verification FROM {table_names} "
        f"WHERE {id_col} = ANY(%s) AND kind IN ('hiragana','katakana','english')",
        (ids,),
    )
    for ent, kind, value, ver in cur.fetchall():
        rank = BEST.get(ver, 9)
        cur_best = out.setdefault(ent, {}).get(kind)
        if cur_best is None or rank < cur_best[0]:
            out[ent][kind] = (rank, value)
    return {k: {kind: v[1] for kind, v in d.items()} for k, d in out.items()}


def search_key(*values: str) -> str:
    keys = []
    for v in values:
        k = normalize(v) if v else ""
        if k and k not in keys:
            keys.append(k)
    return "|".join(keys)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rows = []
    with open(args.csv, encoding="utf-8-sig", newline="") as f:
        for rec in csv.DictReader(f):
            url = rec.get("URL", "")
            m = YOUTUBE_ID.search(url)
            title = (rec.get("動画タイトル") or "").strip()
            if not m or not title:
                continue
            artist, song, kind = clean_title(title)
            rows.append({"youtube_id": m.group(1), "video_title": title, "video_type": kind,
                         "artist_name": artist, "song_title": song,
                         "channel_order": int(rec.get("No") or 0) or None})
    print(f"CSV rows: {len(rows)}")

    reader = Reader()
    import psycopg
    dsn = os.environ["KEN_IMPORT_DATABASE_URL"]
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        # Kenのデンモク楽曲DBの読みを流用（名前の正規化キー一致）
        akeys = {normalize(r["artist_name"]) for r in rows if r["artist_name"]}
        cur.execute("SELECT id, name_key FROM artists WHERE name_key = ANY(%s)", (list(akeys),))
        artist_id = {key: i for i, key in cur.fetchall()}
        a_read = main_db_readings(cur, "artist_names", "artist_id", list(artist_id.values()))
        pairs = {(normalize(r["song_title"]), artist_id[normalize(r["artist_name"])])
                 for r in rows if r["artist_name"] and normalize(r["artist_name"]) in artist_id}
        song_id: dict[tuple[str, int], int] = {}
        if pairs:
            cur.execute("SELECT id, title_key, primary_artist_id FROM songs WHERE primary_artist_id = ANY(%s)",
                        (list({p[1] for p in pairs}),))
            for sid, tkey, aid in cur.fetchall():
                if (tkey, aid) in pairs:
                    song_id[(tkey, aid)] = sid
        s_read = main_db_readings(cur, "song_names", "song_id", list(song_id.values()))

        stats = {"artist_main_db": 0, "song_main_db": 0}
        prepared = []
        for r in rows:
            aid = artist_id.get(normalize(r["artist_name"])) if r["artist_name"] else None
            sid = song_id.get((normalize(r["song_title"]), aid)) if aid else None
            ah, ak, ar = reader(r["artist_name"])
            sh, sk, sr = reader(r["song_title"])
            ae = r["artist_name"] if is_latin(r["artist_name"]) else ""
            se = r["song_title"] if is_latin(r["song_title"]) else ""
            aver = sver = "estimated"
            db = a_read.get(aid) if aid else None
            if db:
                ah, ak, ae = db.get("hiragana", ah), db.get("katakana", ak), db.get("english", ae)
                aver = "main_db"
                stats["artist_main_db"] += 1
            db = s_read.get(sid) if sid else None
            if db:
                sh, sk, se = db.get("hiragana", sh), db.get("katakana", sk), db.get("english", se)
                sver = "main_db"
                stats["song_main_db"] += 1
            prepared.append((
                r["youtube_id"], r["video_title"], r["video_type"],
                r["artist_name"], ah, ak, ae, aver,
                r["song_title"], sh, sk, se, sver,
                search_key(r["artist_name"], ah, ak, ae, ar),
                search_key(r["song_title"], sh, sk, se, sr),
                r["channel_order"],
            ))
        print(stats)
        for p in prepared[:5]:
            print(p[:13])
        if args.dry_run:
            print("dry-run: no changes")
            conn.rollback()
            return 0
        cur.executemany(
            """
INSERT INTO utachaoh_videos (youtube_id, video_title, video_type,
  artist_name, artist_hiragana, artist_katakana, artist_english, artist_reading_verification,
  song_title, song_hiragana, song_katakana, song_english, song_reading_verification,
  artist_search_key, song_search_key, channel_order)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
ON CONFLICT (youtube_id) DO UPDATE SET
  video_title=EXCLUDED.video_title, video_type=EXCLUDED.video_type, channel_order=EXCLUDED.channel_order,
  artist_name=CASE WHEN utachaoh_videos.artist_reading_verification='human_confirmed' THEN utachaoh_videos.artist_name ELSE EXCLUDED.artist_name END,
  artist_hiragana=CASE WHEN utachaoh_videos.artist_reading_verification='human_confirmed' THEN utachaoh_videos.artist_hiragana ELSE EXCLUDED.artist_hiragana END,
  artist_katakana=CASE WHEN utachaoh_videos.artist_reading_verification='human_confirmed' THEN utachaoh_videos.artist_katakana ELSE EXCLUDED.artist_katakana END,
  artist_english=CASE WHEN utachaoh_videos.artist_reading_verification='human_confirmed' THEN utachaoh_videos.artist_english ELSE EXCLUDED.artist_english END,
  artist_reading_verification=CASE WHEN utachaoh_videos.artist_reading_verification='human_confirmed' THEN 'human_confirmed' ELSE EXCLUDED.artist_reading_verification END,
  artist_search_key=CASE WHEN utachaoh_videos.artist_reading_verification='human_confirmed' THEN utachaoh_videos.artist_search_key ELSE EXCLUDED.artist_search_key END,
  song_title=CASE WHEN utachaoh_videos.song_reading_verification='human_confirmed' THEN utachaoh_videos.song_title ELSE EXCLUDED.song_title END,
  song_hiragana=CASE WHEN utachaoh_videos.song_reading_verification='human_confirmed' THEN utachaoh_videos.song_hiragana ELSE EXCLUDED.song_hiragana END,
  song_katakana=CASE WHEN utachaoh_videos.song_reading_verification='human_confirmed' THEN utachaoh_videos.song_katakana ELSE EXCLUDED.song_katakana END,
  song_english=CASE WHEN utachaoh_videos.song_reading_verification='human_confirmed' THEN utachaoh_videos.song_english ELSE EXCLUDED.song_english END,
  song_reading_verification=CASE WHEN utachaoh_videos.song_reading_verification='human_confirmed' THEN 'human_confirmed' ELSE EXCLUDED.song_reading_verification END,
  song_search_key=CASE WHEN utachaoh_videos.song_reading_verification='human_confirmed' THEN utachaoh_videos.song_search_key ELSE EXCLUDED.song_search_key END,
  updated_at=now()
""",
            prepared,
        )
        conn.commit()
        cur.execute("SELECT COUNT(*) FROM utachaoh_videos")
        print("utachaoh_videos rows:", cur.fetchone()[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
