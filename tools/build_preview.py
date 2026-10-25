"""Local preview of the Audio Diary page: apps_script/Index.html with the seed waiting in the Dumper.

    python tools/build_preview.py            -> apps_script/preview.html (changes stay in that browser)
    python tools/build_preview.py --accepted -> apps_script/demo.html, the seed already accepted (the phone demo)
"""
import hashlib
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent


def main():
    accepted = "--accepted" in sys.argv
    seed = json.loads((HERE / "catalogue" / "diary_seed.json").read_text(encoding="utf-8"))
    # Local covers are copied next to the page and linked by path (the real seed uploads them to Drive).
    # Inlining them as data: URIs made the preview ~10 MB, past browser storage limits.
    for d in seed["dumper"]:
        for row in [d["payload"]["series"], *d["payload"].get("volumes", [])]:
            src = HERE / row["cover"] if row.get("cover") else None
            if src and src.is_file():
                rel = src.relative_to(HERE / "catalogue" / "covers").as_posix()
                dst = HERE / "apps_script" / "preview_covers" / rel
                if not dst.is_file() or dst.stat().st_size != src.stat().st_size:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src, dst)
                row["cover"] = "preview_covers/" + rel
    data = {"franchises": seed["franchises"], "groups": seed.get("groups", []), "series": [], "volumes": [], "tracks": [],
            "settings": {}, "dumper": []}
    for n, d in enumerate(seed["dumper"]):
        p = d["payload"]
        if accepted:  # what "Accept" does in the page: the series, its CDs and tracks become library rows
            data["series"].append(p["series"])
            data["volumes"] += [dict(v, series_id=p["series"]["id"]) for v in p.get("volumes", [])]
            data["tracks"] += p.get("tracks", [])
        else:
            data["dumper"].append({"id": f"d_{n}", "type": d["type"], "source": d["source"], "found_at": "2026-10-25",
                                   "status": "pending", "payload_json": json.dumps(p, ensure_ascii=False)})
    blob = json.dumps(data, ensure_ascii=False)
    inject = (f"<script>window.PREVIEW_VERSION = '{hashlib.sha1(blob.encode()).hexdigest()[:8]}';"
              f"window.PREVIEW_DATA = {blob};</script>")
    html = (HERE / "apps_script" / "Index.html").read_text(encoding="utf-8").replace("<script>\n// ---------- backend", inject + "\n<script>\n// ---------- backend", 1)
    out = HERE / "apps_script" / ("demo.html" if accepted else "preview.html")
    out.write_text(html, encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
