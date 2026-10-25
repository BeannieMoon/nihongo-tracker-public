"""Sync Japanese immersion history into NihongoTracker (nihongotracker.app).

Sources:
  gsm       GameSentenceMiner's daily per-game rollup (D:\\Tools\\GSM Data\\gsm.db); finished
            titles use jiten.moe's character count spread over GSM's daily proportions
  ttu       ッツ Reader statistics_*.json (Hoshi Reader / Chimahon novels sync these to
            Google Drive ttu-reader-data/<book>/), copied into imports/ttu/
  natively  finished books and videos on learnnatively.com (one log per item on its finish
            date; manga volumes get jiten.moe's per-volume character count)
  dramacd   drama CD sheet snapshot imports/dramacd_sheet.json (one audio log per CD on its
            finish date; temporary until audio gets its own tracker)
  chimahon  Chimahon backup (.tachibk) in imports/chimahon/: per-day manga OCR stats and
            novel stats (novel days share ids with ttu, so a day is never sent twice)
  manual    hand-entered logs in imports/manual.json (titles no other source knows about)
  jiten     everything marked Completed on jiten.moe (needs jiten.key): one log per title on
            its completion date; reading media get jiten's character count, anime/movies/audio
            their runtime. Titles another source already logged are skipped.
  youtube   Google Takeout watch-history.html in imports/youtube/: Japanese-spoken, non-music
            videos, one video log per channel per day (overrides in youtube_map.json)

Usage:
  python nt_sync.py check              verify the API key, show your account
  python nt_sync.py gsm                dry run: write out/gsm_preview.csv, send nothing
  python nt_sync.py gsm --push         send logs not sent before (tracked in sent.json)
  python nt_sync.py gsm --since 2026-10-01 --push
  python nt_sync.py ttu [--push]
  python nt_sync.py natively [--push]
  python nt_sync.py dramacd [--push]
  python nt_sync.py chimahon [--push]
  python nt_sync.py jiten [--push]
  python nt_sync.py youtube [--push]
  python nt_sync.py manual [--push]

The API key is read from the NT_API_KEY environment variable or from the
file `nihongotracker.key` next to this script (one line, the key only).
Every log carries a stable external id (manabeId) so re-runs never double-log.
"""
import argparse
import csv
import hashlib
import datetime as dt
import json
import os
import re
import shutil
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
API = "https://nihongotracker.app/api"
GSM_DIR = Path(r"D:\Tools\GSM Data")
SNAPSHOT_DIR = Path(r"D:\Claude\Temp\nihongo-tracker")
LEDGER = HERE / "sent.json"
OUT = HERE / "out"

GSM_TYPES = {"Visual Novel": "vn", "Game": "game", "Manga": "manga",
             "Light Novel": "light-novel", "Novel": "reading", "Unknown": "game"}
UNKNOWN_TITLE = "GSM (title not recorded)"
JITEN_API = "https://api.jiten.moe/api"
JITEN_CACHE = HERE / "jiten_cache.json"
NATIVELY_USER = "Ancabenca"
NATIVELY_MAP = HERE / "natively_map.json"
# Natively's import day: everything already read back then got this finish date.
NATIVELY_BULK_DAY = "2024-07-14"


# ---------- NihongoTracker API ----------

def api_key():
    key = os.environ.get("NT_API_KEY")
    if not key and (HERE / "nihongotracker.key").exists():
        key = (HERE / "nihongotracker.key").read_text(encoding="utf-8-sig").strip()
    if not key:
        sys.exit("No API key: create one at https://nihongotracker.app/settings and save it "
                 "to nihongotracker.key next to this script.")
    return key


def api(method, path, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method, headers={
        "X-API-Key": api_key(), "Content-Type": "application/json",
        "User-Agent": "nt_sync.py", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"{method} {path} -> HTTP {e.code}: {e.read().decode(errors='replace')[:500]}")


def load_ledger():
    return json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.exists() else {}


def push(logs, source):
    """Create logs not in the ledger. The external id doubles as the Idempotency-Key,
    so a retried request never creates a second log."""
    ledger = load_ledger()
    todo = [l for l in logs if l["manabeId"] not in ledger]
    print(f"{source}: {len(logs)} logs, {len(logs) - len(todo)} already sent, {len(todo)} to send")
    for n, l in enumerate(todo, 1):
        body = {k: v for k, v in l.items() if not k.startswith("_") and k != "manabeId"}
        res = api("POST", "/logs", body, {"Idempotency-Key": l["manabeId"]})
        ledger[l["manabeId"]] = res.get("_id") or res.get("log", {}).get("_id") or True
        LEDGER.write_text(json.dumps(ledger, indent=1, ensure_ascii=False), encoding="utf-8")
        if n % 25 == 0 or n == len(todo):
            print(f"  {n}/{len(todo)}")


def write_preview(logs, name):
    OUT.mkdir(exist_ok=True)
    path = OUT / name
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["date", "type", "mediaId", "time_min", "chars", "measured_chars",
                    "pages", "episodes", "unknown_date", "description", "manabeId"])
        for l in logs:
            w.writerow([l["date"][:10], l["type"], l.get("mediaId", ""), l.get("time", ""),
                        l.get("chars", ""), l.get("_measured", ""), l.get("pages", ""),
                        l.get("episodes", ""), "yes" if l.get("unknownDate") else "",
                        l["description"], l["manabeId"]])
    print(f"preview: {path}")


def log_date(day):
    # Noon local time, so the log lands on the right day whatever the site's timezone handling.
    return dt.datetime.fromisoformat(f"{day}T12:00:00").astimezone().isoformat()


# ---------- GSM ----------

