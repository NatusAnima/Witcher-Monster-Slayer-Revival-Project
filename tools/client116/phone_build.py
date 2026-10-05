"""Assemble the playable 1.1.116 client on the phone, unsigned. The companion app signs it afterwards
with apksig (there is no JVM on the phone), then installs it.

Same assembly as build_client.py, reused through assemble(). The only differences: Frida Gadget and its
config are shipped with the app instead of downloaded, and signing happens in the app, not here. Runs on
the companion app's bundled Python, which also ships lief and axml.

  python phone_build.py --apks <install split dir> --packs <extracted packs dir> \
      --gadget <libgadget.so> --gadget-config <libgadget.config.so> --out <unsigned.apk>

--apks  the directory holding the installed game's base.apk and split_*.apk (its sourceDir)
--packs the 26 Play-delivered packs, extracted from a backup with extract_packs.py
"""
import argparse, os

from build_client import assemble, check_alignment


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apks", required=True)
    ap.add_argument("--packs", required=True)
    ap.add_argument("--gadget", required=True)
    ap.add_argument("--gadget-config", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    count = assemble(args.apks, args.packs, args.out,
                     open(args.gadget, "rb").read(), open(args.gadget_config, "rb").read())
    check_alignment(args.out)  # Writer aligned it; the app's apksig signing preserves that alignment
    print(f"done: {args.out} ({os.path.getsize(args.out) / 2**30:.2f} GiB, {count} entries)")


if __name__ == "__main__":
    main()
