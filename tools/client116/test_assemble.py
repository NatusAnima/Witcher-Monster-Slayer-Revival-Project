"""assemble() takes the game as a split set (Play, Aurora, an APKMirror bundle) or as one universal APK, and says what is missing.
Small fake APKs stand in for the real ones; the manifest and Gadget steps need real AXML and ELF files, so they are stubbed.
Needs lief (build_client imports it), nothing else:  python tools/client116/test_assemble.py
"""
import contextlib, hashlib, io, os, sys, tempfile, unittest, zipfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_client as b

LIBS = b"fake il2cpp"
BUILT_IN = [f"built_in_{i}" for i in range(b.INSTALL_TIME_PACKS)]
DOWNLOADED = [f"downloaded_{i}" for i in range(3)]


def make_apk(path, entries):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)


def game_dir(root, shape, built_in=BUILT_IN, libs=True):
    """The game's folder: 'splits' (base, an arm64 split, one split per built-in pack, plus a language split) or 'universal'."""
    folder = os.path.join(root, shape)
    os.makedirs(folder)
    base = {"AndroidManifest.xml": b"manifest", "classes.dex": b"dex", "assets/aa/settings.json": b"{}",
            "META-INF/ANDROIDD.RSA": b"old signature"}
    lib_entries = {b.LIB + "libil2cpp.so": LIBS, b.LIB + "libmain.so": b"main", "lib/armeabi-v7a/libunity.so": b"other abi"} if libs else {}
    packs = {b.ASSETPACK + name: name.encode() for name in built_in}
    if shape == "universal":
        make_apk(os.path.join(folder, "base.apk"), {**base, **lib_entries, **packs})
    else:
        make_apk(os.path.join(folder, "base.apk"), base)
        if libs:
            make_apk(os.path.join(folder, "split_config.arm64_v8a.apk"), lib_entries)
        for name in built_in:
            make_apk(os.path.join(folder, f"split_{name}.apk"), {b.ASSETPACK + name: name.encode(), "AndroidManifest.xml": b"split"})
        make_apk(os.path.join(folder, "split_config.en.apk"), {"AndroidManifest.xml": b"language", "resources.arsc": b"strings"})
    return folder


class Assemble(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.packs = os.path.join(self.tmp.name, "packs")
        os.makedirs(self.packs)
        for name in DOWNLOADED:
            with open(os.path.join(self.packs, name), "wb") as f:
                f.write(name.encode())
        self.modules = None

        def manifest(data, modules):
            self.modules = modules
            return b"patched manifest"

        for patch in (mock.patch.object(b, "PACKS", len(DOWNLOADED)),
                      mock.patch.object(b, "PACK_BYTES", sum(len(n) for n in DOWNLOADED)),
                      mock.patch.object(b, "LIBIL2CPP_SHA256", hashlib.sha256(LIBS).hexdigest()),
                      mock.patch.object(b, "patch_manifest", manifest),
                      mock.patch.object(b, "gadget_libmain", lambda data: b"gadget main")):
            patch.start()
            self.addCleanup(patch.stop)

    def build(self, shape, **kwargs):
        folder = game_dir(self.tmp.name, shape, **kwargs)
        out = os.path.join(self.tmp.name, shape + ".apk")
        with contextlib.redirect_stdout(io.StringIO()):  # assemble() reports its steps
            b.assemble(folder, self.packs, out, b"gadget", b"config", b"hook")
        return zipfile.ZipFile(out)

    def test_split_set_and_universal_apk_make_the_same_client(self):
        splits, universal = self.build("splits"), self.build("universal")
        # Names that differ only by where they came from: the universal APK's base holds what the splits add.
        self.assertEqual(sorted(splits.namelist()), sorted(universal.namelist()))
        self.assertEqual(self.modules, sorted(["base"] + BUILT_IN + DOWNLOADED))
        for client in (splits, universal):
            self.assertEqual(client.read(b.LIB + "libmain.so"), b"gadget main")  # Gadget goes into libmain
            self.assertEqual(client.read("AndroidManifest.xml"), b"patched manifest")
            self.assertEqual(client.read(b.ASSETPACK + BUILT_IN[0]), BUILT_IN[0].encode())
            self.assertEqual(client.read(b.ASSETPACK + DOWNLOADED[0]), DOWNLOADED[0].encode())
            self.assertEqual(client.read(b.LIB + b.HOOK_FILE), b"hook")

    def test_other_abis_old_signatures_and_language_splits_are_left_out(self):
        for shape in ("splits", "universal"):
            names = self.build(shape).namelist()
            self.assertNotIn("lib/armeabi-v7a/libunity.so", names)
            self.assertNotIn("META-INF/ANDROIDD.RSA", names)
            self.assertNotIn("resources.arsc", names)

    def test_base_apk_alone_says_it_has_no_libraries(self):
        with self.assertRaises(SystemExit) as stopped:
            self.build("splits", libs=False)
        self.assertIn("no game libraries", str(stopped.exception))

    def test_too_few_built_in_packs_is_reported_with_the_count(self):
        with self.assertRaises(SystemExit) as stopped:
            self.build("universal", built_in=BUILT_IN[:5])
        self.assertIn("5 of its 21 built-in packs", str(stopped.exception))

    def test_wrong_build_is_refused(self):
        with mock.patch.object(b, "LIBIL2CPP_SHA256", "0" * 64), self.assertRaises(SystemExit) as stopped:
            self.build("universal")
        self.assertIn("not the original", str(stopped.exception))


class Scan(unittest.TestCase):
    def test_finds_libraries_and_packs_by_content(self):
        def apk(entries):
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as z:
                for name in entries:
                    z.writestr(name, b"x")
            return zipfile.ZipFile(buffer)

        libs, built_in = b.scan({"base.apk": apk(["classes.dex"]), "libs-and-more.apk": apk([b.LIB + "libil2cpp.so"]),
                                 "any-name.apk": apk([b.ASSETPACK + "game_data", b.ASSETPACK + "deeper/ignored"])})
        self.assertEqual(libs, "libs-and-more.apk")
        self.assertEqual(built_in, {"game_data": "any-name.apk"})


if __name__ == "__main__":
    unittest.main()
