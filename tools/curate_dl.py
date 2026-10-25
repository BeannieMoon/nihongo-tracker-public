"""Build the curated DIABOLIK LOVERS entry from the catalogue made for jiten (dl_catalog.json).

    seasons         -> groups (one per game era, plus anime/misc and House of Emblem)
    product groups  -> series (a main CD line with its own bonuses, or a game's bonus pack)
    owned items     -> CDs (multi-volume items become one CD per LI, voice actor from the
                       translation posts); items marked have_audio=false are left out

Covers come from DL_Covers_for_Sirus.zip, shrunk into catalogue/covers/dl/.

    python tools/curate_dl.py   -> imports/curated/diabolik_lovers.json
"""
import io
import json
import re
import zipfile
from pathlib import Path

from PIL import Image

from voice_actors import normalise_cv

HERE = Path(__file__).resolve().parent.parent
ZIP = Path(r"D:\Claude\Projects\Audio & Drama CDs\DIABOLIK LOVERS catalogue\DL_Covers_for_Sirus.zip")
COVERS = HERE / "catalogue" / "covers" / "dl"
VNDB = "https://vndb.org/"

# season -> (group name, VNDB id of its game)
SEASONS = {1: ("Haunted Dark Bridal", "v9846"), 2: ("More, Blood", "v12150"), 2.5: ("Anime & misc", ""),
           3: ("Vandead Carnival", "v15448"), 4: ("Dark Fate", "v14649"), 5: ("Lunatic Parade", "v17345"),
           6: ("Lost Eden", "v18945"), 7: ("Chaos Lineage", "v24577"), 8: ("Song of Emblem", "")}
# LI names as they appear in English track titles or in katakana.
LIS = [("Ayato", "アヤト"), ("Kanato", "カナト"), ("Laito", "ライト"), ("Shuu", "シュウ"), ("Reiji", "レイジ"),
       ("Subaru", "スバル"), ("Ruki", "ルキ"), ("Kou", "コウ"), ("Yuma", "ユーマ"), ("Azusa", "アズサ"),
       ("Carla", "カルラ"), ("Shin", "シン"), ("Karlheinz", "カールハインツ"), ("Kino", "キノ")]
STORE_WORDS = ["Animate", "Stellaworth", "Alice NET", "Alice-NET", "Imajin Webshop", "Tower Records", "SKiT Dolce",
               "Rejet shop", "7net Shopping", "Gamers", "Amazon", "Sofmap", "Animega"]
EDITION_WORDS = {"Gentei": "limited edition", "Yoyaku": "pre-order", "Kuji": "kuji prize",
                 "Limited V Edition": "Limited V Edition", "Grand Edition": "Grand Edition"}


UNKNOWN_CV = set()


def cv_of(*texts):
    """Translation posts spell voice actors every which way; one spelling each (catalogue/voice_actors.json)."""
    cv, unknown = normalise_cv(", ".join(t for t in texts if t))
    UNKNOWN_CV.update(unknown)
    return cv


def lis_in(*texts):
    text = " ".join(t or "" for t in texts)
    return [en for en, jp in LIS if re.search(rf"\b{en}\b", text, re.I) or jp in text
            or (en == "Laito" and re.search(r"\bRaito\b", text, re.I))]


def store_of(title):
    """'LP Stellaworth Tokuten: "…"' -> 'Stellaworth'; 'Gentei Tokuten: …' -> 'limited edition'."""
    head = re.split(r"[:：]", title)[0]
    stores = [w for w in STORE_WORDS if w.lower() in head.lower()]
    editions = [v for k, v in EDITION_WORDS.items() if k.lower() in head.lower()]
    return " / ".join(dict.fromkeys(stores + editions))


def save_cover(z, names, cover_dir, filename, out_name):
    path = f"DL_Covers_for_Sirus/{cover_dir}/{filename}"
    if not filename or path not in names:
        return ""
    try:
        im = Image.open(io.BytesIO(z.read(path))).convert("RGB")
    except OSError:  # a few files in the zip aren't real images (e.g. .webp named .png that PIL can't read)
        return ""
    im.thumbnail((400, 400))
    out = COVERS / f"{out_name}.jpg"
    im.save(out, "JPEG", quality=85)
    return out.relative_to(HERE).as_posix()


