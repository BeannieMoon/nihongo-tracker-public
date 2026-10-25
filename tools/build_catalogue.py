"""Build the audio catalogue (owned works only) from the collection data already gathered.

Sources, all things you own:
  Z:\\AUDIO inventory      inventory/z_audio.csv (tools/inventory_audio.py)
  Paradox Live            per-release folders on Z:, voice drama only (songs are music)
  HypMic                  drama tracks captured from Spotify (HYPMIC SPOTIFY BACKUP/tracks.csv)
  Diabolik Lovers         dl_catalog.json items with have_audio (DIABOLIK LOVERS catalogue)

    python tools/build_catalogue.py    -> catalogue/works.csv + .xlsx

Read-only towards every source; writes only into catalogue/.
"""
import csv
import json
import os
import re
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "tools"))
from inventory_audio import VIDEO_EXT, duration, long_path, short_path  # noqa: E402
from catalogue_audio import AUDIO_EXT  # noqa: E402  (on sys.path via inventory_audio)

AUDIO_PROJECTS = Path(r"D:\Claude\Projects\Audio & Drama CDs")
PARADOX = Path(r"Z:\AUDIO\DRAMA CDs\Originals Drama CD\Paradox Live")
OUT = HERE / "catalogue"
DRAMA = re.compile(r"drama|ドラマ|ボイス", re.I)

COLUMNS = ["work_id", "line", "age", "kind", "series", "title", "title_en", "parent_id", "release",
           "tracks", "runtime_min", "runtime_source", "owned", "location", "dlsite", "jiten",
           "source", "note"]


def work(**kw):
    return {c: kw.get(c, "") for c in COLUMNS}


def from_inventory():
    rows = list(csv.DictReader(open(HERE / "inventory" / "z_audio.csv", encoding="utf-8-sig")))
    for r in rows:
        if r["title"] == "Paradox Live":
            continue  # replaced by the per-release breakdown below
        hours = float(r["hours"]) if r["hours"] else None
        title = r["title"] or r["dlsite"] or Path(r["path"]).name  # code-only names lose their title
        yield work(
            work_id=f"z:{r['line']}/{r['age'] or '-'}/{r['kind']}/{title}", line=r["line"], age=r["age"], kind=r["kind"], title=title,
            tracks=int(r["audio_files"]) + int(r["video_files"]) or "",
            runtime_min=round(hours * 60) if hours else "",
            runtime_source="files" if hours else "",
            owned="on NAS" if r["status"].startswith("ready") else "on NAS, still packed" if r["status"] == "packed" else "no media",
            location=r["path"], dlsite=r["dlsite"], source="Z:\\AUDIO",
            note=f"{r['subtitles']} subtitle files" if int(r["subtitles"]) else "")


def from_paradox():
    for year in sorted(os.listdir(long_path(PARADOX))):
        ydir = os.path.join(long_path(PARADOX), year)
        if not os.path.isdir(ydir) or not year.isdigit():
            continue
        for release in sorted(os.listdir(ydir)):
            rdir = os.path.join(ydir, release)
            files = [os.path.join(dp, f) for dp, _d, fn in os.walk(rdir) for f in fn]
            drama = [f for f in files if os.path.splitext(f)[1].lower() in AUDIO_EXT | VIDEO_EXT
                     and DRAMA.search(os.path.basename(f))]
            if not drama:
                continue
            secs = sum(duration(f)[0] for f in drama)
            yield work(
                work_id=f"paradox:{year}/{release}", line="Original series", age="AA", kind="Drama CD",
                series="Paradox Live", title=re.sub(r"^[\d.]+\s+", "", release), release=year,
                tracks=len(drama), runtime_min=round(secs / 60) if secs else "",
                runtime_source="files" if secs else "", owned="on NAS", location=short_path(rdir),
                source="Paradox Live archive", note="voice drama only (songs are music)")


def from_hypmic():
    rows = list(csv.DictReader(open(AUDIO_PROJECTS / "HYPMIC SPOTIFY BACKUP" / "tracks.csv", encoding="utf-8-sig")))
    albums = {}
    for r in rows:
        if r["status"].startswith("captured") and DRAMA.search(r["title"]):
            albums.setdefault(r["album"], []).append(r)
    for album, tracks in albums.items():
        secs = sum(int(t["duration_s"] or 0) for t in tracks)
        yield work(
            work_id=f"hypmic:{album}", line="Original series", age="AA", kind="Drama CD",
            series="ヒプノシスマイク", title=f"{album} (drama tracks)", release=tracks[0]["release_date"],
            tracks=len(tracks), runtime_min=round(secs / 60), runtime_source="Spotify",
            owned="on I: (HypMic rips)", location=str(Path(tracks[0]["matched_file"]).parent),
            source="HypMic Spotify backup", note="drama tracks of a music release")


def from_diabolik():
    z = zipfile.ZipFile(AUDIO_PROJECTS / "DIABOLIK LOVERS catalogue" / "DL_Covers_for_Sirus.zip")
    data = json.loads(z.read("DL_Covers_for_Sirus/dl_catalog.json").decode("utf-8"))
    for season in data["seasons"]:
        for group in season["product_groups"]:
            for item in group["items"]:
                if not item.get("have_audio"):
                    continue  # not owned
                parent = item.get("tokuten_of") or ""
                yield work(
                    work_id=f"dl:{item['id']}", line="Otome", age="",
                    kind="Tokuten" if item["type"] == "tokuten" else "Drama CD",
                    series="DIABOLIK LOVERS", title=item["title"],
                    parent_id=(f"dl:{parent}" if parent and ":" not in parent else parent),
                    release=item.get("official_release") or item.get("inferred_release") or "",
                    tracks=item.get("volumes") or "", owned="on I: (Diabolik Lovers rips)",
                    location=f"I:\\Diabolik Lovers ({season.get('archive', '')})",
                    jiten=(item.get("jiten") or {}).get("url", ""), source="DL catalogue",
                    note="; ".join(filter(None, [
                        "age (AA/R18) not set yet",
                        (item.get("jp_reference") or {}).get("jp_sample") and
                        "JP e.g. " + item["jp_reference"]["jp_sample"]])))


def main():
    works = []
    for source in (from_inventory, from_paradox, from_hypmic, from_diabolik):
        print(f"{source.__name__} ...", flush=True)
        works += list(source())
    OUT.mkdir(exist_ok=True)
    with open(OUT / "works.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, COLUMNS)
        w.writeheader()
        w.writerows(works)
    try:
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "Works"
        ws.append(COLUMNS)
        for r in works:
            ws.append([r[c] for c in COLUMNS])
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        wb.save(OUT / "works.xlsx")
    except ImportError:
        pass
    print(f"{len(works)} works -> {OUT / 'works.csv'}")


if __name__ == "__main__":
    main()
