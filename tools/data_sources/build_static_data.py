"""Rebuild the wiki-derived tables in server/WitcherRevival.Server/StaticData/static_data.json (Phase 1): consumable
effects, bomb damage, and the monsters the story graphs fight.

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

# Monster slug (client asset / localization slug) -> wiki bestiary name. Every monster a story graph fights
# (quest_catalog.json seeds:MonsterSlug) must exist: DataManager.LoadMonsters and the fight graphs look them up.
# family_id = wiki Type, difficulty = pre-1.2 skulls + 1 (difficulties tiers 1..3), rarity = wiki section
# (MonsterRaritySettings.GetAddress indexes [rarity - 1]: 1 common, 2 rare, 3 legendary). None = no wiki row.
MONSTERS = {
    "ghoul": "Ghoul", "alghoul": "Alghoul", "drowner": "Drowner", "nekker": "Nekker",
    "nekkerwarrior": "Nekker Warrior", "werewolf": "Werewolf", "banshee": "Beann'shie", "devourer": "Devourer",
    "gravehag": "Grave hag", "arachas": "Common Arachas", "arachnomorph": "Arachnomorph", "archespore": "Archespore",
    "bies_lvl1": "Fiend", "cavetroll": "Rock Troll", "chort_lvl1": "Chort", "elementaldaored": "D'ao",
    "endriagaspikey": "Endrega Drone", "endriagatailed": "Endrega Warrior", "endriagaworker": "Endrega Worker",
    "fogling_lvl1": "Foglet", "foglingignisfatuus": "Ignis Fatuus", "forktail": "Forktail",
    "frightener": "Frightener", "gargoyle": "Gargoyle", "golem_lvl1": "Golem", "golem_lvl2": "Stone Golem",
    "cockatrice": "Cockatrice",                  # golem_lvl1 / cockatrice: presentation seeds (monster lookup by slug)
    "golem_lvl2_hq01": "Stone Golem",            # Sword in the Stone's guardian: golem_lvl2 with its own settings
    "gryphon": "Griffin", "leshensdog_lvl2": "Leshen Hound", "lessun": "Leshen", "likho": "Liho",
    "nekkerwarrior_lvl3": "Nekker Shaman", "scolopendromorph_lvl1": "Scolopendromorph",
    "striga_albino": "White Striga", "vodyanoi": "Vodnik", "wraith": "Wraith",
    "wraith_lvl2": "Wraith",                     # no separate wiki row
    "actor_fightable": None, "hermit_fightable": None,  # humans the To the Rescue / Sins of our Fathers graphs fight
}
FAMILIES = {"necrophages": 1, "draconids": 2, "ogroids": 3, "hybrids": 4, "elementa": 5, "relicts": 6,
            "specters": 7, "insectoids": 8, "vampires": 10, "cursed ones": 11}
RARITY = {"Common Creatures": 1, "Rare Creatures": 2, "Legendary Creatures": 3}
ASSET_ALIAS = {"golem_lvl2_hq01": "golem_lvl2"}  # only its _settings asset is its own

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


def build_monsters(data):
    """Adds every MONSTERS slug missing from monsters (+ its 3 description tiers) and sets family/difficulty/rarity
    from the wiki. Asset paths and localization keys come from the client (catalog.json, stringliteral.json)."""
    keys = json.load(open(os.path.join(ROOT, "tools", "dump", "catalog.json"), encoding="utf-8"))["m_InternalIds"]
    assets = {k.rsplit("/", 1)[-1].lower(): k for k in keys if isinstance(k, str) and k.startswith("Assets/")}
    lits = {x["value"] for x in json.load(open(os.path.join(ROOT, "tools", "dump", "stringliteral.json"), encoding="utf-8"))}
    page = json.load(open(os.path.join(HERE, "wiki", "bestiary.json"), encoding="utf-8"))
    wiki = {r["Name"].lower(): (r, s["title"]) for s in page["sections"] for t in s["tables"] for r in t["rows"]}
    rows = {m["slug"]: m for m in data["monsters"]}
    described = {d["monster_id"] for d in data["monster_descriptions"]}
    for slug, name in MONSTERS.items():
        m = rows.get(slug)
        if m is None:
            a = ASSET_ALIAS.get(slug, slug)
            key = slug if f"MONSTERS/BESTIARY/{slug.upper()}" in lits else a
            m = collections.OrderedDict(id=max(r["id"] for r in data["monsters"]) + 1, family_id=9, encounter_distance=50,
                                        attack_animation_time=2000, rarity=1, difficulty=1,
                                        name=f"MONSTERS/BESTIARY/{key.upper()}", model="", image="", trophy="", slug=slug)
            data["monsters"].append(m)
            rows[slug] = m
            if m["name"] not in lits: review.append(f"monster {slug}: the client has no {m['name']} text")
        a = ASSET_ALIAS.get(slug, slug)  # fill empty asset fields (hand-made rows keep theirs)
        m["model"] = m["model"] or assets.get(f"{a}_lq.prefab", "")
        m["image"] = m["image"] or assets.get(f"{a}_hq_presentation.prefab") or assets.get(f"{a}_hq.prefab", "")
        m["trophy"] = m["trophy"] or assets.get(f"trophy_{a}.png", "")
        if not m["model"]: review.append(f"monster {slug}: no {a}_lq.prefab in the catalog")
        if m["id"] not in described:
            key = m["name"].rsplit("/", 1)[-1]
            for level, threshold in ((1, 1), (2, 5), (3, 10)):
                data["monster_descriptions"].append(collections.OrderedDict(
                    id=max(d["id"] for d in data["monster_descriptions"]) + 1, monster_id=m["id"], level=level,
                    threshold=threshold, content=f"MONSTERS/DESCRIPTIONS/{key}/INFO_{level}"))
        if name is None:
            review.append(f"monster {slug}: no wiki row; family 9 / rarity 1 / difficulty 1 are placeholders")
            continue
        row, section = wiki[name.lower()]
        skulls = int(row["Skulls (pre-1.2)"])
        m["family_id"], m["rarity"], m["difficulty"] = FAMILIES[row["Type"].lower()], RARITY[section], min(skulls + 1, 3)
        if skulls + 1 > 3: review.append(f"monster {slug}: {skulls} skulls, capped at difficulty tier 3")
        sources.setdefault("monsters", []).append({
            "row": {k: m[k] for k in ("slug", "family_id", "rarity", "difficulty")},
            "source": {"page": page["page"], "revid": page["revid"], "section": section, "name": name,
                       "text": f"{row['Type']}; skulls (pre-1.2) {skulls}"}})


def main():
    data = json.load(open(STATIC, encoding="utf-8"), object_pairs_hook=collections.OrderedDict)
    build_monsters(data)
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

    data["_notes"]["monsters"] = (
        "Rows for every monster a story graph fights; family_id / rarity / difficulty generated by "
        "tools/data_sources/build_static_data.py from the wiki bestiary (family = Type, rarity = section 1 common / "
        "2 rare / 3 legendary, difficulty = pre-1.2 skulls + 1 capped at tier 3; sources in static_data_sources.json). "
        "model/image/trophy are the client's <slug>_lq / _hq_presentation / trophy_<slug> assets. encounter_distance "
        "and attack_animation_time are placeholders. difficulty references the difficulties ids 1..3 below.")
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
    print("wrote", {t: len(data[t]) for t in ("potion_to_effect", "oil_to_effect", "bomb_damage_types", "monsters",
                                              "monster_descriptions")})
    for r in review: print("REVIEW:", r)


if __name__ == "__main__":
    main()