def cds_of(item, cover):
    """One CD per volume (deduplicated translation refs), or the item itself as one CD."""
    refs = list({(r.get("jp") or r.get("track")): r for r in item.get("translation_refs") or []}.values())
    release = item.get("official_release") or item.get("inferred_release") or ""
    jiten = (item.get("jiten") or {}).get("url", "")
    is_tokuten = item["type"] == "tokuten"
    volumes = int((re.search(r"\d+", str(item.get("volumes") or 1)) or [1])[0])  # sometimes "4 (+bonus)"
    if volumes > 1 and len(refs) > volumes:
        refs = refs[:volumes]  # the catalogue sometimes lists a related CD's posts after the real volumes
    if volumes > 1 and len(refs) > 1:
        out = []
        for n, r in enumerate(refs, 1):
            lis = lis_in(r.get("track"), r.get("jp"))
            out.append({"no": n, "title": r.get("jp") or r.get("track"), "title_en": r.get("track", ""),
                        "li": ", ".join(lis), "cv": cv_of(r.get("cv")), "release": release.split(" to ")[0] if n == 1 else "",
                        "cover": cover, "links": "\n".join(filter(None, [r.get("post") and f"Translation: {r['post']}",
                                                                         jiten and f"jiten: {jiten}"])),
                        "dl_item": item["id"]})
        if " to " in release:
            out[-1]["release"] = release.split(" to ")[-1]
        return out
    r = refs[0] if refs else {}
    return [{"no": 1, "title": r.get("jp") or item["title"], "title_en": item["title"],
             "li": ", ".join(lis_in(item["title"], r.get("track"), r.get("jp"))), "cv": cv_of(*(x.get("cv") for x in refs)),
             "release": release, "store": store_of(item["title"]) if is_tokuten else "", "cover": cover,
             "links": "\n".join(filter(None, [r.get("post") and f"Translation: {r['post']}", jiten and f"jiten: {jiten}"])),
             "tokuten": is_tokuten, "dl_item": item["id"]}]


def main():
    z = zipfile.ZipFile(ZIP)
    names = set(z.namelist())
    data = json.loads(z.read("DL_Covers_for_Sirus/dl_catalog.json").decode("utf-8"))
    COVERS.mkdir(parents=True, exist_ok=True)
    groups, skipped = [], []
    for order, season in enumerate(data["seasons"], 1):
        name, game = SEASONS[season["season"]]
        group = {"name": name, "order": order, "game": VNDB + game if game else "", "series": []}
        for pg in season["product_groups"]:
            owned = [i for i in pg["items"] if i.get("have_audio")]
            skipped += [i["title"] for i in pg["items"] if not i.get("have_audio")]
            if not owned:
                continue
            main_item = next((i for i in owned if i["type"] != "tokuten"), None)
            cds = []
            for item in owned:
                f = item.get("cover_file") or (item.get("cover_files") or [None])[0]
                cover = save_cover(z, names, pg.get("cover_dir", ""), f, item["id"])
                for cd in cds_of(item, cover):
                    cds.append(cd)
            for n, cd in enumerate(cds, 1):
                cd["no"] = n
            series_cover = next((c["cover"] for c in cds if c["cover"] and (main_item is None or c["dl_item"] == main_item["id"])), "") \
                or next((c["cover"] for c in cds if c["cover"]), "")
            group["series"].append({
                "key": f"dl-group:{season['season']}:{pg['group']}", "title": pg["group"],
                "kind": "Drama CD" if main_item else "Tokuten", "audience": "Otome", "label": "Rejet",
                "release": (main_item or owned[0]).get("official_release") or (main_item or owned[0]).get("inferred_release") or "",
                "website": ((main_item or {}).get("jiten") or {}).get("url", ""), "cover": series_cover,
                "game": group["game"] if not main_item else "", "owned": "other drive",
                "location": f"I:\\Diabolik Lovers ({season.get('archive', '')})", "cds": cds,
            })
        groups.append(group)
    entry = {"_source": "dl_catalog.json (the jiten submission catalogue): seasons, product groups, owned items, "
                        "translation-post voice actors, jiten links; covers from DL_Covers_for_Sirus.zip.",
             "franchise": {"name": "DIABOLIK LOVERS", "audience": "Otome", "age": "AA", "cast_label": "LI",
                           "games": " ".join(VNDB + g for _, g in SEASONS.values() if g)},
             "groups": groups, "not_owned": skipped}
    out = HERE / "imports" / "curated" / "diabolik_lovers.json"
    out.write_text(json.dumps(entry, ensure_ascii=False, indent=1), encoding="utf-8")
    n_series = sum(len(g["series"]) for g in groups)
    n_cds = sum(len(s["cds"]) for g in groups for s in g["series"])
    print(f"{len(groups)} groups, {n_series} series, {n_cds} CDs ({len(skipped)} not owned, left out) -> {out}")
    if UNKNOWN_CV:
        print("voice actors not in catalogue/voice_actors.json (kept as written):", ", ".join(sorted(UNKNOWN_CV)))


if __name__ == "__main__":
    main()
