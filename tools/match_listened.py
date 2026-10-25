"""Match the drama CDs you've listened to (imports/dramacd_sheet.json) to catalogue works.

Writes catalogue/listened_matches.csv: one row per sheet entry with the best catalogue match,
a score, and a verdict (match / check / none). catalogue/listened_overrides.json pins a sheet
entry to a work id (or to "none") and always wins over the automatic match.

    python tools/match_listened.py
"""
import csv
import json
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
CAT = HERE / "catalogue"


def norm(s):
    s = unicodedata.normalize("NFKC", s or "").casefold()
    s = re.sub(r"\.(rar|zip|7z)$", "", s)
    s = re.sub(r"drama ?cd|tokuten|特典|ドラマcd|cd", " ", s)
    return "".join(ch for ch in s if ch.isalnum())


def score(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 0.9 + 0.1 * min(len(a), len(b)) / max(len(a), len(b))
    return SequenceMatcher(None, a, b).ratio()


def main():
    rows = json.loads((HERE / "imports" / "dramacd_sheet.json").read_text(encoding="utf-8"))["rows"]
    works = list(csv.DictReader(open(CAT / "works.csv", encoding="utf-8-sig")))
    overrides_path = CAT / "listened_overrides.json"
    overrides = json.loads(overrides_path.read_text(encoding="utf-8")) if overrides_path.exists() else {}
    by_id = {w["work_id"]: w for w in works}
    out = []
    for name, start, finish, time, series in rows:
        if name in overrides:
            ids = overrides[name] if isinstance(overrides[name], list) else [overrides[name]]
            picked = [by_id[i] for i in ids if i in by_id]
            missing = [i for i in ids if i != "none" and i not in by_id]
            if missing:
                raise SystemExit(f"override for {name!r} names unknown work ids: {missing}")
            best, s, verdict = (picked or [None])[0], 1.0, "pinned"
        else:
            cands = [(max(score(name, w["title"]), score(name, w["title_en"])), w) for w in works]
            s, best = max(cands, key=lambda c: c[0])
            picked = [best]
            verdict = "match" if s >= 0.85 else "check" if s >= 0.6 else "none"
            if verdict == "none":
                best = None
        out.append({
            "sheet_title": name, "finished": finish, "sheet_time": time, "verdict": verdict,
            "score": round(s, 2),
            "work_id": ";".join(w["work_id"] for w in (picked if verdict == "pinned" else [best] if best else [])),
            "work_title": (best["title_en"] or best["title"]) if best else "",
            "work_runtime_min": best["runtime_min"] if best else "", "owned": best["owned"] if best else "",
        })
    with open(CAT / "listened_matches.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, list(out[0]))
        w.writeheader()
        w.writerows(out)
    counts = {}
    for o in out:
        counts[o["verdict"]] = counts.get(o["verdict"], 0) + 1
    print(f"{len(out)} sheet entries -> {counts}")


if __name__ == "__main__":
    main()