def gsm_snapshot():
    """Copy gsm.db (+WAL) aside; GSM keeps the live file open."""
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("gsm.db", "gsm.db-wal"):
        src = GSM_DIR / name
        dst = SNAPSHOT_DIR / name
        if src.exists():
            shutil.copy2(src, dst)
        elif dst.exists():
            dst.unlink()
    return SNAPSHOT_DIR / "gsm.db"


def jiten_chars(deck_id):
    """Character count of a jiten.moe deck, cached in jiten_cache.json."""
    cache = json.loads(JITEN_CACHE.read_text(encoding="utf-8")) if JITEN_CACHE.exists() else {}
    if str(deck_id) not in cache:
        req = urllib.request.Request(f"{JITEN_API}/media-deck/{deck_id}/detail",
                                     headers={"User-Agent": "nt_sync.py"})
        with urllib.request.urlopen(req, timeout=30) as r:
            deck = json.load(r)["data"]["mainDeck"]
        cache[str(deck_id)] = {"title": deck["originalTitle"], "chars": deck["characterCount"]}
        JITEN_CACHE.write_text(json.dumps(cache, indent=1, ensure_ascii=False), encoding="utf-8")
    return cache[str(deck_id)]["chars"]


def scale_to_jiten(logs, jiten_total):
    """Spread jiten_total over a title's logs in proportion to the measured chars."""
    measured = sum(l["chars"] for l in logs)
    done = 0
    for i, l in enumerate(logs):
        l["_measured"] = l["chars"]
        if i == len(logs) - 1:
            l["chars"] = jiten_total - done  # rounding remainder goes on the last day
        else:
            l["chars"] = round(l["chars"] * jiten_total / measured)
            done += l["chars"]


def gsm_logs(since=None):
    mapping = json.loads((HERE / "media_map.json").read_text(encoding="utf-8"))
    db = sqlite3.connect(gsm_snapshot())
    rows = db.execute("""
        SELECT r.date, r.game_id, g.title_original, g.title_english, g.type, g.vndb_id,
               g.completed, g.deck_id,
               CAST(r.total_characters AS INTEGER), CAST(r.total_reading_time_seconds AS REAL)
        FROM game_daily_rollup r LEFT JOIN games g ON g.id = r.game_id
        ORDER BY r.date""").fetchall()
    # Days whose lines were purged survive only in the overall daily rollup, without a game.
    orphans = db.execute("""
        SELECT d.date, CAST(d.total_characters AS INTEGER) - COALESCE(SUM(CAST(r.total_characters AS INTEGER)), 0),
               CAST(d.total_reading_time_seconds AS REAL) - COALESCE(SUM(CAST(r.total_reading_time_seconds AS REAL)), 0)
        FROM daily_stats_rollup d LEFT JOIN game_daily_rollup r ON r.date = d.date
        GROUP BY d.date""").fetchall()
    db.close()
    rows += [(day, None, UNKNOWN_TITLE, None, "Visual Novel", "", "0", None, chars, secs)
             for day, chars, secs in orphans if chars >= 1000]
    # 'as' in media_map files one title's days under another GSM title, game metadata included.
    games = {r[2]: r[1:8] for r in rows if r[1]}
    rows = [(r[0], *games[mapping[r[2]]["as"]], *r[8:])
            if r[2] in mapping and "as" in mapping[r[2]] else r for r in rows]
    rows.sort(key=lambda r: r[0])

    merged = {}  # (date, media key) -> log; GSM sometimes has several game ids for one title
    finished = {}  # title -> jiten deck id, for titles GSM marks completed
    for day, game_id, title, title_en, gtype, vndb, completed, deck, chars, secs in rows:
        if not chars and not secs:
            continue
        title = title or title_en or game_id
        m = mapping.get(title, {})
        ltype = m.get("type") or GSM_TYPES.get(gtype or "", "game")
        media_id = m["mediaId"] if "mediaId" in m else (vndb or "")
        deck = m["jitenDeck"] if "jitenDeck" in m else deck
        if completed == "1" and deck:
            finished[title] = deck
        key = (day, media_id or title)
        log = merged.setdefault(key, {
            "type": ltype, "description": title, "date": log_date(day),
            "chars": 0, "time": 0.0,
            "manabeId": f"gsm:{day}:{media_id or 't' + hashlib.sha1(title.encode()).hexdigest()[:10]}",
            **({"mediaId": media_id} if media_id else {})})
        log["chars"] += chars or 0
        log["time"] += (secs or 0) / 60
    logs = list(merged.values())
    for l in logs:
        l["time"] = max(1, round(l["time"]))

    # Finished titles use jiten's character count, spread over the days in GSM's proportions.
    # Unfinished ones keep GSM's measured count: how much of jiten's total was read is unknown.
    for title, deck in finished.items():
        total = jiten_chars(deck)
        if total:
            scale_to_jiten([l for l in logs if l["description"] == title], total)
    # Stray OCR blips (no characters, a minute or less) aren't worth a log.
    return [l for l in logs if (not since or l["date"][:10] >= since)
            and not (l["chars"] == 0 and l["time"] <= 1)]


# ---------- ッツ Reader (Hoshi / Chimahon) ----------

def ttu_logs(since=None):
    mapping = json.loads((HERE / "media_map.json").read_text(encoding="utf-8"))
    today = dt.date.today().isoformat()
    days = {}  # newest statistics file per book wins, keyed by (title, day)
    for f in sorted((HERE / "imports" / "ttu").glob("statistics_*.json")):
        for e in json.loads(f.read_text(encoding="utf-8")):
            days[(e["title"], e["dateKey"])] = e
    logs = []
    for (title, day), e in sorted(days.items(), key=lambda kv: kv[0][1]):
        # Today is still being read; it gets sent once the day is over.
        if day >= today or (since and day < since) or e["charactersRead"] <= 0:
            continue
        m = mapping.get(title, {})
        media_id = m.get("mediaId", "")
        logs.append({
            "type": m.get("type", "reading"), "description": title, "date": log_date(day),
            "chars": e["charactersRead"], "time": max(1, round(e["readingTime"] / 60)),
            "manabeId": f"ttu:{day}:{media_id or 't' + hashlib.sha1(title.encode()).hexdigest()[:10]}",
            **({"mediaId": media_id} if media_id else {})})
    return logs


