"""Scrape The Witcher: Monster Slayer pages from the Witcher wiki into JSON (Phase 1: recover original values).

The game's numbers (effect %, durations, costs, recipes, prices) only ever lived in the dead server's static data;
the wiki documents them, version by version (sections like "PRE-1.2.0" — our client is 1.0.43). Each page becomes
tools/data_sources/wiki/<slug>.json with every table row parsed per section, plus the page's revision id, so any
value copied into PreloaderStaticData.cs can be traced back. Quest and bestiary pages are also kept as raw
wikitext (walkthroughs, infoboxes) for later reading.

  python tools/data_sources/wiki_scrape.py
"""
import json, os, re, time, urllib.parse, urllib.request

API = "https://witcher.fandom.com/api.php"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wiki")
LIST_PAGES = ["armor", "bags", "baits", "bestiary", "bombs", "boosters", "character", "contracts", "crafting",
              "gifts", "glossary", "ingredients", "oils", "potions", "quests", "scrolls", "skills", "swords",
              "timed tasks", "trinkets"]
EXTRA_PAGES = ["Thorstein's shop", "XP", "Thorstein"]
CATEGORIES = ["Category:The Witcher Monster Slayer quests", "Category:The Witcher Monster Slayer bestiary"]


def api(**params):
    params["format"] = "json"
    req = urllib.request.Request(API + "?" + urllib.parse.urlencode(params), headers={"User-Agent": "TWMS-revival/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)
    time.sleep(0.5)  # be gentle with the wiki
    return data


def clean(cell):
    s = re.sub(r"\[\[(?:File|Image):[^\]]*\]\]", "", cell)
    s = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", s)        # [[target|text]] -> text
    s = re.sub(r"\{\{(?:[^}|]*\|)?([^}]*)\}\}", r"\1", s)          # {{tpl|x}} -> x
    s = re.sub(r"<br\s*/?>", "; ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s).replace("'''", "").replace("''", "")
    return re.sub(r"\s+", " ", s).strip(" ;")


def cell_value(raw):
    # "align="center" |30" -> "30": attributes sit before a single '|' that isn't part of a link
    parts = re.split(r"(?<!\|)\|(?!\|)(?![^\[]*\]\])", raw, maxsplit=1)
    return parts[1] if len(parts) == 2 and "=" in parts[0] and "[[" not in parts[0] else raw


def parse_tables(text):
    tables = []
    for body in re.findall(r"\{\|(.*?)\n\|\}", text, re.S):
        headers, rows, row = [], [], None
        for line in body.split("\n")[1:]:
            line = line.strip()
            if line.startswith("!"):
                headers += [clean(cell_value(h)) for h in re.split(r"!!", line[1:])]
            elif line.startswith("|-"):
                if row: rows.append(row)
                row = []
            elif line.startswith("|") and row is not None:
                row += [cell_value(c) for c in re.split(r"\|\|", line[1:])]
            elif row:  # continuation of the previous cell
                row[-1] += "\n" + line
        if row: rows.append(row)
        tables.append({"headers": headers,
                       "rows": [{(headers[i] if i < len(headers) else f"col{i}"): clean(c) for i, c in enumerate(r)}
                                for r in rows if any(clean(c) for c in r)]})
    return tables


def sections(text):
    parts = re.split(r"^(==+)\s*(.*?)\s*\1\s*$", text, flags=re.M)
    out = [{"title": "(intro)", "tables": parse_tables(parts[0])}]
    for i in range(1, len(parts) - 2, 3):
        out.append({"title": parts[i + 1], "level": len(parts[i]), "tables": parse_tables(parts[i + 2])})
    return [s for s in out if s["tables"]]


def fetch(title):
    d = api(action="parse", page=title, prop="wikitext|revid", redirects=1)["parse"]
    return d["title"], d["revid"], d["wikitext"]["*"]


def save(name, payload):
    path = os.path.join(OUT, re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") + ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    return path


def main():
    os.makedirs(OUT, exist_ok=True)
    for t in ["The Witcher Monster Slayer " + p for p in LIST_PAGES] + EXTRA_PAGES:
        title, revid, text = fetch(t)
        secs = sections(text)
        print(f"{title}: rev {revid}, {sum(len(tb['rows']) for s in secs for tb in s['tables'])} rows")
        save(title.replace("The Witcher Monster Slayer ", ""), {"page": title, "revid": revid, "sections": secs, "wikitext": text})
    for cat in CATEGORIES:
        members = api(action="query", list="categorymembers", cmtitle=cat, cmlimit=500)["query"]["categorymembers"]
        pages = {}
        for m in members:
            if m["ns"] != 0: continue
            title, revid, text = fetch(m["title"])
            pages[title] = {"revid": revid, "wikitext": text, "sections": sections(text)}
        print(f"{cat}: {len(pages)} pages")
        save(cat.split(":", 1)[1].replace("The Witcher Monster Slayer ", "") + " pages", {"category": cat, "pages": pages})


if __name__ == "__main__":
    main()
