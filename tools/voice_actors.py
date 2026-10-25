"""One spelling per voice actor (catalogue/voice_actors.json), so the Voices tab doesn't split people.

    normalise_cv("Toriumi Kousuke & Takashi Kondou") -> ("鳥海浩輔 (Kōsuke Toriumi), 近藤隆 (Takashi Kondō)", [])

Names match in either order and with any long-vowel spelling (Kousuke / Kosuke / Kōsuke); unknown
names are kept as written and returned so the caller can report them.
"""
import json
import re
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
SPLIT = re.compile(r"\s*(?:,|&|;|/|、|・|\band\b)\s*")


def _key(name):
    name = re.sub(r"\(([^)]*)\)", r" \1 ", name)  # "鳥海浩輔 (Kōsuke Toriumi)" -> both parts
    latin = re.sub(r"[^a-z ]", "", unicodedata.normalize("NFKD", name).lower())  # ō -> o
    latin = re.sub(r"ou|oo", "o", re.sub(r"uu", "u", latin))
    return " ".join(sorted(latin.split()))


def _table():
    if not hasattr(_table, "t"):
        actors = json.loads((HERE / "catalogue" / "voice_actors.json").read_text(encoding="utf-8"))["actors"]
        _table.t = {}
        for a in actors:
            for alias in [a["name"], *a.get("aliases", [])]:
                _table.t[_key(alias)] = a["name"]
            _table.t[a["name"].split(" (")[0]] = a["name"]  # kanji alone
    return _table.t


def normalise_cv(text):
    """'A & B, C' in any spelling -> 'canonical A, canonical B, canonical C' (joined with ', ' as the Voices tab splits)."""
    out, unknown = [], []
    for part in filter(None, SPLIT.split(text or "")):
        name = _table().get(part) or _table().get(_key(part))
        if not name:
            unknown.append(part)
        name = name or part
        if name not in out:
            out.append(name)
    return ", ".join(out), unknown
