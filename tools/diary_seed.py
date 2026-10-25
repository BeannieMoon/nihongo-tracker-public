"""Turn the drama CDs you've already listened to into Audio Diary series + volumes.

Inputs:
  imports/dramacd_sheet.json (or the full "Old tracker" tab when read through the API)
  catalogue/listened_matches.csv + catalogue/works.csv (which owned work each entry is)
  the Diabolik Lovers catalogue (per-LI volumes with voice actors, tokuten -> game links)

Output: catalogue/diary_seed.json = {"franchises": [...], "dumper": [{type, payload: {series, volumes}}]}.
Ids are derived from the source (work id / sheet title), so re-seeding updates instead of duplicating.

    python tools/diary_seed.py
"""
import csv
import hashlib
import json
import re
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
CAT = HERE / "catalogue"
DL_ZIP = Path(r"D:\Claude\Projects\Audio & Drama CDs\DIABOLIK LOVERS catalogue\DL_Covers_for_Sirus.zip")

VNDB = "https://vndb.org/"
DL_GAMES = {"HDB": "v9846", "HDB-LVE": "v9846", "GE": "v9846", "MB": "v12150", "MB-LVE": "v12150",
            "VC": "v15448", "DF": "v14649", "LP": "v17345", "LE": "v18945", "CHL": "v24577"}
# Old tracker "Series" column -> franchise name, and that franchise's game on VNDB.
FRANCHISES = {
    "diabolik lovers": ("DIABOLIK LOVERS", "Otome", "v9846"),
    "cupid parasite": ("キューピット・パラサイト", "Otome", "v25912"),
    "hanakare": ("花笑む彼と", "Otome", "v47546"),
    "lover pretend": ("Lover Pretend", "Otome", "v22986"),
    "dot kareshi": ("ドットカレシ", "Otome", "v12158"),
    "crazy cirkus": ("CRAZY CIRCUS", "Otome", ""),
    "kare to 48 jikan toubou suru cd 「criminale!」": ("クリミナーレ！", "Otome", ""),
    "chu ldk": ("CHU♥LDK", "Otome", ""),
    "lovers loop": ("Lovers Loop", "Otome", ""),
    "midnight kyonshi": ("Midnight Jiang Shis", "Otome", ""),
    "paradox live": ("Paradox Live", "Joseimuke", ""),
}
DL_LIS = ["Ayato", "Kanato", "Laito", "Raito", "Shuu", "Shu", "Reiji", "Subaru", "Ruki", "Kou", "Yuma",
          "Azusa", "Carla", "Shin", "Karlheinz", "Kino"]


def sid(prefix, key):
    return f"{prefix}_{hashlib.sha1(key.encode()).hexdigest()[:8]}"


def num(text):
    m = re.match(r"\s*(\d+(?:\.\d+)?)", str(text or ""))
    return m.group(1) if m else ""


def minutes(text):
    m = re.match(r"\s*(\d+(?:\.\d+)?)\s*(h|m)?", str(text or ""), re.I)
    return round(float(m.group(1)) * (60 if (m.group(2) or "").lower() == "h" else 1)) if m else ""


def iso(text, year=None):
    """'18.1.2025', '25:10.2025', '02.04.2026' -> ISO; '.03.2026' -> '2026-03'."""
    p = str(text or "").replace(":", ".").split(".")
    if len(p) < 2 or not p[1].strip():
        return ""
    y = p[2].strip() if len(p) > 2 and p[2].strip() else str(year or "")
    if not y:
        return ""
    return f"{y}-{int(p[1]):02d}" + (f"-{int(p[0]):02d}" if p[0].strip() else "")


def li_from(text):
    hit = next((n for n in DL_LIS if re.search(rf"\b{n}\b", text, re.I)), "")
    return {"Raito": "Laito", "Shu": "Shuu"}.get(hit, hit)


DIARY_FIELDS = ("status", "rating", "level", "difficulty", "notes", "notes_after", "started", "finished")