# ---------- LearnNatively ----------

def get_json(url, headers=None, attempts=3):
    req = urllib.request.Request(url, headers={"User-Agent": "nt_sync.py", **(headers or {})})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except (urllib.error.URLError, TimeoutError) as e:
            if isinstance(e, urllib.error.HTTPError) or attempt == attempts - 1:
                raise


def natively_library():
    """Finished items from the public library (books + videos), via the site's own API."""
    import http.cookiejar
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    page = f"https://learnnatively.com/user/{NATIVELY_USER}/jpn/books/"
    ua = {"User-Agent": "Mozilla/5.0 nt_sync.py"}
    opener.open(urllib.request.Request(page, headers=ua)).read()
    csrf = next((c.value for c in jar if c.name == "csrftoken"), "")
    items = []
    for lib in ("books", "videos"):
        req = urllib.request.Request(
            f"https://learnnatively.com/api/item-library-search-api/{NATIVELY_USER}/",
            data=json.dumps({"page": 1, "library_type": lib}).encode(),
            headers={**ua, "Content-Type": "application/json", "X-CSRFToken": csrf, "Referer": page})
        with opener.open(req, timeout=60) as r:
            items += [x for x in json.load(r)["results"] if x["status"] == "finished"]
    return items


def norm(t):
    return "".join(ch for ch in (t or "").lower() if ch.isalnum())


def nt_search(title, ntype):
    q = urllib.parse.urlencode({"search": title, "type": ntype})
    return get_json(f"{API}/media/search?{q}")


def nt_match(title, ntype):
    """First NT media whose native/English/romaji title equals the given title."""
    for m in nt_search(title, ntype)[:8]:
        names = [m["title"].get(k) for k in ("contentTitleNative", "contentTitleEnglish", "contentTitleRomaji")]
        if norm(title) in {norm(n) for n in names if n} | {norm(n) for n in m.get("synonyms") or []}:
            return m
    return None


def jiten_volume_chars(series, volume):
    """jiten.moe character count for one manga volume ('Volume N' subdeck of the series deck)."""
    q = urllib.parse.urlencode({"titleFilter": series})
    for deck in get_json(f"{JITEN_API}/media-deck/get-media-decks?{q}")["data"]:
        if deck["mediaType"] == 9 and norm(deck["originalTitle"]) == norm(series):
            subs = get_json(f"{JITEN_API}/media-deck/{deck['deckId']}/detail?pageSize=200")["data"]["subDecks"]
            for sub in subs:
                if norm(sub["originalTitle"]) == norm(f"Volume {volume}"):
                    return sub["characterCount"], sub["deckId"]
    return None, None


def natively_resolve(item):
    """Media + chars for one Natively item; cached in natively_map.json so it can be hand-edited."""
    cache = json.loads(NATIVELY_MAP.read_text(encoding="utf-8")) if NATIVELY_MAP.exists() else {}
    key = item["url"]
    if key not in cache:
        mt, title, series = item["mediaType"], item["title"].strip(), (item.get("seriesTitle") or "").strip()
        r = {"title": title}
        if mt == "manga":
            m = nt_match(series or title, "manga")
            chars, deck = jiten_volume_chars(series or title, item.get("seriesOrder") or 1)
            r.update(type="manga", mediaId=m["contentId"] if m else "", chars=chars, jitenDeck=deck)
        elif mt in ("light_novel", "novel", "childrens_book", "nonfiction", "graded_reader"):
            ntype = "light-novel" if mt == "light_novel" else "book"
            m = nt_match(title, ntype) or (nt_search(title, ntype) or [None])[0]
            r.update(type=ntype, mediaId=m["contentId"] if m else "", chars=None)
        elif mt == "movie":
            r.update(type="movie", mediaId=f"m{item['tmdbId']}" if item.get("tmdbId") else "")
        elif mt == "tv_season":
            m = nt_match(series or title, "anime")
            if m:
                r.update(type="anime", mediaId=m["contentId"], episodes=m.get("episodes"))
            else:
                m = nt_match(series or title, "tv show")
                r.update(type="tv show", mediaId=m["contentId"] if m else "")
        else:
            r.update(type="other", mediaId="")
        cache[key] = r
        NATIVELY_MAP.write_text(json.dumps(cache, indent=1, ensure_ascii=False), encoding="utf-8")
    return cache[key]


def natively_logs(since=None):
    logs = []
    for item in natively_library():
        it = item["item"]
        finished = (item.get("dateFinishedData") or {}).get("timestampDate")
        if not finished:
            continue
        day = dt.datetime.fromtimestamp(finished, dt.timezone.utc).date().isoformat()
        if since and day < since:
            continue
        r = natively_resolve({**it, "tmdbId": it.get("tmdbId")})
        log = {"type": r["type"], "description": it["title"].strip(), "date": log_date(day),
               "manabeId": f"natively:{it['id']}"}
        if r.get("mediaId"):
            log["mediaId"] = r["mediaId"]
        if r.get("chars"):
            log["chars"] = r["chars"]
        if it.get("pageCount") and r["type"] in ("manga", "book", "light-novel"):
            log["pages"] = it["pageCount"]
        if r["type"] in ("movie", "anime", "tv show") and it.get("runtime"):
            log["time"] = int(it["runtime"])
        if r.get("episodes") and r["type"] == "anime":
            log["episodes"] = r["episodes"]
        if day == NATIVELY_BULK_DAY:
            log["unknownDate"] = True
        logs.append(log)
    return sorted(logs, key=lambda l: l["date"])


