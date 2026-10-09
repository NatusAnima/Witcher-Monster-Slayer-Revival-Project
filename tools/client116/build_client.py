"""Build the playable 1.1.116 client from your own Play install: one APK holding all 47 asset packs,
plain HTTP allowed, and Frida Gadget loaded by libmain.so. Gadget runs hook.js from the app's storage
folder (tools/restart.py pushes it there), so the game starts normally from its icon.

  python tools/client116/build_client.py --apks <play export dir> --packs <extracted packs dir>
  adb uninstall com.spokko.witchermonsterslayer     (the Play copy is signed with a different key)
  adb install local/client/witcher116.apk

--apks   the APKs of an install of 1.1.116 (versionCode 300085): base.apk and its splits (the 23 files of a Play/Aurora install),
         or one universal base.apk that already holds the libraries and the 21 built-in packs (APKMirror's single APK)
--packs  the 26 Play-delivered asset packs, extracted with extract_packs.py
"""
import argparse, hashlib, json, lzma, os, shutil, struct, subprocess, sys, tempfile, zipfile

import lief

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
from axml import BOOL, STRING, TRUE, Manifest
from extract_packs import PACK_BYTES, PACKS

LIB = "lib/arm64-v8a/"
LIBIL2CPP_SHA256 = "c8a5556b1d37e86bb9427ce5b3d70389ac9b39fd9abcb81f31651d904c5b4aa3"  # original 1.1.116
INSTALL_TIME_PACKS = 21
HOOK_PATH = "/sdcard/Android/data/com.spokko.witchermonsterslayer/files/hook.js"  # reloaded when it changes
GADGET_CONFIG = json.dumps({"interaction": {"type": "script", "path": HOOK_PATH, "on_change": "reload"}}).encode()
# A phone build has no adb to push the hook with (Android 11 keeps other apps out of Android/data), so it ships the hook
# inside the APK instead. Android unpacks lib*.so files, and Gadget resolves a relative script path against its own folder.
HOOK_FILE = "libhook.js.so"
EMBEDDED_CONFIG = json.dumps({"interaction": {"type": "script", "path": HOOK_FILE}}).encode()
SIGNATURE_FILES = (".SF", ".RSA", ".DSA", ".EC", "MANIFEST.MF")
zipfile.ZIP64_LIMIT = (1 << 32) - 1  # APK tooling rejects ZIP64; the APK stays below 4 GiB


REQUIRED_SPLITS = "com.android.vending.splits.required"  # a split install's base APK says its splits are needed
FUSED_MODULES = "com.android.dynamic.apk.fused.modules"  # a universal APK lists the modules it already holds


def patch_manifest(data, modules):
    m = Manifest(data)
    app, attrs = next(m.elements("application"))
    cleartext = False
    for a in attrs:
        if m.attr_name(a) == "isSplitRequired":
            a[6] = 0  # every split is merged into this one APK
        elif m.attr_name(a) == "usesCleartextTraffic":
            a[6] = TRUE
            cleartext = True
    if not cleartext:
        attrs.append(m.android_attr("usesCleartextTraffic", 0x010104EC, BOOL, TRUE))  # HTTP to your own server
    m.set_attrs(app, attrs)
    # Play Core treats the modules listed here as installed, so the asset packs load from this APK's assets.
    found = 0
    for chunk, attrs in m.elements("meta-data"):
        name = next(a for a in attrs if m.attr_name(a) == "name")
        if m.strings[name[2]] not in (REQUIRED_SPLITS, FUSED_MODULES):
            continue
        value = next(a for a in attrs if m.attr_name(a) == "value")
        name[2] = name[6] = m.string(FUSED_MODULES)
        value[2] = value[6] = m.string(",".join(modules))
        value[5] = STRING
        m.set_attrs(chunk, attrs)
        found += 1
    if found != 1:  # axml.py cannot add an element, so a manifest with neither entry cannot be made right here
        sys.exit(f"the manifest has {found} {REQUIRED_SPLITS} or {FUSED_MODULES} entries, expected one")
    return m.to_bytes()


def gadget_libmain(data):
    fd, tmp = tempfile.mkstemp(suffix=".so")
    os.close(fd)
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        elf = lief.parse(tmp)
        elf.add_library("libgadget.so")  # loads Gadget before the game's own code
        elf.write(tmp)
        with open(tmp, "rb") as f:
            return f.read()
    finally:
        os.remove(tmp)


