#!/usr/bin/env python3
"""Where and when monsters appear, from the Witcher wiki's Monster Slayer bestiary (maintainer's choice, 2026-10-22).

The wiki's tables give, per monster, its rarity, its pre-1.2 skulls and its occurrences. The occurrences are the game's own
phrases (MONSTERS/OCCURANCE/<TAG> in the client's I2Languages), so each sentence maps back to a tag exactly. The English page
describes later game versions; the Polish page has a row for every monster, so it fills what the English one leaves out.

  fetch:  downloads both pages through the MediaWiki API (the pages themselves sit behind Cloudflare), maps every row to a
          species of the world bestiary and every sentence to a tag (with the client's English and Polish phrases), and saves
          the snapshot, so later builds run offline:
            python wiki_bestiary.py fetch --apk ../../local/client/witcher116.apk \
                --world ../WitcherRevival.Server/Story/world-bestiary.json --output wiki-bestiary.json
  apply:  writes the wiki's tags, rarity and skulls into the world bestiary (the client's tags stay as client_tags):
            python wiki_bestiary.py apply --snapshot wiki-bestiary.json --world ../WitcherRevival.Server/Story/world-bestiary.json

Per category (habitat, time, weather, moon) the English page wins where it says something; where it says "No precise data"
or nothing for that category, the Polish page fills in; the client's own tags are the last resort. Dawn and dusk together
become D_AND_D (the client's "Increased activity around dawn and dusk").
"""
from __future__ import annotations

import argparse
import datetime
import difflib
import json
import re
import struct
import sys
import unicodedata
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

PAGES = {
    "en": ("https://witcher.fandom.com/api.php", "The_Witcher_Monster_Slayer_bestiary"),
    "pl": ("https://witcher.fandom.com/pl/api.php", "Bestiariusz_w_grze_Wiedźmin:_Pogromca_Potworów"),
}
TAGS = ["URBAN", "NON_URBAN", "FOREST", "WATER", "NEUTRAL1", "NEUTRAL2", "NEUTRAL3", "DAY", "NIGHT", "DAWN", "DUSK",
        "D_AND_D", "NOON", "MIDNIGHT", "RAIN", "FOG", "FOG_ONLY", "FULL_MOON", "FULL_MOON_ONLY"]
CATEGORIES = {
    "habitat": ["FOREST", "WATER", "URBAN", "NON_URBAN", "NEUTRAL2", "NEUTRAL3"],
    "weather": ["RAIN", "FOG", "FOG_ONLY"],
    "time": ["DAY", "NIGHT", "DAWN", "DUSK", "D_AND_D", "NOON", "MIDNIGHT"],
    "moon": ["FULL_MOON", "FULL_MOON_ONLY"],
}
RARITY = {"common": 1, "rare": 2, "legendary": 3, "pospolite": 1, "rzadkie": 2, "legendarne": 3}
MATCH = 0.8  # least difflib ratio between a wiki sentence and the client's phrase
# The Polish page shortens some phrases ("Wzrost aktywności podczas opadów" for the client's "Odnotowuje się wzrost aktywności
# w czasie opadów.") and joins green areas and wetlands in one sentence; these words decide when no phrase matches.
KEYWORDS = [(r"obszary zielone.*podmok", ["FOREST", "WATER"]), (r"opad", ["RAIN"]),
            (r"świ[tc].*zmierzch|zmierzch.*świ[tc]", ["D_AND_D"]), (r"świ[tc]", ["DAWN"]), (r"zmierzch", ["DUSK"])]


