"""Decompile libil2cpp.so functions by RVA (the addresses in dump.cs / hook.js) with Ghidra.

First run imports the .so into tools/ghidra-dist/proj (no auto-analysis, which takes hours on 75 MB) and labels
every method, TypeInfo/MethodInfo pointer and string literal from Il2CppDumper's script.json, so the
decompiled C shows real names (strings as str_<text>). Later runs reuse the saved project.

  python tools/ghidra_decomp.py 0x1958370 0x1958498
"""
import glob, json, os, sys
import pyghidra

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SO = os.path.join(ROOT, "tools", "apk_extracted", "lib", "arm64-v8a", "libil2cpp.so")
SCRIPT = os.path.join(ROOT, "tools", "dump", "script.json")
PROJ = os.path.join(ROOT, "tools", "ghidra-dist", "proj")
LABELED = os.path.join(PROJ, "labeled.ok")
os.environ.setdefault("GHIDRA_INSTALL_DIR", glob.glob(os.path.join(ROOT, "tools", "ghidra-dist", "ghidra_*"))[0])


def label_all(prog):
    from ghidra.program.model.symbol import SourceType, SymbolUtilities
    d = json.load(open(SCRIPT, encoding="utf-8"))
    names = [(m["Address"], m["Name"]) for k in ("ScriptMethod", "ScriptMetadata", "ScriptMetadataMethod") for m in d[k]]
    names += [(s["Address"], "str_" + s["Value"][:40]) for s in d["ScriptString"]]
    st, base = prog.getSymbolTable(), prog.getImageBase()
    for rva, name in names:
        try:
            st.createLabel(base.add(rva), SymbolUtilities.replaceInvalidChars(name, True), SourceType.USER_DEFINED)
        except Exception:
            pass  # a handful of names collide or land outside memory; not worth handling


def make_func(flat, addr):
    flat.disassemble(addr)
    return flat.getFunctionAt(addr) or flat.createFunction(addr, None)  # takes the script.json label as its name


def decompile(flat, rva):
    from ghidra.app.decompiler import DecompInterface
    prog = flat.getCurrentProgram()
    f = make_func(flat, prog.getImageBase().add(rva))
    # direct callees become functions too, so calls print as names instead of func_0x...
    for ins in prog.getListing().getInstructions(f.getBody(), True):
        for ref in ins.getReferencesFrom():
            if ref.getReferenceType().isCall():
                make_func(flat, ref.getToAddress())
    di = DecompInterface()
    di.openProgram(prog)
    res = di.decompileFunction(f, 120, flat.getMonitor())
    return res.getDecompiledFunction().getC() if res.decompileCompleted() else "decompile failed: " + res.getErrorMessage()


if __name__ == "__main__":
    os.makedirs(PROJ, exist_ok=True)
    first = not os.path.exists(LABELED)
    with pyghidra.open_program(SO, project_location=PROJ, project_name="il2cpp", analyze=False) as flat:
        prog = flat.getCurrentProgram()
        if first:
            print("first run: labeling from script.json ...", flush=True)
            with pyghidra.transaction(prog, "label"):
                label_all(prog)
        with pyghidra.transaction(prog, "decomp"):
            for a in sys.argv[1:]:
                print("// ===== RVA %s =====" % a)
                print(decompile(flat, int(a, 16)))
    if first:
        open(LABELED, "w").close()
