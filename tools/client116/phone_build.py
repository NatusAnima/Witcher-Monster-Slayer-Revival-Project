"""Assemble the playable 1.1.116 client on the phone, unsigned. The companion app signs it afterwards
with apksig (there is no JVM on the phone), then installs it.

Same assembly as build_client.py, reused through assemble(). The differences: Frida Gadget is shipped with the
app instead of downloaded, the hook goes inside the APK (the phone has no adb to push it with), and signing
happens in the app, not here. Runs on the companion app's bundled Python, which also ships lief and axml.

  python phone_build.py --apks <install split dir> --packs <packs dir> \
      --gadget <libgadget.so> --hook <hook.bundle.js> --out <unsigned.apk>
  python phone_build.py --patch <installed client apk> \
      --gadget <libgadget.so> --hook <hook.bundle.js> --out <unsigned.apk>

--apks  the directory holding the installed game's base.apk and its splits, or one universal base.apk (its sourceDir's folder)
--packs the 26 Play-delivered packs, one file per pack, as the app downloads them from Google Play
--patch the installed client's APK: update its hook and Gadget in place instead of assembling from --apks and --packs
"""
import argparse, os

from build_client import EMBEDDED_CONFIG, assemble, check_alignment, patch_client


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apks")
    ap.add_argument("--packs")
    ap.add_argument("--patch")
    ap.add_argument("--gadget", required=True)
    ap.add_argument("--hook", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    if not args.patch and not (args.apks and args.packs):
        ap.error("give --patch, or both --apks and --packs")

    gadget, hook = open(args.gadget, "rb").read(), open(args.hook, "rb").read()
    count = (patch_client(args.patch, args.out, gadget, EMBEDDED_CONFIG, hook) if args.patch
             else assemble(args.apks, args.packs, args.out, gadget, EMBEDDED_CONFIG, hook))
    check_alignment(args.out)  # Writer aligned it; the app's apksig signing preserves that alignment
    print(f"done: {args.out} ({os.path.getsize(args.out) / 2**30:.2f} GiB, {count} entries)")


if __name__ == "__main__":
    main()