def apply_curated(c, series, franchise, key):
    """A hand-checked entry (imports/curated/*.json) replaces the guessed catalogue facts: real CDs with
    LI/CV, release dates, covers, every track with its duration. Your diary fields from the old sheet stay."""
    fr = c.get("franchise", {})
    s = {**series, **{k: v for k, v in c["series"].items() if k != "notes_extra"},
         "franchise_id": franchise(fr.get("name", ""), c["series"]["title"]) if fr else series["franchise_id"]}
    s.update({k: series[k] for k in DIARY_FIELDS if series.get(k)})
    if c["series"].get("notes_extra"):  # what's in the archive: catalogue info, not your notes
        s["contents"] = c["series"]["notes_extra"]
    heard = bool(series.get("finished"))
    vols, tracks = [], []
    for cd in c["cds"]:
        vid = sid("v", f"{key}#cd{cd['no']}")
        vols.append({**{k: v for k, v in cd.items() if k != "tracks"}, "id": vid, "series_id": s["id"],
                     "listened": heard, "time_min": cd["runtime_min"] if heard else "", "time_source": "runtime"})
        tracks += [{**t, "id": sid("t", f"{vid}#{t['no']}"), "volume_id": vid} for t in cd["tracks"]]
    return {"series": s, "volumes": vols, "tracks": tracks}


def owned_label(catalogue_owned):
    """Catalogue ownership text -> the diary's "Have it" choices."""
    if not catalogue_owned:
        return "streaming only"
    if catalogue_owned.startswith("on I:"):
        return "other drive"
    return {"on NAS": "on NAS", "on NAS, still packed": "on NAS, still packed"}.get(catalogue_owned, "")


def load_dl():
    data = json.loads(zipfile.ZipFile(DL_ZIP).read("DL_Covers_for_Sirus/dl_catalog.json").decode("utf-8"))
    return {f"dl:{i['id']}": i for s in data["seasons"] for g in s["product_groups"] for i in g["items"]}


def old_rows(raw=None):
    """Old tracker rows as dicts. `raw` is the tab read through the API (all columns); otherwise the
    local 5-column snapshot."""
    if raw:
        head = [str(h).strip() for h in raw[0]]
        return [dict(zip(head, r)) for r in raw[1:] if r and r[0]]
    rows = json.loads((HERE / "imports" / "dramacd_sheet.json").read_text(encoding="utf-8"))["rows"]
    return [{"Name": n, "Start date": a, "Finished date": b, "Time": t, "Series": s} for n, a, b, t, s in rows]