class Client:
    """The 1.1.116 client's I2Languages strings (English is language 0, Polish language 1), read from the APK."""

    def __init__(self, apk: Path):
        with zipfile.ZipFile(apk) as z:
            for info in z.infolist():
                if info.filename.startswith("assets/bin/Data/") and info.file_size > 1_000_000:
                    data = z.read(info)
                    if b"I2Languages" in data and b"MONSTERS/OCCURANCE/" in data:
                        self.data = data
                        return
        raise SystemExit("The APK has no I2Languages asset.")

    def _string(self, pos):
        length = struct.unpack_from("<i", self.data, pos)[0]
        if not 0 <= length <= 20000:
            raise ValueError
        return self.data[pos + 4:pos + 4 + length].decode("utf-8"), (pos + 4 + length + 3) & ~3

    def texts(self, term: str) -> list[str]:
        key = term.encode()
        pos = self.data.find(struct.pack("<i", len(key)) + key)
        if pos < 0:
            return []
        _, p = self._string(pos)
        p += 4
        for _ in range(3):
            count = struct.unpack_from("<i", self.data, p)[0]
            if 5 <= count <= 40:
                out, q = [], p + 4
                for _ in range(count):
                    value, q = self._string(q)
                    out.append(value)
                return out
            _, p = self._string(p)
        return []


def fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.replace("ł", "l").replace("Ł", "L"))
    return re.sub(r"[^a-z]", "", text.encode("ascii", "ignore").decode().lower())


def fetch(api: str, page: str) -> tuple[str, int]:
    query = urllib.parse.urlencode({"action": "parse", "page": page, "prop": "wikitext|revid", "format": "json",
                                    "formatversion": 2})
    request = urllib.request.Request(f"{api}?{query}", headers={"User-Agent": "WitcherRevival/0.3 (bestiary research)"})
    with urllib.request.urlopen(request, timeout=30) as response:
        parsed = json.load(response)["parse"]
    return parsed["wikitext"], parsed["revid"]


def rows(wikitext: str) -> list[dict]:
    """Every table row: its section's rarity, the name cell, the skulls cell and the last (occurrences) cell."""
    out, rarity = [], None
    for part in re.split(r"(?m)^(==[^=].*?==)\s*$", wikitext):
        if part.startswith("=="):
            words = fold(part).replace("creatures", "")
            rarity = next((r for word, r in RARITY.items() if fold(word) in words), None)
            continue
        for table in re.findall(r"\{\|(.*?)\|\}", part, re.S):
            for row in table.split("\n|-")[1:]:
                cells = [c.strip() for c in re.split(r"\n\|", "\n" + row.strip())[1:]]
                if len(cells) < 6:
                    continue
                clean = [re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", re.sub(r'align="center"\s*\|', "", c)).strip()
                         for c in cells]
                name = re.sub(r"<br\s*/?>", " ", clean[1]).strip()
                skulls = clean[2] if clean[2].isdigit() else None
                out.append({"name": name, "rarity": rarity, "skulls": int(skulls) if skulls else None, "occurrences": clean[-1]})
    return out


def sentences(text: str) -> list[str]:
    text = re.sub(r"<br\s*/?>", "\n", text)
    parts = re.split(r"\n|(?<=\.)\s+|\.(?=[A-ZĄĆĘŁŃÓŚŹŻ])", text)
    return [p.strip(" .") for p in parts if p.strip(" .")]


def norm(text: str) -> str:
    text = re.sub(r"\[\d\{|\}\d\]|<[^>]+>", "", text).replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", re.sub(r"[.,]", "", text)).strip().lower()


def to_tags(text: str, phrases: dict[str, str]) -> tuple[list[str], list[str]]:
    tags, unmatched = [], []
    for sentence in sentences(text):
        score, tag = max((difflib.SequenceMatcher(None, norm(sentence), norm(phrase)).ratio(), tag)
                         for tag, phrase in phrases.items())
        if score >= MATCH:
            tags.append(tag)
        elif (words := next((t for pattern, t in KEYWORDS if re.search(pattern, sentence.lower())), None)) is not None:
            tags += words
        else:
            unmatched.append(sentence)
    return tags, unmatched