# ---------- Drama CD sheet (temporary) ----------

def parse_minutes(text):
    """'6h*' -> 360, '55 min' / '32 miin' / '40 min?' -> minutes, '' -> None."""
    import re
    m = re.match(r"\s*(\d+(?:\.\d+)?)\s*(h|m)?", text or "")
    if not m:
        return None
    return round(float(m.group(1)) * (60 if m.group(2) == "h" else 1))


def parse_sheet_date(text, year):
    """'18.1.2025', '25:10.2025' (typo), '.03.2026' (day unknown), '7.7' (year missing)."""
    parts = [p for p in (text or "").replace(":", ".").split(".")]
    if len(parts) < 2 or not parts[1].strip():
        return None, False
    day, month = parts[0].strip(), int(parts[1])
    yr = int(parts[2]) if len(parts) > 2 and parts[2].strip() else year
    if not day:
        return dt.date(yr, month, 15).isoformat(), True
    return dt.date(yr, month, int(day)).isoformat(), False


def dramacd_logs(since=None):
    rows = json.loads((HERE / "imports" / "dramacd_sheet.json").read_text(encoding="utf-8"))["rows"]
    logs, year = [], 2025
    for name, start, finish, time, series in rows:
        day, unknown = parse_sheet_date(finish, year)
        if not day:
            continue  # still listening
        year = int(day[:4])
        if since and day < since:
            continue
        log = {"type": "audio", "description": name, "date": log_date(day),
               "manabeId": f"dramacd:{day}:{hashlib.sha1(name.encode()).hexdigest()[:10]}"}
        if not parse_minutes(time):
            print(f"skipped (no time in sheet; NihongoTracker requires it for audio): {name}")
            continue
        log["time"] = parse_minutes(time)
        if unknown:
            log["unknownDate"] = True
        logs.append(log)
    return sorted(logs, key=lambda l: l["date"])


# ---------- Chimahon backup ----------

def pb_fields(buf):
    """Minimal protobuf reader: yields (field number, wire type, value) for one message."""
    import struct
    i = 0
    def varint():
        nonlocal i
        shift = result = 0
        while True:
            b = buf[i]
            i += 1
            result |= (b & 0x7F) << shift
            if not b & 0x80:
                return result
            shift += 7
    while i < len(buf):
        key = varint()
        field, wire = key >> 3, key & 7
        if wire == 0:
            yield field, wire, varint()
        elif wire == 1:
            yield field, wire, struct.unpack("<d", buf[i:i + 8])[0]
            i += 8
        elif wire == 2:
            n = varint()
            yield field, wire, buf[i:i + n]
            i += n
        elif wire == 5:
            yield field, wire, struct.unpack("<f", buf[i:i + 4])[0]
            i += 4
        else:
            raise ValueError(f"unsupported wire type {wire}")


def pb_message(buf, schema):
    """Decode into a dict using {field: (name, kind)}; kind is str/int/float/bytes/list:<schema>."""
    out = {name: [] for name, kind in schema.values() if isinstance(kind, dict)}
    for field, wire, value in pb_fields(buf):
        if field not in schema:
            continue
        name, kind = schema[field]
        if isinstance(kind, dict):
            out[name].append(pb_message(value, kind))
        elif kind is str:
            out[name] = value.decode("utf-8", "replace")
        else:
            out[name] = value
    return out


CHIMAHON_SCHEMA = {
    1: ("manga", {3: ("title", str), 800: ("customTitle", str),
                  104: ("history", {1: ("url", str), 2: ("lastRead", int), 3: ("readDuration", int)})}),
    700: ("novels", {2: ("title", str), 7: ("characterCount", int),
                     9: ("stats", {1: ("dateKey", str), 2: ("charactersRead", int), 3: ("readingTime", float)})}),
    710: ("mangaStats", {1: ("dateKey", str), 2: ("charactersRead", int), 3: ("readingTime", int),
                         4: ("mangaId", int)}),
}


def chimahon_backup():
    import gzip
    files = sorted((HERE / "imports" / "chimahon").glob("*.tachibk"), key=lambda f: f.stat().st_mtime)
    if not files:
        sys.exit("No Chimahon backup: in Chimahon create a backup and copy the .tachibk into imports/chimahon/")
    return pb_message(gzip.decompress(files[-1].read_bytes()), CHIMAHON_SCHEMA)


def chimahon_titles(backup, stats):
    """mangaId -> title. The backup has no manga ids, so each id is matched to the manga whose
    chapter read dates overlap its stat days the most (override in chimahon_map.json)."""
    overrides_path = HERE / "chimahon_map.json"
    overrides = json.loads(overrides_path.read_text(encoding="utf-8")) if overrides_path.exists() else {}
    read_days = {}
    for m in backup["manga"]:
        title = m.get("customTitle") or m.get("title", "")
        read_days[title] = {dt.datetime.fromtimestamp(h["lastRead"] / 1000).date().isoformat()
                            for h in m["history"] if h.get("lastRead")}
    titles = {}
    for manga_id in {s["mangaId"] for s in stats}:
        days = {s["dateKey"] for s in stats if s["mangaId"] == manga_id}
        best = max(read_days.items(), key=lambda kv: len(kv[1] & days), default=(None, set()))
        titles[manga_id] = overrides.get(str(manga_id)) or (best[0] if best[1] & days else f"Chimahon manga #{manga_id}")
    overrides_path.write_text(json.dumps({str(k): v for k, v in sorted(titles.items())}, indent=1,
                                         ensure_ascii=False), encoding="utf-8")
    return titles


