"""List every direct call site (ARM64 BL/B) into the given libil2cpp.so RVAs, named via script.json.

Static xrefs without waiting hours for Ghidra auto-analysis. Misses virtual/interface calls (vtable
dispatch), which never appear as BL targets.

  python tools/il2cpp_callers.py 0x3194F8C 0x19585B8
"""
import bisect, json, os, sys
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
d = json.load(open(os.path.join(ROOT, "tools", "dump", "script.json"), encoding="utf-8"))
meths = sorted((m["Address"], m["Name"]) for m in d["ScriptMethod"])
addrs = [a for a, _ in meths]
code = np.fromfile(os.path.join(ROOT, "tools", "apk_extracted", "lib", "arm64-v8a", "libil2cpp.so"), dtype="<u4")
pc = np.arange(len(code), dtype=np.int64) * 4  # file offset == RVA for this .so
op = code & 0xFC000000
branch = (op == 0x94000000) | (op == 0x14000000)  # BL, B (tail call)
imm = (code & 0x03FFFFFF).astype(np.int64)
imm[imm >= 1 << 25] -= 1 << 26
dest = pc + imm * 4
for t in (int(a, 16) for a in sys.argv[1:]):
    print("callers of", hex(t))
    for p in pc[branch & (dest == t)]:
        i = bisect.bisect_right(addrs, int(p)) - 1
        print(f"  {hex(int(p))} in {meths[i][1]} (+{hex(int(p) - meths[i][0])})")
