"""Assemble the phone runtime that the companion app ships, into local/companion/ (never committed).

  python companion/runtime/build_runtime.py

Output:
  jniLibs/arm64-v8a/libmusl.so    musl's dynamic loader (Alpine), the interpreter of the two programs below
  jniLibs/arm64-v8a/libserver.so  the server: self-contained single-file .NET for linux-musl-arm64
  jniLibs/arm64-v8a/libpython.so  Alpine's CPython 3.12, which runs the map services and the index builder
  jniLibs/arm64-v8a/libseccompshim.so  preloaded into both: answers the syscalls Android's app sandbox
                                  would kill them for (seccomp_shim.c)
  assets/runtime.zip              lib/ (shared libraries), python/ (standard library, pyosmium and lief),
                                  maps/ (the map services, laid out as in server/connection/),
                                  defaults/ (the server's default news and tasks),
                                  client/ (the client builder: scripts, Frida Gadget and the compiled hook)

Android only lets an app execute files from its native library folder, and has no musl. So the programs
are stored as lib*.so, and their ELF interpreter is rewritten to the relative name "libmusl.so". The
kernel resolves that name against the working directory, and the app starts them from that folder.

The two native pieces (pyosmium, the shim) are built by companion/runtime/build_natives.sh.
"""
import glob, os, shutil, subprocess, sys, zipfile

import alpine

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOCAL = os.path.join(ROOT, "local")
OUT = os.path.join(LOCAL, "companion")
STAGE = os.path.join(LOCAL, "build", "phone")
CACHE = os.path.join(LOCAL, "cache", "alpine")
SERVER = os.path.join(ROOT, "server", "WitcherRevival.Server")
CONNECTION = os.path.join(ROOT, "server", "connection")
CLIENT = os.path.join(ROOT, "tools", "client116")
PYTHON = "python3.12"
LIEF_VERSION = "0.17.6"
LIEF_WHEEL = f"lief-{LIEF_VERSION}-cp312-cp312-musllinux_1_2_aarch64.whl"  # matches the bundled CPython 3.12
# The client builder scripts run on the phone's Python (lief + axml); phone_build.py assembles the APK.
CLIENT_SCRIPTS = ["axml.py", "build_client.py", "phone_build.py", "extract_packs.py"]

PACKAGES = ["musl", "libgcc", "libstdc++", "libssl3", "libcrypto3", "zlib",
            "python3", "sqlite-libs", "libffi", "libbz2", "xz-libs", "libexpat", "mpdecimal", "lz4-libs"]
# Shared libraries the programs need. .NET loads OpenSSL (libssl/libcrypto) itself when it first uses crypto.
LIBS = ["libgcc_s.so.1", "libstdc++.so.6", "libssl.so.3", "libcrypto.so.3", "libz.so.1",
        "libpython3.12.so.1.0", "libsqlite3.so.0", "libffi.so.8", "libbz2.so.1", "liblzma.so.5",
        "libexpat.so.1", "libmpdec.so.4", "liblz4.so.1"]
# musl's loader is also its libc: it answers to its own SONAME and to these legacy names (lief links libc.so).
MUSL = {"libc.musl-aarch64.so.1", "ld-musl-aarch64.so.1",
        "libc.so", "libm.so", "libdl.so", "libpthread.so", "librt.so", "libutil.so", "libresolv.so", "libcrypt.so"}
# Standard library parts nothing on the phone uses; the extension modules need libraries we don't ship.
STDLIB_SKIP = {"ensurepip", "idlelib", "lib2to3", "pydoc_data", "test", "tkinter", "turtledemo", "unittest",
               "config-3.12-aarch64-linux-musl", "__pycache__"}
DYNLOAD_SKIP = ("_curses", "_dbm", "readline")
OSMIUM_SKIP = ("osmium/replication/", "osmium/tools/")  # need `requests`; the index builder doesn't use them


def publish_server(dest):
    subprocess.run(["dotnet", "publish", os.path.join(SERVER, "WitcherRevival.Server.csproj"), "-c", "Release",
                    "-r", "linux-musl-arm64", "--self-contained", "-p:PublishSingleFile=true", "-p:DebugType=none",
                    "-p:ServerGarbageCollection=false",  # one small heap on a phone, not one per core
                    "-p:NuGetAudit=false", "-p:UseSharedCompilation=false",
                    "--artifacts-path", os.path.join(LOCAL, "build", "phone-server"), "-o", dest, "--nologo", "-v", "q"],
                   cwd=ROOT, check=True)
    return os.path.join(dest, "WitcherRevival.Server")


def copy_stdlib(source, dest):
    def ignore(folder, names):
        skipped = {n for n in names if n in STDLIB_SKIP or n.endswith(".pyc")}
        if os.path.basename(folder) == "lib-dynload":
            skipped |= {n for n in names if n.startswith(DYNLOAD_SKIP)}
        return skipped
    shutil.copytree(source, dest, ignore=ignore)


def add_osmium(wheel, site_packages):
    with zipfile.ZipFile(wheel) as z:
        for name in z.namelist():
            if name.startswith("osmium/") and not name.startswith(OSMIUM_SKIP) and not name.endswith(".pyi"):
                z.extract(name, site_packages)


def add_lief(wheel, site_packages):
    with zipfile.ZipFile(wheel) as z:
        for name in z.namelist():
            if name.startswith("lief/") and not name.endswith(".pyi"):
                z.extract(name, site_packages)


def lief_wheel(dest):
    """The prebuilt musl aarch64 lief wheel (same version as the PC build), cached under natives/."""
    path = os.path.join(dest, LIEF_WHEEL)
    if not os.path.isfile(path):
        import json
        meta = json.loads(alpine.fetch(f"https://pypi.org/pypi/lief/{LIEF_VERSION}/json"))
        url = next(f["url"] for f in meta["urls"] if f["filename"] == LIEF_WHEEL)
        with open(path + ".part", "wb") as f:
            f.write(alpine.fetch(url))
        os.replace(path + ".part", path)
    return path


