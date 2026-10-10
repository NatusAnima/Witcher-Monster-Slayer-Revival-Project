#!/usr/bin/env python3
"""Extract the season 1 behaviour graphs of the client into structured data for the story engine.

For every graph of `s01_story_common_assets_all` (the client's asset pack; the server's story uses 1.1.116) this lists the quest node id
and instance id the graph carries, the quests it tracks, the quest nodes it queues, the player modifiers it adds or
removes, and every graph output (QuestEndRequestNode, sent as EndBehaviourGraph 57) with:
  - the facts set in the same step as the output and on the way to it,
  - the monsters of the fights won on the way to it (the fight graph's MonsterInstance input),
  - whether it follows a lost fight.
The monsters, quest items and journal logs referred to are listed too, so their static-data rows can be checked.

  python season1_graphs.py --assetpacks <play export>/assetpacks --output season1-graphs.json
  python season1_graphs.py --assetpacks ~/witcher_1.1.116_packs --output season1-graphs.json   # extract_packs.py output
"""
from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path

import UnityPy

SKIP = {"DataInputNode", "NoteNode", "GameAnalyticsProgressionNode"}
CONDITIONS = {"FactRequirementNode", "AndNode", "OrNode", "NotNode", "AstroConditionNode", "MathConditionNode"}
OPERATORS = {0: "==", 1: "!=", 2: ">", 3: ">=", 4: "<", 5: "<="}


class Bundle:
    def __init__(self, path: str):
        env = UnityPy.load(path)
        scripts = {o.path_id: o.read_typetree().get("m_ClassName", "?") for o in env.objects if o.type.name == "MonoScript"}
        self.objects: dict[int, tuple[str, dict]] = {}
        for o in env.objects:
            if o.type.name != "MonoBehaviour":
                continue
            try:
                tree = o.read_typetree()
            except Exception:
                continue
            self.objects[o.path_id] = (scripts.get(tree.get("m_Script", {}).get("m_PathID"), "?"), tree)
        self.assets: dict[str, int] = {}
        for path_name, obj in env.container.items():
            if obj.path_id in self.objects:
                name = path_name.lower()
                # A graph asset's container entry also lists its nodes; keep the object named like the asset.
                if name not in self.assets or self.objects[obj.path_id][1].get("m_Name", "").lower() == Path(name).stem:
                    self.assets[name] = obj.path_id


def ports(tree: dict) -> dict:
    p = tree.get("ports", {})
    return dict(zip(p.get("keys", []), p.get("values", [])))


def targets(tree: dict, port: str) -> list[int]:
    return [c["node"]["m_PathID"] for c in (ports(tree).get(port) or {}).get("connections", [])]


