"""Rebuild the wiki-derived tables in server/WitcherRevival.Server/StaticData/static_data.json (Phase 1).

The original numbers only lived in the dead server's static data; the Witcher wiki documents them per version.
Every value written here is pulled from a parsed wiki row (tools/data_sources/wiki/*.json, run wiki_scrape.py
first), always from the pre-1.2 section because our client is 1.0.43. Mapping effect text -> the client's own enums
(EffectBehaviourType / ApplyTime from tools/dump/dump.cs, damage types = Vulnerability.Type) is spelled out below.
Each generated row's source goes to tools/data_sources/static_data_sources.json; anything the wiki doesn't quantify
keeps its current value and is printed under REVIEW.

  python tools/data_sources/build_static_data.py
"""
import collections, json, os, re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
STATIC = os.path.join(ROOT, "server", "WitcherRevival.Server", "StaticData", "static_data.json")
SOURCES = os.path.join(HERE, "static_data_sources.json")
DAMAGE_TYPES = {"FIRE": 1, "SILVER": 2, "STEEL": 3, "KINETIC ENERGY": 4, "DIMERITIUM": 7}  # Vulnerability.Type

# slug suffix -> (wiki name, EffectBehaviourType, ApplyTime). Number = first "N%" in the effect text.
POTIONS = {
    "blizzard": ("Blizzard", "GenerateAdrenaline", "OnStart"),            # "some CRITICAL HIT METER charge"
    "cat": ("Cat", "ImproveDamageDuringNight", "OnStart"),
    "mariborforest": ("Petri's Philter", "ImproveSigns", "OnStart"),
    "squall": ("Squall", "ImproveDamageWhenRaining", "OnStart"),
    "swallow": ("Swallow", "HealOverTime", "OnStart"),                     # 1% of vitality per second
    "swift": ("Swift", "ImproveHealth", "OnStart"),
    "tawnyowl": ("Tawny Owl", "ImproveSignsCooldownReduction", "OnStart"),
    "thunderbolt": ("Thunderbolt", "ImproveAttackPower", "OnStart"),
    "wolverine": ("Wolverine", "ImproveDamageOnLowHP", "OnStart"),         # +100% at <= 30% vitality
}
OIL_FAMILY = {"cursed": "Cursed", "draconid": "Draconides", "elemental": "Elementals", "hybrid": "Hybrids",
              "insectoid": "Insectoids", "necrophage": "Necrophages", "ogroid": "Ogroids", "relict": "Relicts",
              "specter": "Specters", "vampire": "Vampires"}
BOMBS = {"basic": "Basic bomb", "dancingstar": "Dancing Star", "dimeritium": "Dimeritium Bomb",
         "grapeshot": "Grapeshot", "moondust": "Moon Dust"}

review, sources = [], collections.OrderedDict()


def enum(name):
    dump = open(os.path.join(ROOT, "tools", "dump", "dump.cs"), encoding="utf-8", errors="replace").read()
    i = dump.index(f"public enum {name} //")
    return {k: int(v) for k, v in re.findall(r"public const [\w.]+ (\w+) = (-?\d+);", dump[i:dump.index("\n}", i)])}


def wiki_rows(page, pre12):
    d = json.load(open(os.path.join(HERE, "wiki", page + ".json"), encoding="utf-8"))
    for s in d["sections"]:
        if pre12(s["title"]):
            for t in s["tables"]:
                for r in t["rows"]:
                    yield r["Name"], r, {"page": d["page"], "revid": d["revid"], "section": s["title"]}


def by_name(page, pre12):
    return {name.lower(): (row, src) for name, row, src in wiki_rows(page, pre12)}


