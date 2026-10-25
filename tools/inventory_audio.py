"""Read-only inventory of the drama CD / audiobook collection on the NAS (Z:\\AUDIO).

One row per work, with the category taken from the folder layout
(OTOME|BL / AA|R18 / Original|Tokuten), real runtimes from the files (audio and mp4),
DLsite / Amazon ids, subtitle count (read-along readiness) and what is still packed.

    python tools/inventory_audio.py            -> inventory/z_audio.csv + .xlsx

Never writes to the NAS. Builds on the audio-collection-catalogue skill script for
tag/duration probing and store-id parsing.
"""
import csv
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".claude/skills/audio-collection-catalogue/scripts"))
from catalogue_audio import ARCHIVE_EXT, AUDIO_EXT, clean_title, ids_from, probe  # noqa: E402

ROOT = Path(r"Z:\AUDIO")
HERE = Path(__file__).resolve().parent.parent
OUT = HERE / "inventory"
FFPROBE = r"D:\Tools\FFmpeg\ffmpeg-9.0.2-full_build\bin\ffprobe.exe"

EXTENDED = "\\\\?\\"
VIDEO_EXT = {".mp4", ".m4v", ".mkv", ".webm", ".mov"}
SUB_EXT = {".srt", ".ass", ".vtt", ".lrc"}
SCRIPT_EXT = {".txt", ".pdf", ".docx", ".html"}
# Folders that hold several unrelated works rather than being one work.
GRAB_BAGS = {"POSTED DRAMA CDS"}

# (folder under Z:\AUDIO, line, age, kind)
SECTIONS = [
    (r"DRAMA CDs\OTOME\AA\Original", "Otome", "AA", "Drama CD"),
    (r"DRAMA CDs\OTOME\AA\Tokuten", "Otome", "AA", "Tokuten"),
    (r"DRAMA CDs\OTOME\R18\Original", "Otome", "R18", "Drama CD"),
    (r"DRAMA CDs\OTOME\R18\Tokuten", "Otome", "R18", "Tokuten"),
    (r"DRAMA CDs\BL\AA\Original", "BL", "AA", "Drama CD"),
    (r"DRAMA CDs\BL\AA\Tokuten", "BL", "AA", "Tokuten"),
    (r"DRAMA CDs\BL\R18\Original", "BL", "R18", "Drama CD"),
    (r"DRAMA CDs\BL\R18\Tokuten", "BL", "R18", "Tokuten"),
    (r"DRAMA CDs\Originals Drama CD", "Original series", "", "Drama CD"),
    (r"DRAMA CDs\AUDIOBOOKS", "Japanese", "", "Audiobook"),
    (r"AUDIOBOOKS\ENGLISH", "English", "", "Audiobook"),
]


def stem_key(name):
    """'X scripts', 'X.rar', 'X' -> same key, so a work's script folder joins its archive."""
    s = os.path.splitext(name)[0] if os.path.splitext(name)[1].lower() in ARCHIVE_EXT | AUDIO_EXT | VIDEO_EXT else name
    s = re.sub(r"\s+scripts?$", "", s, flags=re.I)
    s = unicodedata.normalize("NFKC", s).casefold()
    return "".join(ch for ch in s if ch.isalnum())


def duration(path):
    """Seconds of audio in a file; mutagen first, ffprobe for what it can't read."""
    secs, _br, tags, _cover, err = probe(path)
    if secs:
        return secs, tags
    try:
        out = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                              "-of", "default=nw=1:nk=1", path], capture_output=True, text=True, timeout=60)
        return float(out.stdout.strip() or 0), tags
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return 0, tags


def long_path(p):
    """Windows extended-length path, so files nested past 260 characters can be read."""
    p = os.path.abspath(p)
    return p if p.startswith(EXTENDED) else EXTENDED + p


def short_path(p):
    return p[len(EXTENDED):] if p.startswith(EXTENDED) else p


def works_in(folder):
    """Yield (name, [files]) per work: subfolders are works, loose files group by stem,
    grab-bag folders are opened up one level."""
    groups = {}
    for entry in sorted(os.listdir(folder)):
        p = os.path.join(folder, entry)
        if os.path.isdir(p) and entry in GRAB_BAGS:
            yield from works_in(p)
            continue
        files = ([os.path.join(dp, f) for dp, _d, fn in os.walk(p) for f in fn]
                 if os.path.isdir(p) else [p])
        g = groups.setdefault(stem_key(entry), {"names": [], "files": []})
        g["names"].append(entry)
        g["files"] += files
    for g in groups.values():
        # Prefer the plain folder/file name over "... scripts" for the title.
        name = sorted(g["names"], key=lambda n: (bool(re.search(r"scripts?$", n, re.I)), len(n)))[0]
        if g["files"]:
            yield name, g["files"]


def row(section, name, files):
    rel, line, age, kind = section
    ext = lambda f: os.path.splitext(f)[1].lower()
    audio = [f for f in files if ext(f) in AUDIO_EXT]
    video = [f for f in files if ext(f) in VIDEO_EXT]
    arch = [f for f in files if ext(f) in ARCHIVE_EXT]
    subs = [f for f in files if ext(f) in SUB_EXT]
    scripts = [f for f in files if ext(f) in SCRIPT_EXT]
    secs, tags = 0.0, {}
    for f in audio + video:
        d, t = duration(f)
        secs += d
        for k, v in t.items():
            if v and not tags.get(k):
                tags[k] = v
    asin, dlsite = ids_from(name)
    for f in files:
        a2, d2 = ids_from(os.path.basename(f))
        asin, dlsite = asin or a2, dlsite or d2
    media = audio + video
    status = ("ready" if media and not arch else "ready + archives" if media
              else "packed" if arch else "no media")
    return {
        "line": line, "age": age, "kind": kind,
        "title": clean_title(name), "album_tag": tags.get("album", ""), "artist_tag": tags.get("narrator", ""),
        "dlsite": dlsite, "asin": asin,
        "status": status, "hours": round(secs / 3600, 2) if secs else "",
        "audio_files": len(audio), "video_files": len(video),
        "subtitles": len(subs), "scripts": len(scripts),
        "archives": len(arch), "archive_MB": round(sum(os.path.getsize(f) for f in arch) / 2**20) if arch else "",
        "size_MB": round(sum(os.path.getsize(f) for f in files) / 2**20),
        "path": short_path(files[0] if len(files) == 1 else os.path.commonpath(files)),
    }


def main():
    rows = []
    for section in SECTIONS:
        folder = ROOT / section[0]
        if not folder.is_dir():
            continue
        print(f"scanning {folder} ...", flush=True)
        for name, files in works_in(long_path(folder)):
            rows.append(row(section, name, files))
    OUT.mkdir(exist_ok=True)
    cols = list(rows[0])
    with open(OUT / "z_audio.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, cols)
        w.writeheader()
        w.writerows(rows)
    try:
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "Z AUDIO"
        ws.append(cols)
        for r in rows:
            ws.append([r[c] for c in cols])
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        wb.save(OUT / "z_audio.xlsx")
    except ImportError:
        pass
    print(f"{len(rows)} works -> {OUT / 'z_audio.csv'}")


if __name__ == "__main__":
    main()