def build(raw=None):
    works = {w["work_id"]: w for w in csv.DictReader(open(CAT / "works.csv", encoding="utf-8-sig"))}
    matches = {m["sheet_title"]: [i for i in m["work_id"].split(";") if i]
               for m in csv.DictReader(open(CAT / "listened_matches.csv", encoding="utf-8-sig"))}
    dl = load_dl()
    rows = old_rows(raw)

    franchises = {}
    curated_files = [json.loads(f.read_text(encoding="utf-8")) for f in sorted((HERE / "imports" / "curated").glob("*.json"))]
    curated = {c["match_work_id"]: c for c in curated_files if "match_work_id" in c}
    hubs = [c for c in curated_files if "groups" in c]  # whole franchises (DIABOLIK LOVERS…)
    hub_items = {cd["dl_item"] for h in hubs for g in h["groups"] for se in g["series"] for cd in se["cds"] if cd.get("dl_item")}
    hub_names = {h["franchise"]["name"].lower() for h in hubs}
    hub_rows = {}  # dl item id -> old-sheet rows that listened to it

    def franchise(name_key, title):
        key = str(name_key or "").strip().lower()
        if not key:
            key = "paradox live" if "paradox" in title.lower() else ""
        if not key:
            return ""  # standalone CD: shows under "Other" until you give it a franchise
        name, audience, game = FRANCHISES.get(key, (str(name_key or title).strip(), "Otome", ""))
        fid = sid("f", name)
        franchises.setdefault(fid, {"id": fid, "name": name, "audience": audience, "games": VNDB + game if game else ""})
        return fid
    franchise.registry = franchises

    # Group: which sheet rows point at which work.
    by_work = {}
    for r in rows:
        ids = matches.get(r["Name"], [])
        if len(ids) == 1:
            by_work.setdefault(ids[0], []).append(r)

    seen_rows = set()
    out = []
    year = 2025
    for r in rows:
        if r["Name"] in seen_rows:
            continue
        ids = matches.get(r["Name"], [])
        if not ids and r["Name"].strip().lower() in hub_names:
            continue  # a whole-franchise line ("Paradox Live"); the hub carries its own listening log
        if ids and all(i.startswith("dl:") and i[3:] in hub_items for i in ids):
            for i in ids:  # this listen belongs to a franchise hub; its CDs pick it up below
                hub_rows.setdefault(i[3:], []).append(r)
            continue
        group = by_work.get(ids[0], [r]) if len(ids) == 1 else [r]
        seen_rows.update(g["Name"] for g in group)
        work = works.get(ids[0]) if len(ids) == 1 else None
        item = dl.get(ids[0]) if len(ids) == 1 else None
        key = ids[0] if len(ids) == 1 else "sheet:" + r["Name"]
        title = (work["title"] if work else r["Name"]).strip()

        started = iso(group[0].get("Start date"), year)
        finished = iso(group[-1].get("Finished date"), year)
        year = int((finished or started or str(year))[:4])
        kind = ("Tokuten" if (item and item["type"] == "tokuten") or (work and work["kind"] == "Tokuten")
                else "Drama CD")  # situation CDs count as drama CDs
        notes_field = lambda rr, k: str(rr.get(k) or "").strip()
        series = {
            "id": sid("s", key), "franchise_id": franchise(r.get("Series"), title), "title": title,
            "title_en": "" if not work or work["title"] == r["Name"] else r["Name"],
            "kind": kind, "audience": "Joseimuke" if "Paradox" in title else "Otome",
            "age": (work or {}).get("age") or ("R18" if "R18" in notes_field(r, "Notes") else ""),
            "status": "listening" if not finished else "completed",
            "rating": num(r.get("Ranking")), "level": notes_field(r, "Level"), "difficulty": num(r.get("Difficulty")),
            "release": (item or {}).get("official_release") or (item or {}).get("inferred_release") or "",
            "notes": notes_field(r, "Notes"), "notes_after": notes_field(r, "Notes after finishing "),
            "website": notes_field(r, "DB link") or (notes_field(r, "Source") if notes_field(r, "Source").startswith("http") else ""),
            "links": notes_field(r, "Source") if notes_field(r, "Source").startswith("http") else "",
            "started": started, "finished": finished,
            "owned": owned_label((work or {}).get("owned", "")), "location": (work or {}).get("location", ""),
        }
        if item and str(item.get("tokuten_of", "")).startswith("game:"):
            game = DL_GAMES.get(item["tokuten_of"][5:])
            series["game"] = VNDB + game if game else ""
            series["store"] = re.split(r"[:：]", item["title"])[0].replace("Tokuten", "").strip()
        elif item and item.get("tokuten_of"):
            series["parent_id"] = sid("s", "dl:" + item["tokuten_of"])

        sheet_min = minutes(r.get("Time"))
        if len(ids) > 1:
            # One listen covering several owned works (e.g. 365 Days: one CD per LI) -> one volume each.
            vols = [{"title": works[i]["title"], "li": li_from(works[i]["title"]), "runtime_min": works[i]["runtime_min"]}
                    for i in ids if i in works]
            for v, i in zip(vols, ids):
                ref = (dl.get(i) or {}).get("translation_refs") or [{}]
                v["cv"] = ref[0].get("cv", "")
        elif len(group) > 1:
            # Several listens of one work (Hanakare vol.1-4, SKiT per LI) -> one volume per listen.
            vols = [{"title": g["Name"], "li": li_from(g["Name"]), "cv": notes_field(g, "Voice Actors"),
                     "started": iso(g.get("Start date"), year), "finished": iso(g.get("Finished date"), year),
                     "time_min": minutes(g.get("Time")), "rating": num(g.get("Ranking")),
                     "notes": notes_field(g, "Notes after finishing ")} for g in group]
        elif item and len(item.get("translation_refs") or []) > 1:
            # A DL release with a track per LI -> the LI volumes, voice actor from the translation post.
            refs = {}
            for t in item["translation_refs"]:
                refs.setdefault(t.get("jp") or t.get("track"), t)
            vols = [{"title": t.get("jp") or t.get("track"), "li": li_from(t.get("track", "")), "cv": t.get("cv", ""),
                     "file_path": t.get("audio", "")} for t in refs.values()]
        else:
            vols = [{"title": title, "cv": notes_field(r, "Voice Actors"),
                     "runtime_min": (work or {}).get("runtime_min", "")}]

        for n, v in enumerate(vols, 1):
            v.setdefault("started", started)
            v.setdefault("finished", finished)
            v.update(id=sid("v", f"{key}#{n}"), series_id=series["id"], no=n, listened=bool(finished))
            if not v.get("time_min"):
                real = v.get("runtime_min")
                v["time_min"] = real or (round(sheet_min / len(vols)) if sheet_min else "")
                v["time_source"] = "runtime" if real else "old tracker estimate"
            else:
                v["time_source"] = "old tracker estimate"
        payload = {"series": series, "volumes": vols}
        if key in curated:
            payload = apply_curated(curated[key], series, franchise, key)
        out.append({"type": "new series", "source": "listened list (old tracker)", "payload": payload})
    groups = []
    for hub in hubs:
        g_rows, items = build_hub(hub, hub_rows, franchise)
        groups += g_rows
        out += items
    return {"franchises": list(franchises.values()), "groups": groups, "dumper": out}


