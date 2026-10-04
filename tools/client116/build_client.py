"""Build the playable 1.1.116 client from your own Play install: one APK holding all 47 asset packs,
plain HTTP allowed, and Frida Gadget loaded by libmain.so. Gadget runs hook.js from the app's storage
folder (tools/restart.py pushes it there), so the game starts normally from its icon.

  python tools/client116/build_client.py --apks <play export dir> --packs <extracted packs dir>
  adb uninstall com.spokko.witchermonsterslayer     (the Play copy is signed with a different key)
  adb install local/client/witcher116.apk

--apks   the 23 APKs pulled from a Play/Aurora install of 1.1.116 (versionCode 300085)
--packs  the 26 Play-delivered asset packs, extracted with extract_packs.py
"""
import argparse, hashlib, json, lzma, os, shutil, struct, subprocess, sys, zipfile

import lief

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools", "patch"))
from axml import BOOL, STRING, TRUE, Manifest
from extract_packs import PACK_BYTES, PACKS
from patch_apk import GADGET_URL, SIGNER_URL, fetch  # same Gadget/signer downloads as the 1.0.43 client

LIB = "lib/arm64-v8a/"
LIBIL2CPP_SHA256 = "c8a5556b1d37e86bb9427ce5b3d70389ac9b39fd9abcb81f31651d904c5b4aa3"  # original 1.1.116
INSTALL_TIME_PACKS = 21
HOOK_PATH = "/sdcard/Android/data/com.spokko.witchermonsterslayer/files/hook.js"  # reloaded when it changes
GADGET_CONFIG = json.dumps({"interaction": {"type": "script", "path": HOOK_PATH, "on_change": "reload"}}).encode()
SIGNATURE_FILES = (".SF", ".RSA", ".DSA", ".EC", "MANIFEST.MF")
zipfile.ZIP64_LIMIT = (1 << 32) - 1  # APK tooling rejects ZIP64; the APK stays below 4 GiB


def patch_manifest(data, modules):
    m = Manifest(data)
    app, attrs = next(m.elements("application"))
    for a in attrs:
        if m.attr_name(a) == "isSplitRequired":
            a[6] = 0  # every split is merged into this one APK
    attrs.append(m.android_attr("usesCleartextTraffic", 0x010104EC, BOOL, TRUE))  # HTTP to your own server
    m.set_attrs(app, attrs)
    # Play Core treats the modules listed here as installed, so the asset packs load from this APK's assets.
    found = 0
    for chunk, attrs in m.elements("meta-data"):
        name = next(a for a in attrs if m.attr_name(a) == "name")
        if m.strings[name[2]] != "com.android.vending.splits.required":
            continue
        value = next(a for a in attrs if m.attr_name(a) == "value")
        name[2] = name[6] = m.string("com.android.dynamic.apk.fused.modules")
        value[2] = value[6] = m.string(",".join(modules))
        value[5] = STRING
        m.set_attrs(chunk, attrs)
        found += 1
    assert found == 1, "expected one com.android.vending.splits.required entry"
    return m.to_bytes()


def gadget_libmain(data):
    tmp = os.path.join(ROOT, "local", "client", "libmain.tmp.so")
    with open(tmp, "wb") as f:
        f.write(data)
    elf = lief.parse(tmp)
    elf.add_library("libgadget.so")  # loads Gadget before the game's own code
    elf.write(tmp)
    with open(tmp, "rb") as f:
        out = f.read()
    os.remove(tmp)
    return out


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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apks", required=True)
    ap.add_argument("--packs", required=True)
    ap.add_argument("--out", default=os.path.join(ROOT, "local", "client", "witcher116.apk"))
    args = ap.parse_args()

    split_packs = sorted(f[6:-4] for f in os.listdir(args.apks)
                         if f.startswith("split_") and f.endswith(".apk") and f != "split_config.arm64_v8a.apk")
    recovered = sorted(os.listdir(args.packs))
    if len(split_packs) != INSTALL_TIME_PACKS:
        sys.exit(f"expected {INSTALL_TIME_PACKS} asset-pack splits in {args.apks}, found {len(split_packs)}")
    if len(recovered) != PACKS or sum(os.path.getsize(os.path.join(args.packs, p)) for p in recovered) != PACK_BYTES:
        sys.exit(f"{args.packs} must hold the {PACKS} packs written by extract_packs.py")
    config = zipfile.ZipFile(os.path.join(args.apks, "split_config.arm64_v8a.apk"))
    if hashlib.sha256(config.read(LIB + "libil2cpp.so")).hexdigest() != LIBIL2CPP_SHA256:
        sys.exit("these APKs are not the original 1.1.116 (300085) build")

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    out = Writer(args.out)
    with zipfile.ZipFile(os.path.join(args.apks, "base.apk")) as base:
        for info in base.infolist():
            if info.filename.startswith("META-INF/") and info.filename.endswith(SIGNATURE_FILES):
                continue  # the old signature; re-signed below
            if info.filename == "AndroidManifest.xml":
                manifest = patch_manifest(base.read(info), sorted(["base"] + split_packs + recovered))
                out.bytes(info.filename, manifest, info.compress_type, info.date_time)
            else:
                out.entry(base, info)
    for info in config.infolist():
        if info.filename.startswith(LIB):
            if info.filename == LIB + "libmain.so":
                out.bytes(info.filename, gadget_libmain(config.read(info)))
            else:
                out.entry(config, info)
    out.bytes(LIB + "libgadget.so", lzma.decompress(open(fetch(GADGET_URL), "rb").read()))
    out.bytes(LIB + "libgadget.config.so", GADGET_CONFIG)
    for pack in split_packs:
        with zipfile.ZipFile(os.path.join(args.apks, f"split_{pack}.apk")) as split:
            for info in split.infolist():
                if info.filename.startswith("assets/"):
                    out.entry(split, info)
    for pack in recovered:
        path = os.path.join(args.packs, pack)
        with open(path, "rb") as src:
            out.stream("assets/assetpack/" + pack, src, os.path.getsize(path))
    out.zip.close()

    subprocess.run(["java", "-jar", fetch(SIGNER_URL), "--apks", args.out, "--overwrite", "--skipZipAlign"],
                   check=True, stdout=subprocess.DEVNULL)
    check_alignment(args.out)
    print(f"done: {args.out} ({os.path.getsize(args.out) / 2**30:.2f} GiB, {len(out.names)} entries)")


if __name__ == "__main__":
    main()
