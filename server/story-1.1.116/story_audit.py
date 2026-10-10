#!/usr/bin/env python3
"""Audit the season 1 story the server ships against the client's own behaviour graphs.

The shipped story (WitcherRevival.Server/Story/season1-story.json) was built from the later 1.3.102 graphs; the 1.1.116
client runs its own, which season1_graphs.py extracts from its packs. This checks, against those graphs:
  - triggers: every quest is offered, every node can show and every quest can end, by the facts the client's graphs set
    (each atom of a condition is checked on its own, so this finds conditions that can never hold, not every dead end);
  - every node the client's graphs queue is served, and every output the client sends is known;
  - every walk-through step sends only facts its graph sets;
  - every fight and scene monster has a monsters row (story, inherited or world bestiary), and a story fight's
    bestiary credit and gold match the client's fight and gold notice.
Errors stop a playthrough; warnings are mismatches the player can see or unserved side content. Exit 1 on errors.

  python season1_graphs.py --assetpacks <dir> --output season1-graphs.json      # the 1.1.116 packs
  python story_audit.py --graphs season1-graphs.json
"""
from __future__ import annotations

import argparse
import json
import operator
import re
from collections import defaultdict
from pathlib import Path

from season1_quests import QUESTS, SERVER_FACTS
from season1_story import EXISTING_MONSTERS, OUTPUT_NAMES, catalog_keys

HERE = Path(__file__).resolve().parent
STORY = HERE.parent / "WitcherRevival.Server" / "Story"
OPS = {"<=": operator.le, ">=": operator.ge, "!=": operator.ne, "<": operator.lt, ">": operator.gt, "=": operator.eq}
FACT = re.compile(r"f(\d+)(<=|>=|!=|<|>|=)(-?\d+)")
# Fact 100 comes from "A Joint Venture" (s00 graphs): the figurine sets it to 4 or 5. The server's own facts (the troll
# trigger) can hold whenever the player meets their trigger.
START = {100: {0, 4, 5}, **{f: {0, 1} for f in SERVER_FACTS}}
# Queued nodes the story leaves out on purpose (HANDOFF): the troll attack, and "Intruder 2.0" (quest 183).
UNSERVED = {474} | set(range(640, 700))
BOUND = 64   # counters are followed up to this value


