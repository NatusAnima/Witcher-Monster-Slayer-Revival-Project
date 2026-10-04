#!/usr/bin/env python3
"""Describe a quest end to end from the client's own data, before the server reconstructs it.

For each quest group the atlas lists every behaviour graph (entry conditions, fights, dialogs with their
Polish and English lines, investigations, facts set, quest-end outputs, queued nodes, tracked quest,
notifications), the journal log (entries and the facts that reveal them), the quest items and their
buttons, and a fact table: where each fact is set and where it is tested.

Sources: story graphs, dialogs and journal assets from the 1.3.102 asset packs that LAB loads, and the
localisation (I2Languages) of the 1.1.116 APK. Requires UnityPy (analysis venv).

  python quest_atlas.py --assetpacks <local-play-export-1.3.102.../assetpacks> \
      --apk-data <unzipped APK>/assets/bin/Data --output quests/
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
from pathlib import Path
import struct

import UnityPy

# Client: WitcherWorld.Utils.Comparison.Operator.
OPERATORS = {0: "==", 1: "!=", 2: ">", 3: ">=", 4: "<", 5: "<="}

GROUPS = {
    "tutorial": {"graphs": ("s00/tutorial/",), "logs": ("s00/tutorial/log_tutorial",)},
    "prolog_01": {"graphs": ("s00/prolog/prolog_01_",), "logs": ("s00/prolog/log_prolog_01",)},
    "prolog_02": {"graphs": ("s00/prolog/prolog_02_", "s00/prolog/quest_item_buttons/"),
                  "logs": ("s00/prolog/log_prolog_02",)},
}

# Season 1: graphs, dialogs and journals are all in s01_story_common_assets_all. Each quest folder also lists
# the quest item buttons its journal refers to.
SEASON1 = {
    "s01hq01": "s01hq01_sword_in_stone", "s01hq02": "s01hq02_nests", "s01hq03": "s01hq03_blacksmith",
    "s01hq04": "s01hq04_firefly", "s01hq05": "s01hq05_bandit_and_devourer", "s01hq06": "s01hq06_trolling",
    "s01mq01": "s01mq01_scholar", "s01mq02": "s01mq02_cure", "s01mq03": "s01mq03_striga",
    "s01mq04": "s01mq04_cursed_one", "s01mq05": "s01mq05_mushroom_hunt", "s01mq06": "s01mq06_frightener",
}
for _quest, _folder in SEASON1.items():
    GROUPS[_quest] = {"season": "s01", "graphs": (f"s01/{_folder}/",), "logs": (f"s01/{_folder}/log_{_quest}",)}
GROUPS["s01mq06.2"] = {"season": "s01", "graphs": ("s01/s01mq06_2.0/",), "logs": ("s01/s01mq06.2/log_s01mq06.2",)}
GROUPS["s01_buttons"] = {"season": "s01", "graphs": ("s01/quest_item_buttons/",), "logs": ()}
SKIP_NODES = {"DataInputNode", "DataOutputNode", "GameAnalyticsProgressionNode", "FactRequirementNode",
              "AndNode", "OrNode", "NotNode", "NoteNode"}


class Localization:
    """Reads terms from the 1.1.116 I2Languages asset (no type tree: strings are parsed directly)."""

    def __init__(self, data_dir: Path):
        self.data = b""
        for path in sorted(data_dir.iterdir()):
            if path.is_file() and path.stat().st_size > 1_000_000:
                blob = path.read_bytes()
                if b"I2Languages" in blob and b"DIALOGS/S00/" in blob:
                    self.data = blob
                    break
        self.cache: dict[str, tuple[str, str]] = {}

    def _string(self, pos: int) -> tuple[str, int]:
        length = struct.unpack_from("<i", self.data, pos)[0]
        if not 0 <= length <= 20000:
            raise ValueError
        text = self.data[pos + 4:pos + 4 + length].decode("utf-8")
        return text, (pos + 4 + length + 3) & ~3

    def text(self, term: str) -> tuple[str, str]:
        """(Polish, English) of a term, or ('', '') when missing."""
        if not term or term in self.cache:
            return self.cache.get(term, ("", ""))
        key = term.encode()
        pos = self.data.find(struct.pack("<i", len(key)) + key)
        result = ("", "")
        if pos >= 0:
            try:
                _, p = self._string(pos)
                p += 4  # term type
                for _ in range(3):
                    count = struct.unpack_from("<i", self.data, p)[0]
                    if 5 <= count <= 40:
                        languages, q = [], p + 4
                        for _ in range(count):
                            value, q = self._string(q)
                            languages.append(value)
                        result = (languages[1], languages[0])
                        break
                    _, p = self._string(p)
            except (ValueError, struct.error, UnicodeDecodeError):
                pass
        self.cache[term] = result
        return result


class Bundle:
    def __init__(self, path: str):
        env = UnityPy.load(path)
        scripts = {o.path_id: o.read_typetree().get("m_ClassName", "?") for o in env.objects
                   if o.type.name == "MonoScript"}
        self.objects: dict[int, tuple[str, dict]] = {}
        for o in env.objects:
            if o.type.name != "MonoBehaviour":
                continue
            try:
                tree = o.read_typetree()
            except Exception:
                continue
            cls = scripts.get(tree.get("m_Script", {}).get("m_PathID"))
            if cls is None:
                try:
                    cls = o.read().m_Script.read().m_ClassName
                except Exception:
                    cls = "?"
            self.objects[o.path_id] = (cls, tree)
        self.assets: dict[str, int] = {}
        for path_name, obj in env.container.items():
            if obj.path_id in self.objects:
                name = path_name.lower()
                cls, tree = self.objects[obj.path_id]
                if name not in self.assets or tree.get("m_Name", "").lower() == Path(name).stem:
                    self.assets[name] = obj.path_id


def ports(tree: dict) -> dict:
    p = tree.get("ports", {})
    return dict(zip(p.get("keys", []), p.get("values", [])))


def targets(tree: dict, port: str) -> list[int]:
    value = ports(tree).get(port) or {}
    return [c["node"]["m_PathID"] for c in value.get("connections", [])]


class GraphReader:
    def __init__(self, bundle: Bundle, loc: Localization, facts: dict, dialogs: "GraphReader | None" = None):
        self.b, self.loc, self.facts, self.dialogs = bundle, loc, facts, dialogs

    def node(self, pid: int) -> tuple[str, dict]:
        return self.b.objects.get(pid, ("?", {}))

    def seed(self, pid: int):
        cls, tree = self.node(pid)
        data = tree.get("_dataCache", {}).get("_seedData")
        if cls == "DataInputNode" and tree.get("_specifyValue") and data and len(data) > 1:
            return data[1]
        return None

    def inputs(self, tree: dict) -> dict:
        values = {}
        for name, port in ports(tree).items():
            if port.get("_direction") == 0 and name.endswith("Input"):
                for src in targets(tree, name):
                    value = self.seed(src)
                    if value not in (None, "", 0) and name not in ("UseServerCommunicationInput",):
                        values[name[:-5]] = value
        return values

    def condition(self, pid: int, graph: str) -> str:
        cls, tree = self.node(pid)
        if cls == "FactRequirementNode":
            req = tree.get("FactRequirement", {})
            fact, op, value = req.get("FactId"), OPERATORS.get(req.get("Operator"), "?"), req.get("Value")
            self.facts[fact]["tested"].add(f"{graph}: {op} {value}")
            return f"fact {fact} {op} {value}"
        if cls in ("AndNode", "OrNode"):
            parts = [self.condition(src, graph) for name in ports(tree) if ports(tree)[name].get("_direction") == 0
                     for src in targets(tree, name)]
            return "(" + (" AND " if cls == "AndNode" else " OR ").join(parts) + ")"
        if cls == "NotNode":
            return "NOT " + " ".join(self.condition(src, graph) for name in ports(tree) for src in targets(tree, name)
                                     if ports(tree)[name].get("_direction") == 0)
        return cls

    def describe(self, pid: int, graph: str) -> str:
        cls, tree = self.node(pid)
        name = tree.get("m_Name", "")
        if cls == "BranchingNode":
            return "IF " + " ".join(self.condition(s, graph) for s in targets(tree, "Condition"))
        if cls in ("SetFactNode", "ImmediatelySetFactNode"):
            self.facts[tree.get("FactId")]["set"].add(f"{graph}: {tree.get('Value')}")
            return f"SET fact {tree.get('FactId')} = {tree.get('Value')}" + (" (immediately)" if cls.startswith("Imm") else "")
        if cls == "QuestEndRequestNode":
            return f"QUEST END '{tree.get('QuestEndName')}'  -> server EndBehaviourGraph (57)"
        if cls == "QueueStoryGraphNode":
            return f"QUEUE quest node {tree.get('QuestNodeId')} (started when this graph ends)"
        if cls == "SetTrackedQuestNode":
            return f"TRACK quest {tree.get('QuestId')}"
        if cls == "ShowCustomNotificationNode":
            pl, _ = self.loc.text(tree.get("Message", ""))
            return f"NOTIFY {tree.get('Message')} \"{pl}\" (log {tree.get('QuestLog')})"
        if cls == "ShowJournalNotificationNode":
            return f"JOURNAL NOTICE log {tree.get('_logSlug')} item {tree.get('_itemId')} {tree.get('_interactionSlug')}"
        if cls == "CombatPreparationNode":
            flags = {k: tree[k] for k in ("RequireOil", "RequireBomb", "RequirePotion", "SendStandardServerRequest") if k in tree}
            return f"COMBAT PREPARATION {self.inputs(tree)} {flags}"
        if cls == "GraphRunnerNode":
            return f"RUN {name} {self.inputs(tree)}"
        extra = {k: v for k, v in tree.items() if isinstance(v, (int, float, str)) and k not in
                 ("m_Name", "m_Enabled", "m_EditorHideFlags", "m_EditorClassIdentifier") and v not in ("", 0)}
        return f"{cls}('{name}') {self.inputs(tree)} {extra if extra else ''}".rstrip()

    def outline(self, graph_pid: int, graph: str) -> list[str]:
        lines, seen = [], set()
        start = [n["m_PathID"] for n in self.b.objects[graph_pid][1].get("nodes", [])
                 if self.node(n["m_PathID"])[0] == "StartGraphNode"]

        def walk(pid: int, depth: int, label: str):
            indent = "  " * min(depth, 30)
            cls, tree = self.node(pid)
            if pid in seen:
                lines.append(f"{indent}{label}-> (see above) {self.describe(pid, graph)}")
                return
            seen.add(pid)
            lines.append(f"{indent}{label}{self.describe(pid, graph)}")
            if cls == "GraphRunnerNode" and self.dialogs is not None:
                dialog = self.inputs(tree).get("DialogGraph")
                if dialog:
                    for line in self.dialogs.dialog_lines(dialog):
                        lines.append(f"{indent}    | {line}")
            for port_name, port in ports(tree).items():
                if port.get("_direction") != 1:
                    continue
                for target in targets(tree, port_name):
                    if self.node(target)[0] not in SKIP_NODES:
                        walk(target, depth + 1, f"[{port_name}] ")

        for pid in start:
            walk(pid, 0, "")
        return lines

    def dialog_lines(self, asset: str) -> list[str]:
        pid = self.b.assets.get(asset.lower())
        if pid is None:
            return [f"(dialog {asset} not found)"]
        graph = Path(asset).stem
        out = []
        for ref in self.b.objects[pid][1].get("nodes", []):
            cls, tree = self.node(ref["m_PathID"])
            if cls == "DialogNode":
                for message in tree.get("MessageComponents", []):
                    pl, en = self.loc.text(message.get("MessageLocalizationTerm", ""))
                    out.append(f"NPC: {pl}  /  {en}")
                for response in tree.get("Responses", []):
                    for part in response.get("StatementComponents", []):
                        pl, en = self.loc.text(part.get("MessageLocalizationTerm", ""))
                        out.append(f"  Geralt: {pl}  /  {en}")
            elif cls == "BranchingNode":
                out.append("IF " + " ".join(self.condition(s, graph) for s in targets(tree, "Condition")))
        return out


def journal(bundle: Bundle, loc: Localization, facts: dict, log: str) -> list[str]:
    pid = bundle.assets.get(f"assets/_bundledassets/story/journal/{log}.asset")
    if pid is None:
        return [f"(log {log} not found)"]
    tree = bundle.objects[pid][1]
    title = loc.text(tree.get("Name", {}).get("DefaultValue", ""))[0]
    lines = [f"Title: {title}"]
    for entry in tree.get("Entries", []):
        fact = entry.get("Fact", {})
        cond = f"fact {fact.get('FactID')} {OPERATORS.get(fact.get('FactOperator'), '?')} {fact.get('FactValue')}"
        facts[fact.get("FactID")]["tested"].add(f"journal {log}: {cond.split(' ', 2)[2]}")
        kind = "cutscene" if entry.get("Type") == 1 else "text"
        lines.append(f"- [{cond}] {kind}: {loc.text(entry.get('Text', ''))[0][:300]}")
    for item in tree.get("QuestItems", []):
        fact = item.get("Fact", {})
        cond = f"fact {fact.get('FactID')} {OPERATORS.get(fact.get('FactOperator'), '?')} {fact.get('FactValue')}"
        facts[fact.get("FactID")]["tested"].add(f"quest item {item.get('Id')}: {cond.split(' ', 2)[2]}")
        lines.append(f"- quest item {item.get('Id')} [{cond}] window {item.get('InteractionGraph')}")
        window = bundle.assets.get(str(item.get("InteractionGraph", "")).lower())
        for ref in (bundle.objects[window][1].get("nodes", []) if window in bundle.objects else []):
            cls, node = bundle.objects.get(ref["m_PathID"], ("?", {}))
            if cls == "QuestItemDataNode":
                lines.append(f"    name: {loc.text(node.get('Name', ''))[0]}; text: {loc.text(node.get('LongText', ''))[0][:300]}")
                for act in node.get("Interactions", []):
                    op = OPERATORS.get(act.get("FactOperator"), "?")
                    facts[act.get("RequiredFactID")]["tested"].add(f"button {Path(act.get('InteractionGraph', '')).stem}: {op} {act.get('RequiredFactValue')}")
                    lines.append(f"    button \"{loc.text(act.get('ButtonText', ''))[0]}\" when fact {act.get('RequiredFactID')} {op} "
                                 f"{act.get('RequiredFactValue')} -> {act.get('InteractionGraph')} (quest node {act.get('QuestNodeId')})")
    return lines


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--assetpacks", type=Path, required=True)
    parser.add_argument("--apk-data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--groups", nargs="*", default=list(GROUPS))
    args = parser.parse_args()
    pack = lambda name: glob.glob(str(args.assetpacks / name / "*/*/assets/assetpack" / name))[0]
    loc = Localization(args.apk_data)
    bundles: dict[str, Bundle] = {}

    def bundle(name: str) -> Bundle:
        if name not in bundles:
            bundles[name] = Bundle(pack(name))
        return bundles[name]

    args.output.mkdir(parents=True, exist_ok=True)
    for group in args.groups:
        if GROUPS[group].get("season") == "s01":
            graphs = dialogs = journal_bundle = bundle("s01_story_common_assets_all")
        else:
            graphs, dialogs, journal_bundle = (bundle(n) for n in ("s00_story_graphs_assets_all",
                                               "s00_story_dialogs_assets_all", "s00_story_journal_glossary_assets_all"))
        facts = collections.defaultdict(lambda: {"set": set(), "tested": set()})
        dialog_reader = GraphReader(dialogs, loc, facts)
        reader = GraphReader(graphs, loc, facts, dialog_reader)
        out = [f"# Quest atlas: {group}", "",
               "Generated by quest_atlas.py from the client data (graphs, dialogs and journal: 1.3.102 asset packs "
               "loaded by LAB; text: 1.1.116 localisation). Operators: == != > >= < <=.", ""]
        for prefix in GROUPS[group]["graphs"]:
            for asset, pid in sorted(graphs.assets.items()):
                if f"/bgraphs/{prefix}" not in asset or graphs.objects[pid][0] != "BehaviourGraph":
                    continue
                tree = graphs.objects[pid][1]
                name = asset.split("/bgraphs/")[1][:-6]
                out += [f"## Graph `{name}`", "",
                        f"QuestNodeId {tree.get('QuestNodeId')}, QuestNodeInstanceId {tree.get('QuestNodeInstanceId')}", "",
                        "```", *reader.outline(pid, name), "```", ""]
        for log in GROUPS[group]["logs"]:
            out += [f"## Journal `{log}`", "", *journal(journal_bundle, loc, facts, log), ""]
        out += ["## Facts", "", "| Fact | Set by | Tested by |", "| --- | --- | --- |"]
        for fact in sorted(k for k in facts if k is not None):
            out.append(f"| {fact} | {'; '.join(sorted(facts[fact]['set']))} | {'; '.join(sorted(facts[fact]['tested']))} |")
        (args.output / f"{group}.md").write_text("\n".join(out) + "\n")
        print(group, len(out), "lines")


if __name__ == "__main__":
    main()