def do_fetch(args):
    client = Client(args.apk)
    world = json.loads(args.world.read_text(encoding="utf-8"))
    by_name = {"en": {}, "pl": {}}
    for species in world["species"]:
        names = client.texts(f"MONSTERS/NAMES/{species['slug'].upper()}")
        by_name["en"][fold(species["name"])] = species["slug"]
        if len(names) > 1:
            by_name["pl"][fold(names[1])] = species["slug"]
    snapshot = {"fetched": datetime.date.today().isoformat(), "pages": {}, "species": {}, "unmatched_rows": {}}
    for language, (api, page) in PAGES.items():
        index = 0 if language == "en" else 1
        phrases = {tag: client.texts(f"MONSTERS/OCCURANCE/{tag}")[index] for tag in TAGS}
        wikitext, revision = fetch(api, page)
        snapshot["pages"][language] = {"api": api, "page": page, "revision": revision}
        snapshot["unmatched_rows"][language] = []
        for row in rows(wikitext):
            slug = by_name[language].get(fold(row["name"]))
            if slug is None:
                snapshot["unmatched_rows"][language].append(row["name"])
                continue
            tags, unmatched = to_tags(row["occurrences"], phrases)
            no_data = "NEUTRAL1" in tags
            snapshot["species"].setdefault(slug, {})[language] = {
                "name": row["name"], "rarity": row["rarity"], "skulls": row["skulls"], "occurrences": row["occurrences"],
                "tags": tags, "no_data": no_data, "unmatched": unmatched}
    args.output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    missing = [s["slug"] for s in world["species"] if "en" not in snapshot["species"].get(s["slug"], {})]
    unmatched = sum(len(r.get(lang, {}).get("unmatched", [])) for r in snapshot["species"].values() for lang in ("en", "pl"))
    print(f"{len(snapshot['species'])} species; missing on the English page: {missing or 'none'}; "
          f"rows without a species: {snapshot['unmatched_rows']}; sentences without a tag: {unmatched}")


def merge(species: dict, entry: dict) -> tuple[list[str], dict]:
    client = species.get("client_tags", species["tags"])
    source, tags = {}, []
    for category, members in CATEGORIES.items():
        for language in ("en", "pl"):
            row = entry.get(language)
            found = [t for t in (row or {}).get("tags", []) if t in members]
            if found:
                source[category] = language
                break
        else:
            found = [t for t in client if t in members]
            source[category] = "client" if found else "none"
        if category == "time" and "DAWN" in found and "DUSK" in found:
            found = [t for t in found if t not in ("DAWN", "DUSK")] + ["D_AND_D"]
        tags += [t for t in members if t in found]
    return tags, source


def do_apply(args):
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    world = json.loads(args.world.read_text(encoding="utf-8"))
    rows_by_id = {row["id"]: row for row in world["monsters"]}
    changed = []
    for species in world["species"]:
        entry = snapshot["species"].get(species["slug"])
        if not entry or "en" not in entry:
            raise SystemExit(f"{species['slug']} has no row on the English page")
        species["client_tags"] = species.get("client_tags", species["tags"])
        species["tags"], species["tags_source"] = merge(species, entry)
        en = entry["en"]
        rarity = en["rarity"] or species["rarity"]
        skulls = en["skulls"] if en["skulls"] is not None else (entry.get("pl") or {}).get("skulls") or species["skulls"]
        if (rarity, skulls) != (species["rarity"], species["skulls"]) or species["tags"] != species["client_tags"]:
            changed.append(species["slug"])
        species["rarity"], species["skulls"] = rarity, skulls
        if species["monster_id"] >= 101:
            species["difficulty"] = min(3, skulls + 1)   # world_bestiary.py's rule for new rows
        if (row := rows_by_id.get(species["monster_id"])) is not None:
            row["rarity"], row["difficulty"] = rarity, species["difficulty"]
    world["source"] = (world["source"].split(" + wiki")[0] +
                       f" + wiki_bestiary.py (en rev {snapshot['pages']['en']['revision']}, pl rev "
                       f"{snapshot['pages']['pl']['revision']}, fetched {snapshot['fetched']})")
    args.world.write_text(json.dumps(world, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(changed)} species changed: {', '.join(changed)}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    f = commands.add_parser("fetch")
    f.add_argument("--apk", type=Path, required=True)
    f.add_argument("--world", type=Path, required=True)
    f.add_argument("--output", type=Path, required=True)
    a = commands.add_parser("apply")
    a.add_argument("--snapshot", type=Path, required=True)
    a.add_argument("--world", type=Path, required=True)
    args = parser.parse_args(argv)
    (do_fetch if args.command == "fetch" else do_apply)(args)


if __name__ == "__main__":
    sys.exit(main())