def audit(graphs: dict, story: dict, world: dict, keys: set[str]) -> tuple[list[str], list[str]]:
    """The errors and warnings of the story against the client's graphs and catalog keys."""
    errors, warnings = [], []
    nodes = {n["id"]: n for n in story["nodes"]}
    by_key = {n["key"]: n for n in story["nodes"]}
    outputs = defaultdict(list)
    for o in story["outputs"]:
        outputs[o["node"]].append(o)
    graph_of = {n["id"]: graphs.get(n["graph"]) for n in story["nodes"]}
    for n in story["nodes"]:
        if graph_of[n["id"]] is None:
            errors.append(f"{n['key']}: the client has no graph {n['graph']}")
    graph_of = {k: v or {"outputs": {}, "sets": [], "queues": [], "fight_outputs": {}, "npcs": []} for k, v in graph_of.items()}

    # ── Outputs, queued nodes, walk-throughs ───────────────────────────────────────────────
    for n in story["nodes"]:
        sent = {OUTPUT_NAMES.get(name, name) for name in graph_of[n["id"]]["outputs"]}   # StoryEngine.OutputAliases
        known = {o["name"] for o in outputs[n["id"]]}
        for name in sorted(sent - known):
            errors.append(f"{n['key']}: the client sends output {name}, which the story does not know")
        for name in sorted(known - sent):
            warnings.append(f"{n['key']}: output {name} is not in the client's graph (never sent)")
    # Journal buttons are not served: the client sends their graph's own instance, or none, and then the server finds the
    # button by its output name among the started quests' buttons without one (StoryEngine.Resolve, which takes those of
    # one quest as one step), so no such button of another quest may share that name.
    blind = [n for n in story["nodes"] if n["kind"] == "button" and graph_of[n["id"]].get("instance_id", 0) in (0, -1)]
    for n in blind:
        for o in outputs[n["id"]]:
            if clash := [m["key"] for m in blind if m["quest"] != n["quest"] and any(x["name"] == o["name"] for x in outputs[m["id"]])]:
                errors.append(f"{n['key']}.{o['name']}: sent without an instance, like {', '.join(clash)} of another quest with the same output")
    for key, graph in sorted(graphs.items()):
        for queued in graph["queues"]:
            if queued not in nodes and queued not in UNSERVED:
                warnings.append(f"{key}: queues node {queued}, which the story does not serve")
    for quest, steps in story["walks"].items():
        for step in steps:
            if step[0] in ("wait", None):
                continue
            graph = graph_of[by_key[step[0]]["id"]]
            sets = {(f, str(v)) for f, v in graph["sets"]}
            counters = {f for f, v in graph["sets"] if str(v).startswith("+")}
            for fact, value in step[2].items():
                if (int(fact), str(value)) not in sets and int(fact) not in counters:
                    errors.append(f"walk {quest}: {step[0]}.{step[1]} sends f{fact}={value}, which the client's graph never sets")

    # ── Monsters, bestiary credit, gold ───────────────────────────────────────────────────
    rows = {**EXISTING_MONSTERS, **{m["slug"]: m["id"] for m in story["monsters"]},
            **{m["slug"]: m["id"] for m in world["monsters"]}}
    slug_of = {v: k for k, v in rows.items()}
    authored = {end: reward for q in QUESTS for end, reward in q["end"].items()}   # rewards of the overlay's endings
    for n in story["nodes"]:
        graph = graph_of[n["id"]]
        # Scene characters (Thorstein, the scholar) are not monsters; a fight's monster and a scene monster need a row.
        monsters = {m for m in graph["npcs"] if f"assets/_bundledassets/characters/monsters/s00/{m}/{m}_settings.asset" in keys}
        for monster in sorted(monsters | set(graph["fight_outputs"].values())):
            if monster not in rows:
                errors.append(f"{n['key']}: the client loads monster {monster}, which has no monsters row")
        for o in outputs[n["id"]]:
            fought = graph["fight_outputs"].get(o["name"])
            credited = [slug_of.get(int(m)) for m in o["kills"]]
            if fought and credited and credited != [fought] and not (fought.startswith("golem") and credited[0].startswith("golem")):
                warnings.append(f"{n['key']}.{o['name']}: the client fights {fought}, the bestiary credits {credited[0]}")
            if graph.get("gold_notice") and o["name"] in graph["outputs"]:
                notice = next((int(v) for f, v in graph["outputs"][o["name"]]["facts"] if f == 175 and not str(v).startswith("+")), 0)
                paid = o["gold"] - authored.get(f"{n['key']}.{o['name']}", {}).get("gold", 0)
                if notice != paid:
                    warnings.append(f"{n['key']}.{o['name']}: the client announces {notice} gold, the story pays {paid}")

    # ── Triggers: what can be offered, shown and finished ─────────────────────────────────
    possible = defaultdict(lambda: {0}, {f: set(v) for f, v in START.items()})
    reached, shown, started, finished = set(), set(), set(), set()

    def atom(text: str) -> bool:
        negated, text = text.startswith("!"), text.lstrip("!")
        if m := FACT.fullmatch(text):
            return any(OPS[m[2]](x, int(m[3])) != negated for x in possible[int(m[1])])
        if negated:
            return True   # not reached, started or finished yet
        kind, _, ref = text.partition(":")
        if kind in ("out", "wait"):
            key, _, name = ref.split(":")[0].partition(".")
            return any(o["id"] in reached for o in outputs[by_key[key]["id"]] if o["name"] == name)
        return int(ref) in (finished if kind == "done" else started)

    def holds(expr: str) -> bool:
        return not expr.strip() or any(all(atom(a.strip()) for a in alt.split("&")) for alt in expr.split("|"))

    criteria = {q["id"]: q["criteria"] for q in story["quests"]}
    done = {q["id"]: q.get("done", 0) for q in story["quests"]}
    changed = True
    while changed:
        changed = False
        for n in story["nodes"]:
            if n["id"] in shown:
                continue
            if n["kind"] == "giver":
                ok = holds(criteria[n["quest"]]) and holds(n["root"])
            elif n["kind"] == "queued":
                ok = holds(n["show"])
            else:
                ok = n["quest"] in started and holds(n["show"])
            if not ok:
                continue
            shown.add(n["id"]); started.add(n["quest"]); changed = True
            for o in outputs[n["id"]]:
                reached.add(o["id"])
                if o["endpoint"]:
                    finished.add(n["quest"])
                    possible[done[n["quest"]]].add(1)   # the server saves the completion fact with the ending
            for fact, value in graph_of[n["id"]]["sets"]:
                if str(value).startswith("+"):
                    step, values = int(str(value)[1:]), possible[fact]
                    while (more := {x + step for x in values if abs(x + step) <= BOUND} - values):
                        values |= more
                else:
                    possible[fact].add(int(value))
    for q in story["quests"]:
        if q["id"] not in started:
            errors.append(f"quest {q['id']} {q['name']}: never offered")
        elif q["id"] not in finished:
            errors.append(f"quest {q['id']} {q['name']}: can never end")
    for n in story["nodes"]:
        if n["id"] not in shown:
            errors.append(f"{n['key']} ({n['kind']}): never shows: {n['root'] or n['show']}")
    return errors, warnings


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--graphs", type=Path, required=True, help="season1_graphs.py output for the 1.1.116 packs")
    parser.add_argument("--catalog", type=Path, required=True, help="the client's assets/aa/catalog.json")
    parser.add_argument("--story", type=Path, default=STORY / "season1-story.json")
    parser.add_argument("--world", type=Path, default=STORY / "world-bestiary.json")
    args = parser.parse_args()
    story = json.loads(args.story.read_text(encoding="utf-8"))
    errors, warnings = audit(json.loads(args.graphs.read_text(encoding="utf-8"))["graphs"], story,
                             json.loads(args.world.read_text(encoding="utf-8")), catalog_keys(args.catalog))
    for line in warnings:
        print("warning:", line)
    for line in errors:
        print("ERROR:", line)
    print(f"{len(story['quests'])} quests, {len(story['nodes'])} nodes: {len(errors)} errors, {len(warnings)} warnings")
    raise SystemExit(1 if errors else 0)


if __name__ == "__main__":
    main()
