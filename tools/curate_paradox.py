"""Build the curated Paradox Live entry from the Voice Drama Tracker made for the NAS archive.

    releases with a voice drama  -> series, grouped by release year (the NAS year folders)
    held drama parts             -> CDs; "Unit" = the team(s) the part is about; songs are left out
    the tracker's saved log      -> listened / finished / rating (5 stars -> /10) / notes

Inputs (both copied into imports/paradox_live/, the NAS stays read-only):
    voice_drama_tracker.html     the tracker page (its `R` release list: parts held, file lengths, notes)
    progress/*.json              the page's saved log (ArtifactData export of the `progress` collection)
Spotify durations (PARADOX LIVE ARCHIVE/paralive_catalogue.csv) fill parts the tracker has no file length for.
Covers come from each release folder on the NAS, shrunk into catalogue/covers/pl/.

    python tools/curate_paradox.py   -> imports/curated/paradox_live.json
"""
import csv
import json
import re
from difflib import SequenceMatcher
from pathlib import Path

import json5
from PIL import Image

from voice_actors import normalise_cv

HERE = Path(__file__).resolve().parent.parent
SRC = HERE / "imports" / "paradox_live"
NAS = Path(r"Z:\AUDIO\DRAMA CDs\Originals Drama CD\Paradox Live")
SPOTIFY = Path(r"D:\Claude\Projects\Audio & Drama CDs\PARADOX LIVE ARCHIVE\paralive_catalogue.csv")
COVERS = HERE / "catalogue" / "covers" / "pl"
UNITS = ["BAE", "The Cat's Whiskers", "cozmez", "悪漢奴等", "武雷管", "VISTY", "AMPRULE", "1Nm8", "獄Luck"]


def hkey(prefix, text):
    """The tracker's part key (djb2-xor, base 36), so its saved ticks map onto the right parts."""
    h = 5381
    for ch in text:
        h = ((h * 33) & 0xFFFFFFFF) ^ ord(ch)
    digits, out = "0123456789abcdefghijklmnopqrstuvwxyz", ""
    while True:
        h, r = divmod(h, 36)
        out = digits[r] + out
        if not h:
            return prefix + out


def units_in(text):
    text = text.replace("’", "'")
    return [u for u in UNITS if u.lower() in text.lower()]


def track_key(title):
    t = title.lower().replace("exibition", "exhibition").replace("voice drama", "").replace("-battle of unity-", "")
    return re.sub(r"[^\w]", "", t)


def part_no(title):
    m = re.search(r"(?:part|vol)\s*\.?\s*(\d+)", title, re.I)
    return m and m[1]


def spotify_track(spotify, release, part):
    """The Spotify drama track for one tracker part: same release date, same part number, closest title.
    Bonus parts (After Stories, YouTube extras) aren't on the CD, so they never match."""
    if part.get("bonus"):
        return None
    cands = [t for t in spotify if t["release_date"] == release["date"]]
    if part_no(part["n"]):
        cands = [t for t in cands if part_no(t["title"]) in (None, part_no(part["n"]))] or cands
    score = lambda t: SequenceMatcher(None, track_key(part["n"]), track_key(t["title"])).ratio()
    return max(cands, key=score, default=None)


# Spotify credits the 1st-season characters with their voice actors on the Opening Show dramas, and
# by character name alone on the shuffle dramas; this maps both onto unit + voice actor.
CHAR_ALIASES = {"矢戸乃上可波汰": "矢戸乃上珂波汰", "神林ヨウ平": "神林よう平"}


def cast_table(spotify):
    cast = {}
    for t in spotify:
        unit = units_in(t["title"])
        for credit in t["artists"].split("; "):
            m = re.fullmatch(r"(.+?)\(CV\.(.+?)\)", credit.strip())
            if m and len(unit) == 1:
                cast[m[1]] = (unit[0], m[2])
    return cast


def units_and_cv(track, cast):
    units, cvs = [], []
    for credit in track["artists"].split("; "):
        name = CHAR_ALIASES.get(credit.strip(), credit.strip())
        name = re.sub(r"\(CV\..*", "", name)
        if name in cast:
            units.append(cast[name][0])
            cvs.append(cast[name][1])
        else:
            units += units_in(name)
    return list(dict.fromkeys(units)), cvs


def mmss(text):
    m = re.fullmatch(r"(\d+):(\d\d)", text or "")
    return int(m[1]) * 60 + int(m[2]) if m else 0