def chimahon_logs(since=None):
    mapping = json.loads((HERE / "media_map.json").read_text(encoding="utf-8"))
    backup = chimahon_backup()
    today = dt.date.today().isoformat()
    stats = [s for s in backup["mangaStats"] if s.get("charactersRead") or s.get("readingTime")]
    titles = chimahon_titles(backup, stats)
    merged = {}
    for s in stats:
        day = s["dateKey"]
        if day >= today or (since and day < since):
            continue
        title = titles[s["mangaId"]]
        m = mapping.get(title, {})
        media_id = m.get("mediaId", "")
        log = merged.setdefault((day, title), {
            "type": m.get("type", "manga"), "description": title, "date": log_date(day),
            "chars": 0, "time": 0.0,
            "manabeId": f"chimahon:{day}:{media_id or 't' + hashlib.sha1(title.encode()).hexdigest()[:10]}",
            **({"mediaId": media_id} if media_id else {})})
        log["chars"] += s.get("charactersRead", 0)
        log["time"] += s.get("readingTime", 0) / 60000
    logs = list(merged.values())
    for l in logs:
        l["time"] = max(1, round(l["time"]))
    # Novel days use the ttu id scheme: the same book synced through ッツ is the same log.
    for novel in backup["novels"]:
        title = novel.get("title", "")
        m = mapping.get(title, {})
        media_id = m.get("mediaId", "")
        for e in novel["stats"]:
            day = e["dateKey"]
            if day >= today or (since and day < since) or e.get("charactersRead", 0) <= 0:
                continue
            logs.append({
                "type": m.get("type", "reading"), "description": title, "date": log_date(day),
                "chars": e["charactersRead"], "time": max(1, round(e.get("readingTime", 0) / 60)),
                "manabeId": f"ttu:{day}:{media_id or 't' + hashlib.sha1(title.encode()).hexdigest()[:10]}",
                **({"mediaId": media_id} if media_id else {})})
    return sorted(logs, key=lambda l: l["date"])


# ---------- jiten.moe completed titles ----------

def jiten_get(path):
    key_file = HERE / "jiten.key"
    if not key_file.exists():
        sys.exit("No jiten key: create one in jiten.moe settings and save it to jiten.key next to this script.")
    key = key_file.read_text(encoding="utf-8-sig").strip()
    return get_json(f"{JITEN_API}{path}", {"X-Api-Key": key})


# jiten media type -> (NT log type, counts characters as reading)
JITEN_TYPES = {1: ("anime", False), 2: ("tv show", False), 3: ("movie", False), 4: ("light-novel", True),
               5: ("book", True), 6: ("game", True), 7: ("vn", True), 8: ("reading", True),
               9: ("manga", True), 10: ("audio", False), 11: ("video", False)}


def jiten_completed():
    decks, offset = [], 0
    while True:
        q = urllib.parse.urlencode({"status": "completed", "offset": offset})
        page = jiten_get(f"/media-deck/get-media-decks?{q}")
        decks += page["data"]
        offset += len(page["data"])
        if not page["data"] or offset >= page["totalItems"]:
            return decks


def jiten_media_id(ntype, links):
    """NT contentId from a jiten deck's external links (games have none usable: NT keys IGDB by number)."""
    urls = [l.get("url", "") for l in links or []]
    pick = lambda pattern: next((m.group(1) for u in urls for m in [re.search(pattern, u)] if m), "")
    if ntype == "vn":
        return pick(r"vndb\.org/(v\d+)")
    if ntype in ("anime", "manga", "light-novel"):
        return pick(r"anilist\.co/(?:anime|manga)/(\d+)")
    if ntype in ("movie", "tv show"):
        tmdb = pick(r"themoviedb\.org/(?:movie|tv)/(\d+)")
        return (("m" if ntype == "movie" else "s") + tmdb) if tmdb else ""
    return ""


def nt_watch_minutes(ntype, media_id, episodes=None):
    """Watch time from NihongoTracker's media details: episodes x episode length, or movie runtime."""
    m = get_json(f"{API}/media/{urllib.parse.quote(ntype)}/{media_id}")
    if m.get("runtime"):
        return m["runtime"]
    if m.get("episodeDuration"):
        return (episodes or m.get("episodes") or 1) * m["episodeDuration"]
    return None


def gsm_jiten_decks():
    db = sqlite3.connect(gsm_snapshot())
    decks = {str(d) for (d,) in db.execute("SELECT deck_id FROM games WHERE deck_id IS NOT NULL")}
    db.close()
    return decks


def already_logged_media():
    """NT media ids that other sources already sent logs for (GSM, ttu, Natively)."""
    ids = set()
    for source in (gsm_logs, ttu_logs, natively_logs):
        ids |= {l.get("mediaId") for l in source()}
    return ids - {None, ""}


