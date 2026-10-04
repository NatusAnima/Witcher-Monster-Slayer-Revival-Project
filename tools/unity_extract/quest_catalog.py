"""Catalog every story BehaviourGraph (Phase 2) -> tools/data_sources/quest_catalog.json.

One pass over the extracted story-graph bundles (run `bundle_explorer.py extract story_ dialogs_ journal_glossary`
first). Per graph it records what the server's quest flow needs and what the graph will look up:
  - asset path / chapter, baked QuestNodeInstanceId, tracked quest ids (Set Tracked Quest), Quest End Request outputs
  - facts set (incl. journal steps = fact 10000 + quest id) and fact requirements
  - Queue Story Graph targets (these are the ORIGINAL server QuestNodeIds, e.g. 231 = tutorial node)
  - sub-graphs run (GraphRunnerNode), journal logs / notifications, expiring effects, quest item interactions
  - data-input seeds (MonsterSlug, PresentationData, item ids, ...) for the static-data coverage check

  python tools/unity_extract/quest_catalog.py [--check]
--check also compares every monster seed with server/.../StaticData/static_data.json and lists what's missing.
"""
import collections, glob, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
from bundle_explorer import load_monobehaviours

BUNDLES = os.path.join(ROOT, "tools", "apk_extracted", "bundles")
OUT = os.path.join(ROOT, "tools", "data_sources", "quest_catalog.json")
STATIC = os.path.join(ROOT, "server", "WitcherRevival.Server", "StaticData", "static_data.json")


def asset_paths():
    keys = json.load(open(os.path.join(ROOT, "tools", "dump", "catalog.json"), encoding="utf-8")).get("m_InternalIds", [])
    paths = {}
    for k in keys:
        m = re.search(r"story/(bgraphs|injectable_graphs)/(.+)\.asset$", k, re.I) if isinstance(k, str) else None
        if m: paths.setdefault(m.group(2).rsplit("/", 1)[-1].lower(), m.group(2))
    return paths


def catalog_graph(g, objs):
    info = collections.defaultdict(list)
    names = collections.Counter()
    for ref in g["nodes"]:
        n = objs.get(ref["m_PathID"], {})
        name = n.get("m_Name", "")
        names[re.sub(r"\d+$", "", name)] += 1
        if name.startswith("Set Tracked Quest"): info["tracked_quests"].append(n.get("QuestId"))
        elif name.startswith("Quest End Request"): info["outputs"].append(n.get("QuestEndName"))
        elif "Set Fact" in name and "FactId" in n:
            info["facts_set"].append([n["FactId"], n.get("Value"), name.startswith("Immediately")])
        elif "FactRequirement" in n:
            fr = n["FactRequirement"]; info["fact_requirements"].append([fr.get("FactId"), fr.get("Operator"), fr.get("Value")])
        elif name.startswith("Modify Fact"): info["facts_modified"].append([n.get("FactId"), n.get("operation"), n.get("value")])
        elif name.startswith("Queue Story Graph"): info["queue_quest_nodes"].append(n.get("QuestNodeId"))
        elif name.startswith("Add Expiring Effect"): info["expiring_effects"].append([n.get("_effectID"), n.get("_time")])
        elif name.startswith("Show Custom Notification"): info["notifications"].append([n.get("Message"), n.get("QuestLog")])
        elif name.startswith("Show Journal Notification"): info["journal"].append([n.get("_logSlug"), n.get("_itemId"), n.get("_interactionSlug")])
        if "GraphToRun" in n: info["runs"].append(n["GraphToRun"].get("m_PathID"))
        for inter in n.get("Interactions", []) or []:
            info["quest_item_graphs"].append(inter.get("InteractionGraph"))
        seed = (n.get("_dataCache") or {}).get("_seedData") or []
        if len(seed) >= 3 and seed[1]: info["seeds:" + seed[2]].append(seed[1])
    out = {k: sorted(set(map(str, v))) if k.startswith("seeds:") else v for k, v in info.items()}
    out["node_counts"] = dict(names.most_common(12))
    return out


def main(check):
    paths = asset_paths()
    catalog = collections.OrderedDict()
    for bundle in sorted(glob.glob(os.path.join(BUNDLES, "*graphs_assets_all.bundle"))):
        objs = load_monobehaviours(bundle)
        graph_names = {pid: t["m_Name"] for pid, t in objs.items() if "nodes" in t}
        for pid, t in sorted(objs.items(), key=lambda kv: str(kv[1].get("m_Name"))):
            if "nodes" not in t: continue
            entry = collections.OrderedDict(bundle=os.path.basename(bundle), path=paths.get(t["m_Name"].lower()),
                                            instance_id=t.get("QuestNodeInstanceId"), nodes=len(t["nodes"]))
            entry.update(catalog_graph(t, objs))
            if "runs" in entry:  # same-bundle sub-graphs by name; other bundles stay as path ids
                entry["runs"] = sorted({graph_names.get(int(p), p) for p in entry["runs"]}, key=str)
            catalog[t["m_Name"]] = entry
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(catalog, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    quest_nodes = [n for n, e in catalog.items() if e.get("outputs")]
    print(f"{len(catalog)} graphs, {len(quest_nodes)} with Quest End Request outputs -> {OUT}")
    if check:
        static = json.load(open(STATIC, encoding="utf-8"))
        have = {m["slug"] for m in static["monsters"]}
        need = collections.defaultdict(set)
        for name, e in catalog.items():
            for key in ("seeds:MonsterSlug", "seeds:PresentationData"):
                for slug in e.get(key, []):
                    if slug not in have: need[slug].add(name)
        print(f"missing monster/presentation slugs ({len(need)}):")
        for slug, graphs in sorted(need.items()):
            print(f"  {slug}: {', '.join(sorted(graphs)[:4])}{' ...' if len(graphs) > 4 else ''}")


if __name__ == "__main__":
    main("--check" in sys.argv)
