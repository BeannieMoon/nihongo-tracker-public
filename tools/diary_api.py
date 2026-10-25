"""Talk to the deployed Audio Diary (Apps Script web app) from the PC.

Config: diary.json next to this project's README: {"url": "<web app /exec URL>", "token": "<API token>"}
(setup() in the Apps Script editor prints the token).

    python tools/diary_api.py check     counts per tab
    python tools/diary_api.py seed      read "Old tracker", build the listened seed, send it to the Dumper
    python tools/diary_api.py backup    save every tab to catalogue/diary_backup_<date>.json
"""
import datetime as dt
import json
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "tools"))


def call(action, **kw):
    cfg = json.loads((HERE / "diary.json").read_text(encoding="utf-8-sig"))
    body = json.dumps({"action": action, "token": cfg["token"], **kw}).encode()
    req = urllib.request.Request(cfg["url"], data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:  # Apps Script answers via a redirect; urllib follows it
        res = json.load(r)
    if not res.get("ok"):
        sys.exit(f"{action} failed: {res.get('error')}")
    return res["data"]


def upload_covers(seed):
    """Covers that are local files (catalogue/covers/...) go to Drive; rows get the Drive image URL."""
    import base64
    done = {}
    for d in seed["dumper"]:
        for row in [d["payload"]["series"], *d["payload"].get("volumes", [])]:
            path = row.get("cover", "")
            if path and (HERE / path).is_file():
                if path not in done:
                    name = path.replace("catalogue/covers/", "").replace("/", "_")
                    done[path] = call("uploadCover", name=name,
                                      base64=base64.b64encode((HERE / path).read_bytes()).decode())
                row["cover"] = done[path]
    if done:
        print(f"{len(done)} covers uploaded to Drive")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "check":
        for tab, rows in call("read").items():
            print(f"{tab:11} {len(rows)}")
    elif cmd == "seed":
        from diary_seed import build
        seed = build(call("readRaw", tab="Old tracker"))
        upload_covers(seed)
        call("upsert", tab="Franchises", rows=seed["franchises"])
        call("upsert", tab="Groups", rows=seed.get("groups", []))
        call("dump", items=seed["dumper"])
        print(f"{len(seed['franchises'])} franchises saved, {len(seed['dumper'])} series sent to the Dumper")
    elif cmd == "backup":
        out = HERE / "catalogue" / f"diary_backup_{dt.date.today()}.json"
        out.write_text(json.dumps(call("read"), ensure_ascii=False, indent=1), encoding="utf-8")
        print(out)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