def build_hook():
    """Frida Gadget and the compiled hook — the non-game pieces the client build injects.
    Reuses the PC tooling: the Gadget download (patch_apk) and the hook bundler (restart)."""
    for path in (os.path.join(ROOT, "tools"), os.path.join(ROOT, "tools", "patch"), CLIENT):
        if path not in sys.path:
            sys.path.insert(0, path)
    import lzma
    import patch_apk, restart
    return {
        "libgadget.so": lzma.decompress(open(patch_apk.fetch(patch_apk.GADGET_URL), "rb").read()),
        "hook.bundle.js": open(restart.bundle_hook(), "rb").read(),
    }


def check_closure(rt):
    """Every DT_NEEDED of every shipped ELF must be shipped too (or be musl itself)."""
    elves = glob.glob(os.path.join(OUT, "jniLibs", "*", "*.so"))
    elves += [p for p in glob.glob(os.path.join(rt, "**", "*.so*"), recursive=True)
              # client/ is data for the game (Android libraries), never loaded by this runtime
              if os.path.isfile(p) and os.path.relpath(p, rt).split(os.sep)[0] != "client"]
    have = set(LIBS) | MUSL
    missing = {}
    for path in elves:
        if os.path.basename(path) == "libmusl.so":
            continue
        for need in alpine.Elf(path).needed():
            if need not in have:
                missing.setdefault(need, []).append(os.path.relpath(path, STAGE))
    if missing:
        raise SystemExit(f"missing shared libraries: {missing}")


def main():
    natives = os.path.join(LOCAL, "cache", "natives")
    wheel = os.path.join(natives, "osmium-4.3.1-cp312-cp312-linux_aarch64.whl")
    shim = os.path.join(natives, "libseccompshim.so")
    for path in (wheel, shim):
        if not os.path.isfile(path):
            raise SystemExit(f"{path} is missing: build it with companion/runtime/build_natives.sh")

    shutil.rmtree(STAGE, ignore_errors=True)
    shutil.rmtree(OUT, ignore_errors=True)
    jni = os.path.join(OUT, "jniLibs", "arm64-v8a")
    rt = os.path.join(STAGE, "rt")
    os.makedirs(jni)
    os.makedirs(os.path.join(OUT, "assets"))

    print("fetching Alpine packages ...")
    alpine_root = os.path.join(STAGE, "alpine")
    packages = alpine.index()
    for name in PACKAGES:
        print(f"  {name} {alpine.extract(name, packages, alpine_root, CACHE)}")
    alpine.resolve_links()
    shutil.copyfile(os.path.join(alpine_root, "lib", "ld-musl-aarch64.so.1"), os.path.join(jni, "libmusl.so"))
    shutil.copyfile(shim, os.path.join(jni, "libseccompshim.so"))
    os.makedirs(os.path.join(rt, "lib"))
    for name in LIBS:
        shutil.copyfile(os.path.join(alpine_root, "usr", "lib", name), os.path.join(rt, "lib", name))

    print("adding Python and the map services ...")
    python = os.path.join(jni, "libpython.so")
    shutil.copyfile(os.path.join(alpine_root, "usr", "bin", PYTHON), python)
    alpine.Elf(python).set_interp("libmusl.so")
    stdlib = os.path.join(rt, "python", "lib", PYTHON)
    copy_stdlib(os.path.join(alpine_root, "usr", "lib", PYTHON), stdlib)
    add_osmium(wheel, os.path.join(stdlib, "site-packages"))
    add_lief(lief_wheel(natives), os.path.join(stdlib, "site-packages"))
    maps = os.path.join(rt, "maps")
    os.makedirs(os.path.join(maps, "map-road-fixture-01"))
    for script in glob.glob(os.path.join(CONNECTION, "map-road-fixture-01", "*.py")):
        if not os.path.basename(script).startswith("test_"):
            shutil.copy(script, os.path.join(maps, "map-road-fixture-01"))
    shutil.copytree(os.path.join(CONNECTION, "map-tile-fixture-01", "generated-terrain01"),
                    os.path.join(maps, "map-tile-fixture-01", "generated-terrain01"))

    print("adding the client builder ...")
    client = os.path.join(rt, "client")
    os.makedirs(client)
    for name in CLIENT_SCRIPTS:
        shutil.copy(os.path.join(CLIENT, name), client)
    for name, data in build_hook().items():
        with open(os.path.join(client, name), "wb") as f:
            f.write(data)

    print("publishing the server ...")
    server = os.path.join(jni, "libserver.so")
    shutil.copyfile(publish_server(os.path.join(STAGE, "server")), server)
    alpine.Elf(server).set_interp("libmusl.so")
    for name in ("news", "tasks"):
        shutil.copytree(os.path.join(SERVER, name), os.path.join(rt, "defaults", name))

    check_closure(rt)
    with zipfile.ZipFile(os.path.join(OUT, "assets", "runtime.zip"), "w", zipfile.ZIP_DEFLATED) as z:
        for folder, dirs, files in os.walk(rt):
            dirs.sort()
            for name in sorted(files):
                path = os.path.join(folder, name)
                z.write(path, os.path.relpath(path, rt).replace(os.sep, "/"))
    for folder, _, files in os.walk(OUT):
        for name in files:
            path = os.path.join(folder, name)
            print(f"  {os.path.relpath(path, OUT)}: {os.path.getsize(path) / 1e6:.1f} MB")


if __name__ == "__main__":
    sys.exit(main())