class Writer:
    """Writes entries with zipalign's rules: stored data 4-byte aligned, native libraries page aligned."""

    def __init__(self, path):
        self.zip = zipfile.ZipFile(path, "w")
        self.names = set()

    def _info(self, name, compress, date_time=(1981, 1, 1, 1, 1, 2)):
        assert name not in self.names, "duplicate entry " + name
        self.names.add(name)
        zi = zipfile.ZipInfo(name, date_time)
        zi.compress_type = compress
        if compress == zipfile.ZIP_STORED:
            align = 4096 if name.endswith(".so") else 4
            pad = -(self.zip.fp.tell() + 30 + len(name.encode()) + 6) % align
            zi.extra = struct.pack("<HHH", 0xD935, 2 + pad, align) + b"\0" * pad  # zipalign's padding field
        return zi

    def bytes(self, name, data, compress=zipfile.ZIP_STORED, date_time=(1981, 1, 1, 1, 1, 2)):
        self.zip.writestr(self._info(name, compress, date_time), data)

    def stream(self, name, src, size, compress=zipfile.ZIP_STORED, date_time=(1981, 1, 1, 1, 1, 2)):
        zi = self._info(name, compress, date_time)
        zi.file_size = size
        with self.zip.open(zi, "w") as dst:
            shutil.copyfileobj(src, dst, 1 << 22)

    def entry(self, zin, info, name=None):
        with zin.open(info) as src:
            self.stream(name or info.filename, src, info.file_size, info.compress_type, info.date_time)


def check_alignment(path):
    with open(path, "rb") as f, zipfile.ZipFile(path) as z:
        for i in z.infolist():
            if i.compress_type == zipfile.ZIP_STORED:
                f.seek(i.header_offset + 26)
                n, e = struct.unpack("<HH", f.read(4))
                need = 4096 if i.filename.endswith(".so") else 4
                assert (i.header_offset + 30 + n + e) % need == 0, "misaligned after signing: " + i.filename


ASSETPACK = "assets/assetpack/"


def scan(zips):
    """Sort the game's APKs by what they hold, not by name (an APKMirror file is named differently from an Aurora one).
    `zips` maps a file name to its ZipFile and holds base.apk. Returns (libs, built_in): the file with the arm64 libraries
    (None if no file has them) and, for each built-in pack, the file that carries it (one file per pack, assets/assetpack/<name>)."""
    order = ["base.apk"] + sorted(n for n in zips if n != "base.apk")
    libs = next((n for n in order if LIB + "libil2cpp.so" in zips[n].namelist()), None)
    built_in = {}
    for n in order:
        for entry in zips[n].namelist():
            if entry.startswith(ASSETPACK) and "/" not in entry[len(ASSETPACK):]:
                built_in.setdefault(entry[len(ASSETPACK):], n)
    return libs, built_in