def save_cover(release):
    folder = NAS / release["folder"].split("/DRAMA PARTS")[0] if release.get("folder") else None
    if not folder or not folder.is_dir():
        return ""
    images = sorted(p for p in folder.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"))
    if not images:
        return ""
    im = Image.open(images[0]).convert("RGB")
    im.thumbnail((400, 400))
    out = COVERS / f"{release['id']}.jpg"
    im.save(out, "JPEG", quality=85)
    return out.relative_to(HERE).as_posix()


def finished_on(log):
    """'20.9 - finished' -> 2026-09-20 (year from when it was saved); else the day it was saved."""
    saved = log.get("updatedAt", "")[:10]
    m = re.match(r"\s*(\d{1,2})\.(\d{1,2})\b", log.get("notes", ""))
    return f"{saved[:4]}-{int(m[2]):02d}-{int(m[1]):02d}" if m and saved else saved


def main():
    page = (SRC / "voice_drama_tracker.html").read_text(encoding="utf-8")
    releases = json5.loads(re.search(r"const R=(\[.*?\n\]);", page, re.S)[1])
    logs = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (SRC / "progress").glob("*.json")}
    spotify = [t for t in csv.DictReader(open(SPOTIFY, encoding="utf-8-sig")) if re.search(r"voice drama", t["title"], re.I)]
    cast = cast_table(spotify)
    COVERS.mkdir(parents=True, exist_ok=True)

    groups, not_owned, unknown_cv = {}, [], set()
    for r in releases:
        parts = [p for p in r.get("t", []) if not re.search(r"preview", p["n"], re.I)]  # a preview repeats the drama
        held = [p for p in parts if p.get("h")]
        not_owned += [f'{r["n"]}: {p["n"]}' for p in parts if not p.get("h")]
        if r.get("nodrama") or not held:
            continue
        log = logs.get(r["id"], {})
        heard = log.get("parts") or {}
        all_heard = log.get("listened") and not heard
        done = finished_on(log) if log else ""
        cover = save_cover(r)
        cds = []
        for n, p in enumerate(held, 1):
            track = spotify_track(spotify, r, p)
            units, cvs = units_and_cv(track, cast) if track else ([], [])
            units = sorted(units or units_in(p["n"]) or units_in(r.get("teams", "")), key=UNITS.index)
            cv, unknown = normalise_cv(", ".join(cvs))
            unknown_cv.update(unknown)
            secs = mmss(p.get("f")) or (int(track["duration_s"]) if track else 0)
            listened = bool(all_heard or heard.get(hkey("d", r["id"] + "|" + p["n"])))
            cd = {"no": n, "title": p["n"], "li": ", ".join(units), "cv": cv,
                  "runtime_min": round(secs / 60) if secs else "", "release": r["date"] if n == 1 else "",
                  "catalog_no": r.get("cat", ""), "cover": cover, "item": f'{r["id"]}#{n}', "listened": listened}
            if listened:
                cd.update(finished=done, time_min=cd["runtime_min"], time_source="runtime")
            cds.append(cd)
        contents = " ".join(filter(None, [r.get("note"), r.get("flag")]))
        groups.setdefault(r["date"][:4], []).append({
            "key": f"pl:{r['id']}", "title": r["n"], "kind": "Drama CD", "label": "avex", "release": r["date"],
            "cover": cover, "owned": "on NAS", "location": str(NAS / r["folder"].replace("/", "\\")),
            "contents": contents, "tags": "", "rating": str(log["rating"] * 2) if log.get("rating") else "",
            "notes": log.get("notes", "").strip(), "cds": cds,
        })

    entry = {"_source": "Paradox Live Voice Drama Tracker (NAS archive page + its saved log), Spotify durations "
                        "for parts without a file length; covers from the NAS release folders.",
             "franchise": {"name": "Paradox Live", "audience": "Joseimuke", "age": "AA", "cast_label": "Unit", "games": ""},
             "groups": [{"name": year, "order": n, "game": "", "series": series}
                        for n, (year, series) in enumerate(sorted(groups.items()), 1)],
             "not_owned": not_owned}
    out = HERE / "imports" / "curated" / "paradox_live.json"
    out.write_text(json.dumps(entry, ensure_ascii=False, indent=1), encoding="utf-8")
    cds = [cd for g in entry["groups"] for s in g["series"] for cd in s["cds"]]
    print(f"{len(entry['groups'])} groups, {sum(len(g['series']) for g in entry['groups'])} series, {len(cds)} CDs, "
          f"{sum(cd['listened'] for cd in cds)} listened, {sum(not cd['runtime_min'] for cd in cds)} without a runtime "
          f"({len(not_owned)} not owned, left out) -> {out}")
    if unknown_cv:
        print("voice actors not in catalogue/voice_actors.json (kept as written):", ", ".join(sorted(unknown_cv)))


if __name__ == "__main__":
    main()