def jiten_logs(since=None):
    already = already_logged_media()
    gsm_decks = gsm_jiten_decks()
    jmap_path = HERE / "jiten_map.json"
    jmap = json.loads(jmap_path.read_text(encoding="utf-8")) if jmap_path.exists() else {}
    logs = []
    for deck in jiten_completed():
        over = jmap.get(str(deck["deckId"]), {})
        if over.get("skip") or str(deck["deckId"]) in gsm_decks:
            print(f"skipped ({over.get('skip') or 'tracked by GSM'}): {deck['originalTitle']}")
            continue
        detail = jiten_get(f"/media-deck/{deck['deckId']}/detail")["data"]["mainDeck"]
        ntype, reading = JITEN_TYPES.get(detail["mediaType"], ("other", False))
        ntype = over.get("type", ntype)
        title = detail["originalTitle"]
        media_id = over.get("mediaId") or jiten_media_id(ntype, detail.get("links"))
        if not media_id and ntype in ("game", "light-novel", "book", "manga", "anime", "movie", "tv show"):
            m = nt_match(title, ntype)
            media_id = m["contentId"] if m else ""
        if media_id and media_id in already:
            print(f"skipped (already logged from another source): {title}")
            continue
        entry = detail.get("listEntry") or {}
        day = (entry.get("finishedOn") or entry.get("lastCompletedOn") or "")[:10]
        log = {"type": ntype, "description": title, "date": log_date(day or dt.date.today().isoformat()),
               "manabeId": f"jiten:{deck['deckId']}"}
        if reading and detail.get("characterCount"):
            log["chars"] = detail["characterCount"]
        runtime = detail.get("runtimeSeconds")
        if runtime and not reading:
            log["time"] = round(runtime / 60)
        if ntype == "anime" and detail.get("childrenDeckCount"):
            log["episodes"] = detail["childrenDeckCount"]
        if media_id:
            log["mediaId"] = media_id
            if "time" not in log and ntype in ("anime", "movie", "tv show"):
                minutes = nt_watch_minutes(ntype, media_id, log.get("episodes"))
                if minutes:
                    log["time"] = minutes
        if not day:
            log["unknownDate"] = True
            logs.append(log)
            continue
        start = (entry.get("startedOn") or day)[:10]
        logs += [l for l in spread_log(log, start, day) if not since or l["date"][:10] >= since]
    return sorted(logs, key=lambda l: l["date"])


_GSM_PATTERN = None


def gsm_pattern():
    """Your real reading rhythm from GSM VN days: chars per active day, chars/hour,
    lengths of consecutive-day runs and of the gaps between them."""
    global _GSM_PATTERN
    if _GSM_PATTERN is None:
        chars, mins = {}, {}
        for l in gsm_logs():
            if l["type"] == "vn":
                d = l["date"][:10]
                chars[d] = chars.get(d, 0) + l.get("_measured", l["chars"])
                mins[d] = mins.get(d, 0) + l["time"]
        days = sorted(dt.date.fromisoformat(d) for d in chars)
        runs, gaps, run = [], [], 1
        for a, b in zip(days, days[1:]):
            if (b - a).days == 1:
                run += 1
            else:
                runs.append(run)
                gaps.append((b - a).days - 1)
                run = 1
        runs.append(run)
        speeds = [chars[d] / (mins[d] / 60) for d in chars if mins[d] >= 20]
        _GSM_PATTERN = {"chars": sorted(chars.values()), "speeds": speeds, "runs": runs, "gaps": gaps}
    return _GSM_PATTERN


def spread_log(log, start, finish):
    """Turn one completed jiten title into day logs that look like GSM history: active days
    sized like your real GSM days, in runs and gaps like yours, from the jiten start date to
    the finish date. Reading time comes from your GSM speed. Seeded per title, so re-runs
    produce the same days (and the same idempotency keys)."""
    import random
    rng = random.Random(log["manabeId"])
    pat = gsm_pattern()
    first, last = dt.date.fromisoformat(min(start, finish)), dt.date.fromisoformat(finish)
    span = (last - first).days + 1

    # How much happens on each active day: real GSM day sizes for reading, 1-4 episodes for anime.
    if log.get("chars"):
        total, pick = log["chars"], lambda: rng.choice(pat["chars"])
    elif log.get("episodes"):
        total, pick = log["episodes"], lambda: rng.randint(1, 4)
    else:
        total, pick = log.get("time", 0), lambda: rng.choice((30, 45, 60, 90, 120))
    amounts = []
    while sum(amounts) < total and len(amounts) < span:
        amounts.append(pick())

    # Which days: the start day, then runs/gaps walked back from the finish day.
    days = {last}
    day = last
    while len(days) < len(amounts) - 1 and day > first:
        for _ in range(rng.choice(pat["runs"])):
            if day <= first or len(days) >= len(amounts) - 1:
                break
            days.add(day)
            day -= dt.timedelta(1)
        day -= dt.timedelta(rng.choice(pat["gaps"]) + 1)
    days.add(first)
    days = sorted(days)[:len(amounts)] if len(days) > len(amounts) else sorted(days)

    # Scale the day sizes so they add up exactly to the title's total.
    sizes = amounts[:len(days)]
    scaled = [round(a * total / sum(sizes)) for a in sizes]
    scaled[-1] += total - sum(scaled)

    out = []
    for d, amount in zip(days, scaled):
        if amount <= 0:
            continue
        part = {k: v for k, v in log.items() if k not in ("chars", "episodes", "time")}
        if log.get("chars"):
            part["chars"] = amount
            part["time"] = max(1, round(amount / rng.choice(pat["speeds"]) * 60))
        elif log.get("episodes"):
            part["episodes"] = amount
            part["time"] = round(log.get("time", 24 * log["episodes"]) * amount / log["episodes"])
        else:
            part["time"] = amount
        part["date"] = log_date(d.isoformat())
        part["manabeId"] = f"{log['manabeId']}:{d.isoformat()}"
        out.append(part)
    return out


# ---------- YouTube (Google Takeout watch history) ----------

YT_CACHE = HERE / "youtube_cache.json"
YT_MAP = HERE / "youtube_map.json"
# Kana used as decoration in usernames (ツ, シ, ...) doesn't make a title Japanese.
YT_DECOR = re.compile(r"[ツシッゞー・ノ]")
YT_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
# YouTube files voice dramas, situation CDs and voiced manga shorts under Music too.
YT_SPOKEN = re.compile(r"ドラマ|drama|ボイス|voice|漫画|朗読|シチュエーション|asmr|ラジオ|radio|雑談", re.I)
YT_SONG = re.compile(r"歌|曲|bgm|song|playlist|作業用|mv\b|music video|cover", re.I)


def yt_kana(text):
    return len(re.findall(r"[ぁ-ゖァ-ヺ]", YT_DECOR.sub("", text or ""))) >= 2


