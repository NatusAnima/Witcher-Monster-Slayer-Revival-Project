"""Unity AssetBundle inspector for TWMS story bundles (extracted from the OBB).

Requires: pip install UnityPy

Usage:
    python bundle_explorer.py list <bundle.bundle>
    python bundle_explorer.py search <bundle.bundle> <name-substring> [more-substrings...]
    python bundle_explorer.py graph <bundle.bundle> <NodeGraph-m_Name>

`graph` walks an XNode-based BehaviourGraph asset's `nodes` list and prints each node's name,
scalar fields (FactId, QuestEndName, _investigationSlug, etc.), and outgoing port connections —
this is how the real S00 prolog quest-chain data (QuestNodeInstanceId, node flow) was decoded,
since none of it exists in the IL2CPP dump (tools/dump/dump.cs only has code, not serialized
asset data).
"""
import sys
import UnityPy


def load_monobehaviours(path):
    env = UnityPy.load(path)
    by_pathid = {}
    for obj in env.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        try:
            by_pathid[obj.path_id] = obj.read_typetree()
        except Exception:
            pass
    return by_pathid


def cmd_list(path):
    env = UnityPy.load(path)
    counts = {}
    for obj in env.objects:
        counts[obj.type.name] = counts.get(obj.type.name, 0) + 1
    print(f"{path}: {len(env.objects)} objects, {counts}")


def cmd_search(path, needles):
    needles = [n.lower() for n in needles]
    for pathid, tree in load_monobehaviours(path).items():
        name = tree.get("m_Name", "")
        if any(n in name.lower() for n in needles):
            print(f"pathid={pathid} name={name}")
            for k, v in tree.items():
                if isinstance(v, (dict, list)):
                    print(f"    {k}: <{type(v).__name__} len={len(v)}>")
                else:
                    print(f"    {k}: {v}")
            print()


def cmd_graph(path, target_name):
    objs = load_monobehaviours(path)
    target = next((t for t in objs.values() if t.get("m_Name") == target_name and "nodes" in t), None)
    if target is None:
        print(f"Graph '{target_name}' not found (no MonoBehaviour with that m_Name and a 'nodes' field)")
        return

    print(f"=== {target_name} ===")
    print(f"QuestNodeId={target.get('QuestNodeId')} QuestNodeInstanceId={target.get('QuestNodeInstanceId')}")
    node_refs = target.get("nodes", [])
    print(f"{len(node_refs)} nodes\n")

    for i, nref in enumerate(node_refs):
        npid = nref.get("m_PathID")
        ntree = objs.get(npid)
        if ntree is None:
            print(f"[{i}] pathid={npid} <not found>")
            continue
        name = ntree.get("m_Name", "")
        ports = ntree.get("ports", {})
        conns = []
        for k, v in zip(ports.get("keys", []), ports.get("values", [])):
            for c in v.get("connections", []):
                cpid = c.get("node", {}).get("m_PathID")
                cname = objs.get(cpid, {}).get("m_Name", "?")
                conns.append(f"{k}->{cname}")
        extras = {
            k: v for k, v in ntree.items()
            if k not in ("m_GameObject", "m_Enabled", "m_Script", "m_Name", "graph", "position", "ports")
            and not isinstance(v, (dict, list))
        }
        print(f"[{i}] pathid={npid} name={name!r} extras={extras}")
        if conns:
            print(f"      -> {conns}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    cmd, bundle_path, *rest = sys.argv[1:]
    if cmd == "list":
        cmd_list(bundle_path)
    elif cmd == "search":
        cmd_search(bundle_path, rest)
    elif cmd == "graph":
        cmd_graph(bundle_path, rest[0])
    else:
        print(__doc__)
        sys.exit(1)