class Graph:
    def __init__(self, bundle: Bundle, pid: int):
        self.b = bundle
        self.tree = bundle.objects[pid][1]

    def node(self, pid: int) -> tuple[str, dict]:
        return self.b.objects.get(pid, ("?", {}))

    def seed(self, pid: int):
        cls, tree = self.node(pid)
        data = tree.get("_dataCache", {}).get("_seedData")
        if cls == "DataInputNode" and data and len(data) > 1:
            return data[1]
        return None

    def inputs(self, tree: dict) -> dict:
        values = {}
        for name, port in ports(tree).items():
            if port.get("_direction") == 0 and name.endswith("Input"):
                for src in targets(tree, name):
                    value = self.seed(src)
                    if value not in (None, ""):
                        values[name[:-5]] = value
        return values

    def condition(self, pid: int) -> str:
        cls, tree = self.node(pid)
        if cls == "FactRequirementNode":
            req = tree.get("FactRequirement", {})
            return f"f{req.get('FactId')}{OPERATORS.get(req.get('Operator'), '?')}{req.get('Value')}"
        if cls in ("AndNode", "OrNode"):
            parts = [self.condition(src) for name, port in ports(tree).items() if port.get("_direction") == 0
                     for src in targets(tree, name)]
            return "(" + (" & " if cls == "AndNode" else " | ").join(parts) + ")"
        if cls == "NotNode":
            return "!" + "".join(self.condition(src) for name, port in ports(tree).items() if port.get("_direction") == 0
                                 for src in targets(tree, name))
        if cls == "AstroConditionNode":
            return f"astro({tree.get('condition')})"
        return cls

    def walk(self) -> dict:
        """Backward analysis from every QuestEndRequestNode over the execution edges (no path state, so it stays
        linear): the facts set in the same step and in the linear chain before it, the monster of the nearest fight
        won before it, and whether a lost fight leads to it."""
        nodes = [n["m_PathID"] for n in self.tree.get("nodes", [])]
        forward: dict[int, list[tuple[str, int]]] = {}
        backward: dict[int, list[tuple[int, str]]] = {}
        for pid in nodes:
            cls, tree = self.node(pid)
            for port_name, port in ports(tree).items():
                if port.get("_direction") != 1:
                    continue
                for target in targets(tree, port_name):
                    if self.node(target)[0] in SKIP | CONDITIONS:
                        continue
                    forward.setdefault(pid, []).append((port_name, target))
                    backward.setdefault(target, []).append((pid, port_name))
        info = {"tracks": set(), "queues": set(), "modifiers_added": set(), "modifiers_removed": set(),
                "fights": set(), "investigations": set(), "npcs": set(), "notifications": set(), "cutscenes": set(),
                "nest_ui": None}
        fight_of: dict[int, str] = {}
        for pid in nodes:
            cls, tree = self.node(pid)
            inputs = self.inputs(tree)
            if cls == "SetTrackedQuestNode":
                info["tracks"].add(tree.get("QuestId"))
            elif cls == "QueueStoryGraphNode":
                info["queues"].add(tree.get("QuestNodeId"))
            elif cls == "AddExpiringEffect":
                info["modifiers_added"].add((tree.get("_effectID"), tree.get("_time")))
            elif cls == "RemoveExpiringEffect":
                info["modifiers_removed"].add(tree.get("_effectID"))
            elif cls == "InvestigationNode":
                info["investigations"].add(tree.get("_investigationSlug"))
            elif cls == "ShowCustomNotificationNode":
                info["notifications"].add(tree.get("Message"))
            elif cls == "NestUI":
                info["nest_ui"] = {"gold": tree.get("Gold"), "exp": tree.get("Exp")}
            if cls in ("LoadEnviroNode", "CombatPreparationNode") and isinstance(inputs.get("MonsterInstance"), str):
                info["npcs"].add(inputs["MonsterInstance"])
            if cls == "GraphRunnerNode" and inputs.get("CutsceneSettings"):
                info["cutscenes"].add(inputs["CutsceneSettings"])
            if cls == "GraphRunnerNode" and "EnemyMaxHp" in inputs and isinstance(inputs.get("MonsterInstance"), str):
                fight_of[pid] = inputs["MonsterInstance"]
                info["fights"].add((inputs["MonsterInstance"], inputs.get("EnemyMaxHp"), inputs.get("EnemyDamage")))

        def fact_of(pid: int):
            cls, tree = self.node(pid)
            if cls in ("SetFactNode", "ImmediatelySetFactNode"):
                return (tree.get("FactId"), tree.get("Value"))
            if cls == "ModifyFact":
                return (tree.get("FactId"), f"+{tree.get('value')}")
            return None

        def step_facts(pid: int) -> set:
            """Facts set with a node: its siblings on the same parent port and the linear chain above it."""
            found, frontier, seen = set(), [pid], set()
            for _ in range(8):
                nxt = []
                for node in frontier:
                    if node in seen:
                        continue
                    seen.add(node)
                    if fact_of(node):
                        found.add(fact_of(node))
                    for parent, port_name in backward.get(node, []):
                        for sibling_port, sibling in forward.get(parent, []):
                            if sibling_port == port_name and fact_of(sibling):
                                found.add(fact_of(sibling))
                        pcls = self.node(parent)[0]
                        if pcls not in ("BranchingNode", "StartGraphNode") and parent not in fight_of:
                            nxt.append(parent)
                frontier = nxt
            return found

        def fights_before(pid: int) -> tuple[set, bool]:
            wins, lost, seen, frontier = set(), False, set(), [pid]
            while frontier:
                node = frontier.pop()
                if node in seen:
                    continue
                seen.add(node)
                for parent, port_name in backward.get(node, []):
                    if parent in fight_of:
                        if port_name == "End By Win":
                            wins.add(fight_of[parent])
                        elif port_name == "End By Lose":
                            lost = True
                        continue
                    frontier.append(parent)
            return wins, lost

        # The first graph output after each won fight: the output that carries the fight (reward and kill).
        fight_outputs: dict[str, str] = {}
        for pid, monster in fight_of.items():
            frontier = [t for port_name, t in forward.get(pid, []) if port_name == "End By Win"]
            seen, found = set(), None
            while frontier and found is None:
                nxt = []
                for node in frontier:
                    if node in seen:
                        continue
                    seen.add(node)
                    ncls, ntree = self.node(node)
                    if ncls == "QuestEndRequestNode":
                        found = ntree.get("QuestEndName", "")
                        break
                    if node not in fight_of:
                        nxt.extend(t for _, t in forward.get(node, []))
                frontier = nxt
            if found is not None:
                fight_outputs[found] = monster
        info["fight_outputs"] = fight_outputs
        info["sets"] = sorted({fact_of(pid) for pid in nodes if fact_of(pid)}, key=lambda x: (x[0], str(x[1])))
        gold_notice = any(self.node(pid)[0] == "ShowCustomNotificationNode" and
                          self.node(pid)[1].get("Message") == "NOTIFICATIONS/REWARD_GOLD_COINS" for pid in nodes)
        info["gold_notice"] = gold_notice

        outputs: dict[str, dict] = {}
        for pid in nodes:
            cls, tree = self.node(pid)
            if cls != "QuestEndRequestNode":
                continue
            entry = outputs.setdefault(tree.get("QuestEndName", ""), {"facts": set(), "wins": set(), "after_loss": False})
            entry["facts"] |= step_facts(pid)
            wins, lost = fights_before(pid)
            entry["wins"] |= wins
            entry["after_loss"] |= lost and not wins
        result = {name: {"facts": sorted(e["facts"], key=lambda x: (x[0], str(x[1]))), "wins": sorted(e["wins"]),
                         "after_loss": e["after_loss"]} for name, e in outputs.items()}
        return {"outputs": result, **{k: sorted(v) if isinstance(v, set) else v for k, v in info.items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--assetpacks", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    name = "s01_story_common_assets_all"
    bundle = Bundle((glob.glob(str(args.assetpacks / name / "*/*/assets/assetpack" / name)) or [str(args.assetpacks / name)])[0])
    graphs = {}
    for asset, pid in sorted(bundle.assets.items()):
        if "/bgraphs/s01/" not in asset or bundle.objects[pid][0] != "BehaviourGraph":
            continue
        key = asset.split("/bgraphs/")[1][:-len(".asset")]
        tree = bundle.objects[pid][1]
        graphs[key] = {"quest_node_id": tree.get("QuestNodeId", 0), "instance_id": tree.get("QuestNodeInstanceId", 0),
                       **Graph(bundle, pid).walk()}
    # Quest node settings (POI settings) of season 1: the prefab each one shows.
    settings = {}
    for asset, pid in sorted(bundle.assets.items()):
        if "/poi_settings/s01/" in asset:
            tree = bundle.objects[pid][1]
            refs = {k: v for k, v in tree.items() if isinstance(v, str) and v and k != "m_Name"}
            settings[asset] = {"class": bundle.objects[pid][0], **refs}
    args.output.write_text(json.dumps({"graphs": graphs, "poi_settings": settings}, indent=1, ensure_ascii=False,
                                      default=list) + "\n")
    print(len(graphs), "graphs", len(settings), "poi settings")


if __name__ == "__main__":
    main()
