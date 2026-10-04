#!/usr/bin/env python3
"""Build the season 1 story data the server loads (WitcherRevival.Server/Story/season1-story.json).

Method: season1_graphs.py extracts every season 1 behaviour graph of the client (outputs, facts, fights, queued
nodes, modifiers); season1_quests.py holds the quest overlay (POIs, givers, conditions on facts, endings, rewards,
walk-throughs). This script joins them, assigns ids, derives the per-output rewards the graphs imply (the monster of
each won fight, gold announced through fact 175) and checks everything against the client:
  - every graph, POI setting and journal log is a key of the 1.1.116 Addressables catalog;
  - every output named in an ending or a walk-through exists in its node's graph;
  - every condition parses and names known nodes, outputs and quests;
  - every walk-through step sends only facts its graph sets;
  - every quest has exactly one root, givers stand inside the client's giver distance;
  - every monster a fight or a combat preparation loads has a monsters row.
It refuses to write the file when a check fails.

  python season1_story.py --graphs season1-graphs.json --catalog <LAB APK>/assets/aa/catalog.json \
      --sheet m01.csv --output ../WitcherRevival.Server/Story/season1-story.json
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import re
import struct
import sys
from pathlib import Path

from season1_quests import MODIFIER_SECONDS, MODIFIERS, MONSTERS, QUESTS

GIVER_DISTANCE = 350        # Client: PoiSettings.questOnMapHideDistance on LAB 16 (QuestPoiInstance.ShouldBeInstantiated)
GIVER_BAND = (80, 300)
POI_BAND = (250, 700)
EXISTING_MONSTERS = {"ghoul": 1, "alghoul": 2, "drowner": 3, "nekker": 4, "nekkerwarrior": 5, "werewolf": 6,
                     "smalldraconid": 7, "banshee": 8, "gryphon": 9, "devourer": 10, "wraith": 11, "wraith_lvl2": 12,
                     "gargoyle": 13, "endriagaworker": 14, "endriagatailed": 15, "endriagaspikey": 16}
EXISTING_DIFFICULTY = {1: 1, 2: 2, 3: 1, 4: 1, 5: 2, 6: 3, 7: 2, 8: 3, 9: 3, 10: 1, 11: 2, 12: 2, 13: 3, 14: 1, 15: 2, 16: 1}
BASE_EXP = {1: 100, 2: 250, 3: 600}      # Reconstruction.BaseExp (Community: Gamepressure)
ATOM = re.compile(r"^(!?)(?:f(\d+)(<=|>=|!=|=|<|>)(-?\d+)|out:([\w.]+)|wait:([\w.]+):(\d+)|done:(\d+)|started:(\d+))$")
AUTHORED_INSTANCE = 5124760000000000000


def catalog_keys(path: Path) -> set[str]:
    data = json.loads(path.read_text())
    raw = base64.b64decode(data["m_KeyDataString"])
    count, pos, keys = struct.unpack_from("<i", raw, 0)[0], 4, set()
    for _ in range(count):
        kind = raw[pos]; pos += 1
        if kind in (0, 1):
            size = struct.unpack_from("<i", raw, pos)[0]; pos += 4
            keys.add(raw[pos:pos + size].decode("utf-16" if kind == 1 else "ascii").lower()); pos += size
        elif kind == 4:
            pos += 4
        else:
            raise ValueError(f"catalog key type {kind}")
    return keys


def sheet_rows(path: Path) -> dict[str, dict]:
    rows = {}
    with path.open(newline="") as stream:
        reader = csv.reader(stream)
        next(reader); next(reader)
        for row in reader:
            if len(row) < 11 or not row[2].strip():
                continue
            # Strong, Fast, Steel, Silver, Fire, Kinetic, Dime -> damage_types ids (Reconstruction.DamageTypes).
            vulnerable = [dt for dt, mark in zip((6, 5, 3, 2, 1, 4, 7), row[4:11]) if mark.strip()]
            rows[row[2].strip()] = {"rarity": {"Common": 1, "Rare": 2, "Legendary": 3}.get(row[0].strip(), 1),
                                    "skulls": int(row[1]) if row[1].strip().isdigit() else 1, "vulnerable": vulnerable}
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--graphs", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--sheet", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    extracted = json.loads(args.graphs.read_text())
    graphs = extracted["graphs"]
    keys = catalog_keys(args.catalog)
    sheet = sheet_rows(args.sheet)
    errors: list[str] = []

    def need_key(key: str, what: str):
        if key.lower() not in keys:
            errors.append(f"{what}: {key} is not in the client catalog")

    # ── Monsters ────────────────────────────────────────────────────────────────────────────
    monster_ids = dict(EXISTING_MONSTERS)
    difficulty = dict(EXISTING_DIFFICULTY)
    monster_rows, vulnerabilities, count_kills = [], {}, {}
    next_id = max(monster_ids.values()) + 1
    for slug, (sheet_name, family, trophy, kills) in sorted(MONSTERS.items()):
        base = "golem_lvl2" if slug == "golem_lvl2_hq01" else slug
        root = f"assets/_bundledassets/characters/monsters/s00/{base}/{base}"
        model = f"{root}_lq/{base}_lq.prefab"
        image = f"{root}_hq/{base}_hq_presentation.prefab"
        if image.lower() not in keys:
            image = model
        trophy_key = f"assets/_bundledassets/ui/monster_trophies/{trophy or f'trophy_{base}.png'}"
        if trophy_key.lower() not in keys:
            trophy_key = ""
        need_key(model, f"monster {slug}")
        need_key(f"assets/_bundledassets/characters/monsters/s00/{slug}/{slug}_settings.asset", f"monster {slug}")
        stats = sheet.get(sheet_name, {"rarity": 1, "skulls": 1, "vulnerable": [6, 2]}) if sheet_name else \
            {"rarity": 1, "skulls": 1, "vulnerable": [6, 2]}
        level = min(3, stats["skulls"] + 1)
        monster_ids[slug] = next_id
        difficulty[next_id] = level
        count_kills[slug] = kills and bool(trophy_key)
        name = base.upper()
        monster_rows.append({"id": next_id, "family_id": family, "encounter_distance": 50, "attack_animation_time": 2000,
                             "rarity": stats["rarity"], "difficulty": level, "name": f"MONSTERS/BESTIARY/{name}",
                             "model": model, "image": image, "trophy": trophy_key, "slug": slug})
        vulnerabilities[slug] = stats["vulnerable"] or [6, 2]
        next_id += 1

    # ── Quests, nodes and outputs ───────────────────────────────────────────────────────────
    quests, nodes, outputs, walks = [], [], [], {}
    used_ids, used_instances = set(), set()
    next_output = 1001
    for q in QUESTS:
        quest_id, code = q["id"], q["code"]
        journal = f"assets/_bundledassets/story/journal/s01/{q['folder']}/log_{code}.asset"
        need_key(journal, f"{code} journal")
        quests.append({"id": quest_id, "code": code, "name": q["name"], "journal": journal, "criteria": q["criteria"]})
        auto = 12000 + quest_id * 40
        roots = [n for n in q["nodes"] if n["kind"] == "giver"] or [n for n in q["nodes"] if n["kind"] == "queued"][:1]
        if len(roots) != 1:
            errors.append(f"{code}: needs exactly one giver or one queued start")
        keys_here = {n["key"] for n in q["nodes"]}
        for n in q["nodes"]:
            graph_key = n["graph"] if n["graph"].startswith("quest_item_buttons/") else f"{q['folder']}/{n['graph']}"
            graph_key = "s01/" + graph_key
            graph = graphs.get(graph_key)
            if graph is None:
                errors.append(f"{n['key']}: graph {graph_key} not extracted")
                continue
            need_key(f"assets/_bundledassets/story/bgraphs/{graph_key}.asset", n["key"])
            if n["poi"]:
                need_key(n["poi"], n["key"])
            elif n["kind"] != "button":
                errors.append(f"{n['key']}: a map node needs POI settings")
            node_id = n["id"] or (graph["quest_node_id"] if graph["quest_node_id"] > 0 and graph["quest_node_id"] not in used_ids else None)
            if node_id is None:
                while auto in used_ids:
                    auto += 1
                node_id = auto
            if node_id in used_ids:
                errors.append(f"{n['key']}: node id {node_id} used twice")
            used_ids.add(node_id)
            instance = graph["instance_id"] if graph["instance_id"] not in (0, -1) and graph["instance_id"] not in used_instances \
                else AUTHORED_INSTANCE + node_id
            for k in range(n["copies"]):
                if instance + k in used_instances:
                    errors.append(f"{n['key']}: instance id used twice")
                used_instances.add(instance + k)
            band = n["band"] or (GIVER_BAND if n["kind"] == "giver" else POI_BAND)
            if n["kind"] == "giver" and band[1] > GIVER_DISTANCE - 30:
                errors.append(f"{n['key']}: a giver must stand well inside {GIVER_DISTANCE} m")
            nodes.append({"id": node_id, "quest": quest_id, "key": n["key"], "graph": graph_key, "poi": n["poi"] or "",
                          "instance": instance, "kind": n["kind"], "root": n["root"], "show": n["show"],
                          "min": band[0], "max": band[1], "near": n["near"], "placeOf": n["place_of"], "copies": n["copies"]})
            for name, info in graph["outputs"].items():
                reward = dict(q["end"].get(f"{n['key']}.{name}", {}))
                exp, gold = reward.get("exp", 0), reward.get("gold", 0)
                kills = {}
                monster = graph.get("fight_outputs", {}).get(name)
                if monster:
                    if monster not in monster_ids:
                        errors.append(f"{n['key']}.{name}: no monsters row for {monster}")
                    else:
                        exp += BASE_EXP[difficulty[monster_ids[monster]]]
                        if count_kills.get(monster, monster in EXISTING_MONSTERS):
                            kills[str(monster_ids[monster])] = 1
                if graph.get("gold_notice"):
                    gold += next((int(v) for f, v in info["facts"] if f == 175 and not str(v).startswith("+")), 0)
                outputs.append({"id": next_output, "node": node_id, "name": name,
                                "endpoint": f"{n['key']}.{name}" in q["end"], "exp": exp, "gold": gold,
                                "items": reward.get("items", {}), "kills": kills})
                next_output += 1
            for npc in graph["npcs"]:
                if f"assets/_bundledassets/characters/monsters/s00/{npc}/{npc}_settings.asset" in keys and npc not in monster_ids:
                    errors.append(f"{n['key']}: combat or scene monster {npc} has no monsters row")
        for ending in q["end"]:
            node_key, name = ending.split(".", 1)
            node_ids = [x["id"] for x in nodes if x["key"] == node_key]
            if not node_ids or not any(o["node"] in node_ids and o["name"] == name for o in outputs):
                errors.append(f"{code}: ending {ending} is not an output of its node")
        walks[str(quest_id)] = [list(step) for step in q["walk"]]

    # Conditions and walk-throughs refer to known things.
    known_outputs = {f"{x['key']}.{o['name']}" for x in nodes for o in outputs if o["node"] == x["id"]}
    for x in nodes:
        # Root criteria: fact conditions only (the client row carries the first, the server checks all).
        if x["root"] and not all(re.fullmatch(r"f\d+(<=|>=|<|>|=)-?\d+", a.strip()) for a in x["root"].split("&")):
            errors.append(f"{x['key']}: root criteria must be fact conditions joined by &")
        for expr in (x["root"], x["show"]):
            for alternative in filter(None, (a.strip() for a in expr.split("|"))):
                for atom in (a.strip() for a in alternative.split("&")):
                    match = ATOM.match(atom)
                    if not match:
                        errors.append(f"{x['key']}: condition atom '{atom}' does not parse")
                        continue
                    ref = match.group(5) or match.group(6)
                    if ref and ref not in known_outputs:
                        errors.append(f"{x['key']}: condition refers to unknown output {ref}")
    # A condition waits only on facts some graph sets (fact 100 comes from "A Joint Venture").
    set_somewhere = {100} | {f for g in graphs.values() for f, _ in g["sets"]}
    for where, expr in [(x["key"], x["root"] + "&" + x["show"]) for x in nodes] + [(q["code"], q["criteria"]) for q in quests]:
        for fact in re.findall(r"(?<![\w:])f(\d+)(?=<|>|=|!)", expr):
            if int(fact) not in set_somewhere:
                errors.append(f"{where}: condition on f{fact}, which no graph sets")
    for quest_id, steps in walks.items():
        for step in steps:
            if step[0] in ("wait", None):
                continue
            if f"{step[0]}.{step[1]}" not in known_outputs:
                errors.append(f"walk {quest_id}: {step[0]}.{step[1]} is not an output")
            # A walk-through sends only facts its graph sets: that value, or any value of a counter it changes.
            graph = graphs[next(x["graph"] for x in nodes if x["key"] == step[0])]
            sets = {(f, str(v)) for f, v in graph["sets"]}
            counters = {f for f, v in graph["sets"] if str(v)[:1] in "+-" and len(str(v)) > 1 and str(v)[0] == "+"}
            for fact, value in step[2].items():
                if (int(fact), str(value)) not in sets and int(fact) not in counters:
                    errors.append(f"walk {quest_id}: {step[0]}.{step[1]} sends f{fact}={value}, which its graph never sets")
            for key in step[3]:
                if not any(x["key"] == key for x in nodes):
                    errors.append(f"walk {quest_id}: unknown node {key}")

    if errors:
        print("\n".join(errors), file=sys.stderr)
        sys.exit(1)
    story = {"source": "season1_story.py (graphs of s01_story_common_assets_all, overlay season1_quests.py)",
             "quests": quests, "nodes": nodes, "outputs": outputs,
             "modifiers": [{"id": i, "slug": s, "seconds": MODIFIER_SECONDS.get(i)} for i, s in MODIFIERS],
             "monsters": monster_rows,
             "vulnerabilities": vulnerabilities, "walks": walks}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(story, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(quests)} quests, {len(nodes)} nodes, {len(outputs)} outputs, {len(monster_rows)} monster rows")


if __name__ == "__main__":
    main()
