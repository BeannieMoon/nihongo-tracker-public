"""Generate demo/audio_tracker.html: a clickable demo of the audio diary built on the real catalogue.

    python tools/build_demo.py

Data: catalogue/works.csv, catalogue/listened_matches.csv, imports/dramacd_sheet.json.
The Inbox tab shows invented example listens to illustrate the scrobble flow.
"""
import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
OUT = HERE / "demo"


def main():
    works = list(csv.DictReader(open(HERE / "catalogue" / "works.csv", encoding="utf-8-sig")))
    matches = list(csv.DictReader(open(HERE / "catalogue" / "listened_matches.csv", encoding="utf-8-sig")))
    sheet = {r[0]: r for r in json.loads((HERE / "imports" / "dramacd_sheet.json").read_text(encoding="utf-8"))["rows"]}
    listened = []
    for m in matches:
        name, start, finish, time, series = sheet[m["sheet_title"]]
        listened.append({"title": name, "start": start, "finish": finish, "sheet_time": time, "series": series,
                         "work_ids": [i for i in m["work_id"].split(";") if i]})
    keep = ["work_id", "line", "age", "kind", "series", "title", "title_en", "parent_id", "release",
            "tracks", "runtime_min", "owned", "location", "dlsite", "jiten", "note"]
    data = {"works": [{k: w[k] for k in keep} for w in works], "listened": listened}
    html = (Path(__file__).parent / "demo_template.html").read_text(encoding="utf-8")
    OUT.mkdir(exist_ok=True)
    (OUT / "audio_tracker.html").write_text(
        html.replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False)), encoding="utf-8")
    print(f"{OUT / 'audio_tracker.html'}  ({len(works)} works, {len(listened)} listened)")


if __name__ == "__main__":
    main()
