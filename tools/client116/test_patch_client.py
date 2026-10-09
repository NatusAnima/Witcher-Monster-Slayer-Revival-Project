"""patch_client swaps the hook, Gadget and its config in a built client and keeps everything else, aligned.
Needs lief (build_client imports it), nothing else:  python tools/client116/test_patch_client.py
"""
import os, sys, tempfile, unittest, zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_client import HOOK_FILE, LIB, Writer, check_alignment, patch_client

KEPT = {
    "AndroidManifest.xml": b"manifest",
    LIB + "libmain.so": b"\x7fELF" + b"m" * 5000,
    "assets/assetpack/pack_a": bytes(range(256)) * 40,
}


def make_client(path, hook=True):
    """A stand-in for an installed client: stored and deflated entries, an old hook, an old signature file."""
    out = Writer(path)
    for name, data in KEPT.items():
        out.bytes(name, data)
    out.bytes("classes.dex", b"dex " * 1000, zipfile.ZIP_DEFLATED)
    out.bytes("META-INF/MANIFEST.MF", b"old signature")
    out.bytes(LIB + "libgadget.so", b"old gadget")
    out.bytes(LIB + "libgadget.config.so", b"old config")
    if hook:
        out.bytes(LIB + HOOK_FILE, b"old hook")
    out.zip.close()


class PatchClient(unittest.TestCase):
    def patch(self, hook=True):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        client, out = os.path.join(tmp.name, "client.apk"), os.path.join(tmp.name, "out", "patched.apk")
        make_client(client, hook)
        patch_client(client, out, b"new gadget", b"new config", b"new hook")
        return zipfile.ZipFile(out)

    def test_swaps_the_three_files_and_keeps_the_rest(self):
        z = self.patch()
        self.assertEqual(z.read(LIB + "libgadget.so"), b"new gadget")
        self.assertEqual(z.read(LIB + "libgadget.config.so"), b"new config")
        self.assertEqual(z.read(LIB + HOOK_FILE), b"new hook")
        for name, data in KEPT.items():
            self.assertEqual(z.read(name), data, name)
        self.assertEqual(z.read("classes.dex"), b"dex " * 1000)
        self.assertEqual(z.getinfo("classes.dex").compress_type, zipfile.ZIP_DEFLATED)

    def test_drops_the_old_signature_and_stays_aligned(self):
        z = self.patch()
        self.assertNotIn("META-INF/MANIFEST.MF", z.namelist())
        self.assertEqual(len(z.namelist()), len(set(z.namelist())))
        self.assertIsNone(z.testzip())
        check_alignment(z.filename)

    def test_adds_a_hook_the_client_never_had(self):
        self.assertEqual(self.patch(hook=False).read(LIB + HOOK_FILE), b"new hook")


if __name__ == "__main__":
    unittest.main()
