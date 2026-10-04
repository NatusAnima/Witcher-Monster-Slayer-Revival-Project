#!/usr/bin/env python3
"""Build the world bestiary the server loads (WitcherRevival.Server/Story/world-bestiary.json).

The 1.1.116 client ships every monster of the game, not only those of the tutorial and season 1: each has an lq
map model, an hq presentation, a <slug>_settings asset (fight tuning and TrophyImageAddress) and bestiary texts
(MONSTERS/NAMES/<KEY>, MONSTERS/DESCRIPTIONS/<KEY>/INFO_1..5). INFO_1 names the family (MONSTERS/FAMILIES/<X>)
and INFO_2 the occurrences (MONSTERS/OCCURANCE/<X>: URBAN, NON_URBAN, FOREST, WATER, NEUTRAL2, DAY, NIGHT, DAWN,
DUSK, NOON, MIDNIGHT, RAIN, FOG, FULL_MOON, FULL_MOON_ONLY). The server decides where and when monsters appear,
so these client texts are the best evidence of the original spawn rules.

Rarity, skulls and vulnerabilities are not in the client; they come from the community sheet M01, matched by
the client's English name. The server's existing rows (ids 1-36, from the inherited sample and the season 1
story) keep their ids and fields; every other client monster with a name, texts and a sheet row gets a new row
from FIRST_ID, keeping the id it had in the previous build of the output file. The output lists every species the world may spawn, old and new, with the client's family and
occurrence tags. The script refuses to write the file when a check fails.

  python world_bestiary.py --catalog <LAB APK>/assets/aa/catalog.json --apk-data <LAB APK>/assets/bin/Data \
      --settings <LAB APK>/assets/assetpack/s00_monsters_map_settings_assets_all --sheet m01.csv \
      --story ../WitcherRevival.Server/Story/season1-story.json --output ../WitcherRevival.Server/Story/world-bestiary.json

Requires UnityPy (analysis venv) for the settings asset pack.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

from quest_atlas import Localization
from season1_story import EXISTING_DIFFICULTY, EXISTING_MONSTERS, catalog_keys

FIRST_ID = 101
MONSTER_ROOT = "assets/_bundledassets/characters/monsters/s00"
# Client: MONSTERS/FAMILIES/<X> -> monster_families ids (PreloaderStaticData).
FAMILIES = {"NECROPHAGE": 1, "DRACONIDE": 2, "OGROID": 3, "HYBRID": 4, "ELEMENTAL": 5, "RELICT": 6, "SPECTER": 7,
            "INSECTOID": 8, "ANIMAL": 9, "VAMPIRE": 10, "CURSED": 11}
OCCURRENCES = {"URBAN", "NON_URBAN", "FOREST", "WATER", "NEUTRAL1", "NEUTRAL2", "NEUTRAL3", "DAY", "NIGHT", "DAWN",
               "DUSK", "D_AND_D", "NOON", "MIDNIGHT", "RAIN", "FOG", "FOG_ONLY", "FULL_MOON", "FULL_MOON_ONLY"}
# Fight targets that are not wild monsters. Their graphs attach the monster settings themselves, the client's own
# fallback for a slug that is not in the monsters table (PrepareFightNode.LoadMechanic: "... is not listed as map
# monster. Attach monster settings manually"): the training dummies of the Practice tab and Vesemir (tut_ui,
# tut_witcher, tut_dummy_1..3) and the human story actors and quest golem of season 1. The dummies and the cursed
# Liho (a quest POI of s01mq04) have no bestiary texts either.
STORY_ONLY = {"actor_fightable", "hermit_fightable", "golem_lvl2_hq01", "dummy_lvl1", "dummy_lvl2", "dummy_lvl3"}
# The sheet lists the Golden Katakan as legendary without skulls or vulnerabilities. Authored: three skulls like
# the other legendary monsters and the vulnerabilities of the Katakan it varies.
SHEET_FILL = {"goldenkatakan": {"skulls": 3, "vulnerable_from": "katakan"}}
# The sheet spells two names differently from the client.
SHEET_ALIASES = {"bloedzuiger": "bloodzuiger", "archespore": "archspore"}
# Strong, Fast, Steel, Silver, Fire, Kinetic, Dime -> damage_types ids (Reconstruction.DamageTypes).
DAMAGE_TYPES = (6, 5, 3, 2, 1, 4, 7)


def fold(name: str) -> str:
    return re.sub(r"[^a-z]", "", name.lower())


def sheet_rows(path: Path) -> dict[str, dict]:
    rows = {}
    with path.open(newline="") as stream:
        reader = csv.reader(stream)
        next(reader); next(reader)
        for row in reader:
            if len(row) < 11 or not row[2].strip():
                continue
            rows[fold(row[2])] = {
                "name": row[2].strip(),
                "rarity": {"Common": 1, "Rare": 2, "Legendary": 3}.get(row[0].strip()),
                "skulls": int(row[1]) if row[1].strip().isdigit() else None,
                "vulnerable": [dt for dt, mark in zip(DAMAGE_TYPES, row[4:11]) if mark.strip()],
            }
    return rows


def settings_trophies(path: Path) -> dict[str, str]:
    """slug -> TrophyImageAddress of every <slug>_settings asset in the map settings pack."""
    import UnityPy
    trophies = {}
    for container, obj in UnityPy.load(str(path)).container.items():
        match = re.search(r"/([a-z0-9_]+)_settings\.asset$", container.lower())
        if match:
            trophies[match.group(1)] = obj.read_typetree().get("TrophyImageAddress", "")
    return trophies


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--apk-data", type=Path, required=True)
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--sheet", type=Path, required=True)
    parser.add_argument("--story", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    keys = catalog_keys(args.catalog)
    text = Localization(args.apk_data)
    if not text.data:
        raise SystemExit("I2Languages not found in --apk-data")
    sheet = sheet_rows(args.sheet)
    for name, fill in SHEET_FILL.items():
        if name in sheet:
            sheet[name]["skulls"] = sheet[name]["skulls"] if sheet[name]["skulls"] is not None else fill["skulls"]
            sheet[name]["vulnerable"] = sheet[name]["vulnerable"] or sheet[fill["vulnerable_from"]]["vulnerable"]
    trophies = settings_trophies(args.settings)
    story = json.loads(args.story.read_text())
    errors, left_out = [], {}

    existing = {slug: {"id": monster_id, "difficulty": EXISTING_DIFFICULTY[monster_id]}
                for slug, monster_id in EXISTING_MONSTERS.items()}
    existing.update({row["slug"]: {"id": row["id"], "difficulty": row["difficulty"], "family": row["family_id"]}
                     for row in story["monsters"]})
    slugs = sorted(set(trophies) | set(existing))

    species, rows, vulnerabilities = [], [], {}
    # Rows keep the ids of the previous build, so kills and knowledge stay with their monster; others follow.
    previous = {row["slug"]: row["id"] for row in json.loads(args.output.read_text())["monsters"]} \
        if args.output.exists() else {}
    next_id = max([FIRST_ID - 1, *previous.values()]) + 1
    for slug in slugs:
        if slug in STORY_ONLY:
            left_out[slug] = "fight target with its settings attached by its graph"
            continue
        key = slug.upper()
        english = text.text(f"MONSTERS/NAMES/{key}")[1]
        lines = [text.text(f"MONSTERS/DESCRIPTIONS/{key}/INFO_{n}")[1] for n in range(1, 6)]
        if not english or not all(lines):
            left_out[slug] = "no bestiary name or texts in I2Languages"
            continue
        family = re.findall(r"MONSTERS/FAMILIES/(\w+)", lines[0])
        tags = re.findall(r"MONSTERS/OCCURANCE/(\w+)", lines[1])
        if len(family) != 1 or family[0] not in FAMILIES or not tags or not set(tags) <= OCCURRENCES:
            errors.append(f"{slug}: unreadable family or occurrences")
            continue
        stats = sheet.get(SHEET_ALIASES.get(fold(english), fold(english)))
        if stats is None or stats["rarity"] is None or stats["skulls"] is None:
            left_out[slug] = f"no rarity or skulls in the sheet for {english}"
            continue
        family_id = FAMILIES[family[0]]
        model = f"{MONSTER_ROOT}/{slug}/{slug}_lq/{slug}_lq.prefab"
        if slug in existing:
            monster_id, difficulty = existing[slug]["id"], existing[slug]["difficulty"]
            if existing[slug].get("family", family_id) != family_id:
                errors.append(f"{slug}: story row family {existing[slug]['family']} but the client says {family[0]}")
        else:
            image = f"{MONSTER_ROOT}/{slug}/{slug}_hq/{slug}_hq_presentation.prefab"
            trophy = trophies.get(slug, "")
            for needed in (model, image, trophy):
                if needed.lower() not in keys:
                    errors.append(f"{slug}: {needed or 'trophy'} is not in the client catalog")
            difficulty = min(3, stats["skulls"] + 1)
            if slug in previous:
                monster_id = previous[slug]
            else:
                monster_id, next_id = next_id, next_id + 1
            rows.append({"id": monster_id, "family_id": family_id, "encounter_distance": 50,
                         "attack_animation_time": 2000, "rarity": stats["rarity"], "difficulty": difficulty,
                         "name": f"MONSTERS/NAMES/{key}", "model": "A" + model[1:],
                         "image": "A" + image[1:], "trophy": "A" + trophy[1:], "slug": slug})
            vulnerabilities[slug] = stats["vulnerable"]
            if not stats["vulnerable"]:
                errors.append(f"{slug}: no vulnerabilities in the sheet")
        species.append({"monster_id": monster_id, "slug": slug, "name": english, "sheet": stats["name"],
                        "family": family_id, "rarity": stats["rarity"], "skulls": stats["skulls"],
                        "difficulty": difficulty, "tags": tags})

    for slug in existing:
        if slug not in STORY_ONLY and not any(s["slug"] == slug for s in species):
            errors.append(f"{slug}: existing row without client bestiary data")
    if errors:
        raise SystemExit("\n".join(errors))
    bestiary = {"source": "world_bestiary.py (client bestiary texts and settings of 1.1.116, community sheet M01)",
                "species": species, "monsters": rows, "vulnerabilities": vulnerabilities, "left_out": left_out}
    args.output.write_text(json.dumps(bestiary, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(species)} species, {len(rows)} new rows, left out: {len(left_out)}")


if __name__ == "__main__":
    main()