def assemble(apks, packs, out_path, gadget, config, hook=None):
    """Build the unsigned, zip-aligned client APK from the install's APKs and the recovered packs. The APKs are base.apk plus its
    splits (a Play/Aurora install, or an APKMirror bundle), or one universal base.apk that holds the libraries and the 21 built-in
    packs itself; any other split (a language or another ABI) is ignored.
    `gadget`/`config` are the libgadget.so and its config bytes (fetched on a PC, shipped on the phone).
    `hook` is the compiled hook for the APK to carry (phone builds, with EMBEDDED_CONFIG); without it the config
    points at HOOK_PATH, where restart.py pushes the hook (PC builds).
    Returns the entry count. The caller signs the result (uber-apk-signer on a PC, apksig on the phone)."""
    names = sorted(f for f in os.listdir(apks) if f.endswith(".apk"))
    if "base.apk" not in names:
        sys.exit(f"no base.apk in {apks}")
    recovered = sorted(os.listdir(packs))
    total = sum(os.path.getsize(os.path.join(packs, p)) for p in recovered)
    if len(recovered) != PACKS or total != PACK_BYTES:
        sys.exit(f"{packs} must hold exactly the {PACKS} packs ({PACK_BYTES} bytes), one file each; found {len(recovered)} files, {total} bytes")
    zips = {n: zipfile.ZipFile(os.path.join(apks, n)) for n in names}
    try:
        libs, built_in = scan(zips)
        print(f"game files: {len(names)} APKs ({sum(os.path.getsize(os.path.join(apks, n)) for n in names) / 2**20:.0f} MB): {', '.join(names)}")
        if libs is None:
            sys.exit(f"no {LIB}libil2cpp.so in any APK in {apks}: base.apk alone has no game libraries. Use the full APK or the bundle")
        if hashlib.sha256(zips[libs].read(LIB + "libil2cpp.so")).hexdigest() != LIBIL2CPP_SHA256:
            sys.exit("these APKs are not the original 1.1.116 (300085) build")
        print(f"game libraries are in {libs} and match the original 1.1.116 build")
        if len(built_in) != INSTALL_TIME_PACKS:
            sys.exit(f"the game has {len(built_in)} of its {INSTALL_TIME_PACKS} built-in packs: use the full APK or the bundle")
        if set(built_in) & set(recovered):
            sys.exit(f"packs both built in and downloaded: {sorted(set(built_in) & set(recovered))}")
        used = {"base.apk", libs} | set(built_in.values())
        print(f"{len(built_in)} built-in packs found, {len(recovered)} downloaded packs ({total / 2**20:.0f} MB)"
              + (f"; ignored: {', '.join(n for n in names if n not in used)}" if len(used) < len(names) else ""))
        modules = sorted(["base"] + list(built_in) + recovered)

        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        out = Writer(out_path)

        def copy(name):
            """What the client needs from one APK: all of base.apk; of the others only the arm64 libraries and the assets."""
            zin = zips[name]
            for info in zin.infolist():
                entry = info.filename
                if entry.startswith("META-INF/") and entry.endswith(SIGNATURE_FILES):
                    continue  # the old signature; re-signed by the caller
                if entry.startswith("lib/") and not entry.startswith(LIB):
                    continue  # other ABIs: this client is arm64 only
                if name != "base.apk" and not (entry.startswith("assets/") or (entry.startswith(LIB) and name == libs)):
                    continue
                if entry == "AndroidManifest.xml":
                    out.bytes(entry, patch_manifest(zin.read(info), modules), info.compress_type, info.date_time)
                elif entry == LIB + "libmain.so":
                    out.bytes(entry, gadget_libmain(zin.read(info)))
                else:
                    out.entry(zin, info)

        copy("base.apk")
        if libs != "base.apk":
            copy(libs)
        out.bytes(LIB + "libgadget.so", gadget)
        out.bytes(LIB + "libgadget.config.so", config)
        if hook is not None:
            out.bytes(LIB + HOOK_FILE, hook)
        for name in sorted(set(built_in.values()) - {"base.apk", libs}):
            copy(name)
        for pack in recovered:
            path = os.path.join(packs, pack)
            with open(path, "rb") as src:
                out.stream(ASSETPACK + pack, src, os.path.getsize(path))
        out.zip.close()
        return len(out.names)
    finally:
        for z in zips.values():
            z.close()


def patch_client(client_apk, out_path, gadget, config, hook):
    """Rebuild an installed client with a newer Gadget, config and hook: every other entry is copied from it, so the
    original install and the 26 packs are not needed. Returns the entry count. The caller signs the result.
    ponytail: swaps only those three files. A release that also changes the manifest or libmain.so patch needs the full build."""
    swap = {LIB + "libgadget.so": gadget, LIB + "libgadget.config.so": config, LIB + HOOK_FILE: hook}
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    out = Writer(out_path)
    with zipfile.ZipFile(client_apk) as client:
        for info in client.infolist():
            if info.filename.startswith("META-INF/") and info.filename.endswith(SIGNATURE_FILES):
                continue  # the old signature; re-signed by the caller
            if info.filename in swap:
                out.bytes(info.filename, swap.pop(info.filename))
            else:
                out.entry(client, info)
    for name, data in swap.items():  # a client built before the hook was embedded has no file to replace
        out.bytes(name, data)
    out.zip.close()
    return len(out.names)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apks", required=True)
    ap.add_argument("--packs", required=True)
    ap.add_argument("--out", default=os.path.join(ROOT, "local", "client", "witcher116.apk"))
    args = ap.parse_args()
    sys.path.insert(0, os.path.join(ROOT, "tools", "patch"))
    from patch_apk import GADGET_URL, SIGNER_URL, fetch  # same Gadget/signer downloads as the 1.0.43 client

    count = assemble(args.apks, args.packs, args.out,
                     lzma.decompress(open(fetch(GADGET_URL), "rb").read()), GADGET_CONFIG)
    subprocess.run(["java", "-jar", fetch(SIGNER_URL), "--apks", args.out, "--overwrite", "--skipZipAlign"],
                   check=True, stdout=subprocess.DEVNULL)
    check_alignment(args.out)
    print(f"done: {args.out} ({os.path.getsize(args.out) / 2**30:.2f} GiB, {count} entries)")


if __name__ == "__main__":
    main()