def yt_history():
    """Watched videos from the newest Takeout watch-history.html in imports/youtube/."""
    import html as htmllib
    files = sorted((HERE / "imports" / "youtube").glob("watch-history*.html"), key=lambda f: f.stat().st_mtime)
    if not files:
        sys.exit("No Takeout export: copy YouTube and YouTube Music/history/watch-history.html into imports/youtube/")
    text = files[-1].read_text(encoding="utf-8")
    cell = re.compile(r'mdl-typography--title">(.*?)<br>.*?mdl-typography--body-1">Watched\xa0'
                      r'<a href="https://www\.youtube\.com/watch\?v=([\w-]{11})">(.*?)</a><br>'
                      r'<a href="https://www\.youtube\.com/channel/([\w-]+)">(.*?)</a><br>(.*?)<br>', re.S)
    out = []
    for c in text.split('<div class="outer-cell')[1:]:
        m = cell.search(c)
        # YouTube Music plays are songs; ads come from Google Ads; removed videos have no channel.
        if not m or m.group(1) != "YouTube" or "From Google Ads" in c:
            continue
        # '30 Sept 2026, 21:22:43 CET' (Takeout writes 'Sept', which %b doesn't know)
        day, month, year = m.group(6).split(",")[0].split()
        when = dt.date(int(year), YT_MONTHS.index(month[:3].lower()) + 1, int(day))
        out.append({"vid": m.group(2), "title": htmllib.unescape(m.group(3)), "chid": m.group(4),
                    "channel": htmllib.unescape(m.group(5)), "day": when.isoformat()})
    return out