def build_hub(hub, hub_rows, franchise):
    """A whole franchise from its curated file: groups -> series -> CDs, with your old-sheet listens
    attached to the CDs they were about (dates, rating, notes)."""
    fr = hub["franchise"]
    fid = franchise(fr["name"].lower(), fr["name"])
    franchise.registry[fid].update(cast_label=fr.get("cast_label", "LI"), games=fr.get("games", ""))
    groups, items = [], []
    year = 2025
    for g in hub["groups"]:
        gid = sid("g", f"{fr['name']}#{g['name']}")
        groups.append({"id": gid, "franchise_id": fid, "name": g["name"], "order": g["order"], "game": g["game"]})
        for se in g["series"]:
            s_id = sid("s", se["key"])
            series = {k: v for k, v in se.items() if k not in ("cds", "key")}
            series.update(id=s_id, franchise_id=fid, group_id=gid, age=se.get("age") or fr.get("age", ""))
            vols, dates, notes = [], [], []
            for cd in se["cds"]:
                v = {k: val for k, val in cd.items() if k not in ("dl_item", "item", "tokuten")}
                # A hub may carry its own log (Paradox Live's tracker); DL's listens come from the old sheet below.
                v.update(id=sid("v", f"{se['key']}#{cd.get('dl_item') or cd['item']}#{cd['no']}"), series_id=s_id,
                         listened=bool(cd.get("listened")))
                dates += [d for d in (cd.get("started"), cd.get("finished")) if d]
                for r in hub_rows.get(cd.get("dl_item"), []):
                    started, finished = iso(r.get("Start date"), year), iso(r.get("Finished date"), year)
                    year = int((finished or started or str(year))[:4])
                    v.update(listened=bool(finished), started=started, finished=finished, time_source="old tracker")
                    dates += [d for d in (started, finished) if d]
                    if cd.get("tokuten") or len(se["cds"]) == 1:  # a single CD carries its own rating and notes
                        v.update(rating=num(r.get("Ranking")), notes=str(r.get("Notes after finishing ") or "").strip())
                    else:
                        notes.append((r["Name"], num(r.get("Ranking")), str(r.get("Notes after finishing ") or "").strip()))
                vols.append(v)
            heard = sum(v["listened"] for v in vols)
            series["status"] = "completed" if vols and heard == len(vols) else "listening" if heard else "planned"
            if dates:
                series.update(started=min(dates), finished=max(dates) if heard == len(vols) else "")
            if notes:
                series["notes_after"] = "\n\n".join(f"{n}: {t}" if len(notes) > 1 else t for n, _, t in notes if t)
                ratings = [float(x) for _, x, _ in notes if x]
                if ratings:
                    series["rating"] = str(round(sum(ratings) / len(ratings)))
            items.append({"type": "new series", "source": f"{fr['name']} catalogue", "payload": {"series": series, "volumes": vols}})
    return groups, items


def main():
    seed = build()
    (CAT / "diary_seed.json").write_text(json.dumps(seed, ensure_ascii=False, indent=1), encoding="utf-8")
    vols = sum(len(d["payload"]["volumes"]) for d in seed["dumper"])
    print(f"{len(seed['franchises'])} franchises, {len(seed['dumper'])} series, {vols} volumes -> catalogue/diary_seed.json")


if __name__ == "__main__":
    main()