def main():
    data = json.load(open(STATIC, encoding="utf-8"), object_pairs_hook=collections.OrderedDict)
    beh, when = enum("EffectBehaviourType"), enum("ApplyTime")
    ids = lambda table: {r["slug"]: r["id"] for r in data[table]}
    old = lambda table: {(r["item_id"], r["effect_id"]): r["power"] for r in data.get(table, [])}

    def effect_row(table, item_id, effect, text, apply, src, fallback_old):
        m = re.search(r"(\d+)%", text)
        if m: power = int(m.group(1))
        else:  # keep a previous value if there is one, else an explicit placeholder; flagged either way
            power = fallback_old.get((item_id, beh[effect])) or 10
            src = dict(src, placeholder=True)
            review.append(f"{table} item {item_id} ({src['name']}): wiki gives no number ('{text}'); placeholder power {power}")
        row = collections.OrderedDict(item_id=item_id, effect_id=beh[effect], power=power, effect_apply_type_id=when[apply])
        sources.setdefault(table, []).append({"row": row, "source": src})
        return row

    pre = lambda title: "PRE" in title.upper() or "BEFORE" in title.upper()
    potions, pid, prev = by_name("potions", pre), ids("potions"), old("potion_to_effect")
    data["potion_to_effect"] = []
    for suffix, (name, effect, apply) in POTIONS.items():
        row, src = potions[name.lower()]
        data["potion_to_effect"].append(effect_row("potion_to_effect", pid["potion_" + suffix], effect, row["Effect"],
                                                   apply, dict(src, name=name, text=row["Effect"]), prev))

    oils, oid, prev = by_name("oils", pre), ids("oils"), old("oil_to_effect")
    data["oil_to_effect"] = []
    for slug, item_id in oid.items():
        suffix = slug[len("oil_"):]
        name = "Basic oil" if suffix == "basic" else suffix.capitalize() + " oil"
        effect = "ImproveAttackPower" if suffix == "basic" else "ImproveAttacksAgainst" + OIL_FAMILY[suffix]
        row, src = oils[name.lower()]
        data["oil_to_effect"].append(effect_row("oil_to_effect", item_id, effect, row["Effect"], "OnStart",
                                                dict(src, name=name, text=row["Effect"]), prev))

    bombs, bid = by_name("bombs", pre), ids("bombs")
    data["bomb_damage_types"] = []
    for suffix, name in BOMBS.items():
        row, src = bombs[name.lower()]
        hits = re.findall(r"(\d+) damage points from (FIRE|KINETIC ENERGY|STEEL|SILVER)", row["Effect"])
        if "DIMERITIUM" in row["Effect"]:
            review.append(f"bomb {name}: dimeritium cloud has no damage number; no dimeritium row written")
        for amount, kind in hits:
            r = collections.OrderedDict(bomb_id=bid["bomb_" + suffix], damage_type_id=DAMAGE_TYPES[kind], amount=int(amount))
            data["bomb_damage_types"].append(r)
            sources.setdefault("bomb_damage_types", []).append({"row": r, "source": dict(src, name=name, text=row["Effect"])})

    data["_notes"]["potion_to_effect"] = data["_notes"]["oil_to_effect"] = data["_notes"]["bomb_damage_types"] = (
        "Generated by tools/data_sources/build_static_data.py from the Witcher wiki's pre-1.2 tables (client 1.0.43); "
        "sources per row in tools/data_sources/static_data_sources.json. effect_id = EffectBehaviourType, "
        "effect_apply_type_id = ApplyTime, damage_type_id = Vulnerability.Type; percent effects use the percent as power.")

    with open(STATIC, "w", encoding="utf-8") as f:
        f.write("{\n")
        keys = list(data)
        for i, k in enumerate(keys):
            end = ",\n" if i < len(keys) - 1 else "\n"
            if k == "_notes":
                f.write(' "_notes": ' + json.dumps(data[k], ensure_ascii=False, indent=2).replace("\n", "\n ") + end)
            else:
                rows = ",\n".join("  " + json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in data[k])
                f.write(f' "{k}": [\n{rows}\n ]' + end)
        f.write("}\n")
    json.dump(sources, open(SOURCES, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("wrote", {t: len(data[t]) for t in ("potion_to_effect", "oil_to_effect", "bomb_damage_types")})
    for r in review: print("REVIEW:", r)


if __name__ == "__main__":
    main()