def yt_meta(vid):
    """Length, category and auto-caption language from the watch page (asr language = what's spoken)."""
    req = urllib.request.Request(f"https://www.youtube.com/watch?v={vid}&hl=en", headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/130.0 Safari/537.36", "Accept-Language": "en", "Cookie": "SOCS=CAI"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                page = r.read().decode("utf-8", "replace")
            break
        except urllib.error.HTTPError as e:
            if e.code == 429:
                raise  # rate limited: the caller backs off
            if attempt == 2:
                return None  # not cached, retried next run
        except (urllib.error.URLError, TimeoutError):
            if attempt == 2:
                return None
    m = re.search(r"ytInitialPlayerResponse\s*=\s*(\{.+?\});(?:var|</script>)", page)
    if not m:
        return None
    p = json.loads(m.group(1))
    vd = p.get("videoDetails", {})
    tracks = p.get("captions", {}).get("playerCaptionsTracklistRenderer", {}).get("captionTracks", [])
    return {"status": p.get("playabilityStatus", {}).get("status"),
            "seconds": int(vd.get("lengthSeconds") or 0),
            "category": p.get("microformat", {}).get("playerMicroformatRenderer", {}).get("category"),
            "asr": next((t["languageCode"] for t in tracks if t.get("kind") == "asr"), None)}


def yt_metadata(vids):
    """yt_meta for every video id, cached in youtube_cache.json. One page at a time: YouTube
    answers parallel fetching with 429s within a few hundred requests."""
    import time
    cache = json.loads(YT_CACHE.read_text(encoding="utf-8")) if YT_CACHE.exists() else {}
    save = lambda: YT_CACHE.write_text(json.dumps(cache, indent=0, ensure_ascii=False), encoding="utf-8")
    todo = sorted(set(vids) - set(cache))
    if todo:
        print(f"youtube: fetching {len(todo)} video pages")
    backoff = 0
    for n, vid in enumerate(todo, 1):
        while True:
            try:
                meta = yt_meta(vid)
                backoff = 0
                break
            except urllib.error.HTTPError:
                backoff += 1
                if backoff > 5:
                    save()
                    sys.exit(f"YouTube keeps rate limiting ({n - 1}/{len(todo)} fetched, cached); run again later.")
                print(f"  rate limited, waiting {backoff * 5} min")
                time.sleep(backoff * 300)
        if meta:
            cache[vid] = meta
        if n % 50 == 0 or n == len(todo):
            save()
            print(f"  {n}/{len(todo)}")
        time.sleep(3)
    return cache


def yt_japanese(w, m, jp_spoken, jp_titled):
    """Spoken Japanese, not a song. The auto-caption (asr) language follows the uploader's language
    setting, so it is wrong both ways: Japanese channels often show en-US/ko/id (a kana title counts
    when the channel is mostly Japanese-spoken), and English shorts sometimes show ja (an English
    title counts only with kanji in it or on a Japanese channel)."""
    if m["asr"] == "ja":
        japanese = (yt_kana(w["title"]) or yt_kana(w["channel"]) or w["chid"] in jp_titled
                    or bool(re.search(r"[一-鿿]", w["title"] + w["channel"])))
    else:
        japanese = (yt_kana(w["title"]) and w["chid"] in jp_spoken
                    and not re.search(r"[가-힯]", w["title"]))
    if not japanese or m["category"] != "Music":
        return japanese
    return bool(YT_SPOKEN.search(w["title"])) or (
        m["asr"] == "ja" and m["seconds"] >= 15 * 60 and not YT_SONG.search(w["title"]))


def youtube_logs(since=None):
    """One video log per channel per day: Japanese-spoken videos (see yt_japanese), music excluded.
    Each video counts its full length once per day. youtube_map.json overrides by channel or video
    id: "skip", "keep", or a number of minutes for one video."""
    over = json.loads(YT_MAP.read_text(encoding="utf-8")) if YT_MAP.exists() else {}
    today = dt.date.today().isoformat()
    watched = [w for w in yt_history() if not w["channel"].endswith(" - Topic")
               and w["day"] < today and (not since or w["day"] >= since)]
    # Only channels that ever show Japanese (or a CJK title) are probed; 30k pages would be a lot.
    jp_channels = {w["chid"] for w in watched if yt_kana(w["title"]) or yt_kana(w["channel"])}
    cand = [w for w in watched if w["chid"] in jp_channels or w["chid"] in over or w["vid"] in over
            or re.search(r"[ぁ-ヿ一-鿿]", w["title"])]
    meta = yt_metadata([w["vid"] for w in cand])
    # Channels whose captioned videos are mostly (60%+) auto-captioned as Japanese.
    asr = {}
    for w in cand:
        if meta.get(w["vid"], {}).get("asr"):
            asr.setdefault(w["chid"], {})[w["vid"]] = meta[w["vid"]]["asr"] == "ja"
    jp_spoken = {ch for ch, v in asr.items() if sum(v.values()) / len(v) >= 0.6}
    # Channels where at least half the watched titles are in Japanese.
    titles = {}
    for w in cand:
        titles.setdefault(w["chid"], []).append(yt_kana(w["title"]))
    jp_titled = {ch for ch, v in titles.items() if sum(v) / len(v) >= 0.5}

    merged, seen = {}, set()
    for w in sorted(cand, key=lambda w: w["day"]):
        m = meta.get(w["vid"])
        rule = over.get(w["vid"], over.get(w["chid"]))
        if rule == "skip" or not m or m["status"] != "OK" or not m["seconds"] or (w["day"], w["vid"]) in seen:
            continue
        if rule != "keep" and not isinstance(rule, (int, float)) and not yt_japanese(w, m, jp_spoken, jp_titled):
            continue
        seen.add((w["day"], w["vid"]))
        log = merged.setdefault((w["day"], w["chid"]), {
            "type": "video", "mediaId": w["chid"], "date": log_date(w["day"]), "time": 0.0,
            "manabeId": f"youtube:{w['day']}:{w['chid']}", "_channel": w["channel"], "_titles": []})
        log["time"] += rule if isinstance(rule, (int, float)) else m["seconds"] / 60
        log["_titles"].append(w["title"])
    logs = list(merged.values())
    for l in logs:
        l["time"] = max(1, round(l["time"]))
        t = l["_titles"]
        l["description"] = t[0] if len(t) == 1 else f"{l['_channel']} ({len(t)} videos)"
    return logs


# ---------- hand-entered ----------

def manual_logs(since=None):
    """imports/manual.json: [{"id", "type", "description", "mediaId"?, "date" (finish day; omit for
    unknown), "start"? (spread start..date like GSM days), "chars"?, "time"?, "episodes"?, "completed"?}]"""
    logs = []
    for e in json.loads((HERE / "imports" / "manual.json").read_text(encoding="utf-8")):
        day = e.get("date") or dt.date.today().isoformat()
        if since and e.get("date") and day < since:
            continue
        log = {k: e[k] for k in ("type", "description", "mediaId", "chars", "time", "episodes") if e.get(k)}
        log.update(date=log_date(day), manabeId=f"manual:{e['id']}")
        if not e.get("date"):
            log["unknownDate"] = True
            logs.append(log)
        elif e.get("start"):
            logs += spread_log(log, e["start"], day)  # played over a period: GSM-style days
        else:
            logs.append(log)
    return logs


def report(logs, name, source, push_it):
    write_preview(logs, name)
    chars = sum(l.get("chars", 0) for l in logs)
    mins = sum(l.get("time", 0) for l in logs)
    untracked = sorted({l["description"] for l in logs if "mediaId" not in l})
    print(f"{len(logs)} daily logs, {chars:,} chars, {mins / 60:.1f} h, "
          f"{logs[0]['date'][:10] if logs else '-'} .. {logs[-1]['date'][:10] if logs else '-'}")
    if untracked:
        print("no media match (logged by title only):", ", ".join(untracked))
    if push_it:
        push(logs, source)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    for name in ("gsm", "ttu", "natively", "dramacd", "chimahon", "jiten", "youtube", "manual"):
        g = sub.add_parser(name)
        g.add_argument("--since", help="only days on/after YYYY-MM-DD")
        g.add_argument("--push", action="store_true", help="actually send to NihongoTracker")
    a = ap.parse_args()

    if a.cmd == "check":
        me = api("GET", "/users/me")
        print(json.dumps({k: me.get(k) for k in ("username", "stats", "settings") if k in me},
                         ensure_ascii=False, indent=1)[:1500])
    elif a.cmd == "gsm":
        report(gsm_logs(a.since), "gsm_preview.csv", "gsm", a.push)
    elif a.cmd == "ttu":
        report(ttu_logs(a.since), "ttu_preview.csv", "ttu", a.push)
    elif a.cmd == "natively":
        report(natively_logs(a.since), "natively_preview.csv", "natively", a.push)
    elif a.cmd == "dramacd":
        report(dramacd_logs(a.since), "dramacd_preview.csv", "dramacd", a.push)
    elif a.cmd == "chimahon":
        report(chimahon_logs(a.since), "chimahon_preview.csv", "chimahon", a.push)
    elif a.cmd == "jiten":
        report(jiten_logs(a.since), "jiten_preview.csv", "jiten", a.push)
    elif a.cmd == "youtube":
        report(youtube_logs(a.since), "youtube_preview.csv", "youtube", a.push)
    elif a.cmd == "manual":
        report(manual_logs(a.since), "manual_preview.csv", "manual", a.push)
        if a.push:  # completed / ongoing flags for the titles entered by hand
            for e in json.loads((HERE / "imports" / "manual.json").read_text(encoding="utf-8")):
                if e.get("mediaId") and "completed" in e:
                    api("POST", "/users/media/status", {"mediaId": e["mediaId"], "type": e["type"],
                                                        "completed": e["completed"], "source": "manual"})

if __name__ == "__main__":
    main()
