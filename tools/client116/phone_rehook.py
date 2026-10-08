"""Put a new hook into the playable client that is already installed, unsigned, without rebuilding it.

A phone build carries its hook inside the APK (lib/arm64-v8a/libhook.js.so), so a hook fix used to need the
whole client build again, and with it the 1.3 GB extra-data download. The installed client already holds
everything else, so this copies it entry by entry with only the hook swapped. The companion app signs the
result with the same key as the installed client and installs it as an update, which keeps the game's data.

  python phone_rehook.py --apk <installed client base.apk> --hook <hook.bundle.js> --out <unsigned.apk>

Writes nothing when the installed client already carries this hook ("up to date").
"""
import argparse, os, sys, zipfile

from build_client import HOOK_FILE, LIB, SIGNATURE_FILES, Writer, check_alignment


def rehook(apk, hook, out_path):
    """Returns the entry count written, or None when the client already carries `hook`."""
    with zipfile.ZipFile(apk) as zin:
        names = [i.filename for i in zin.infolist()]
        if LIB + HOOK_FILE not in names:
            sys.exit("this client carries no hook of its own (a PC build loads it from storage instead)")
        if zin.read(LIB + HOOK_FILE) == hook:
            return None
        out = Writer(out_path)
        try:
            for info in zin.infolist():
                if info.filename.startswith("META-INF/") and info.filename.endswith(SIGNATURE_FILES):
                    continue  # the old signature; the app signs the result
                if info.filename == LIB + HOOK_FILE:
                    out.bytes(info.filename, hook)
                else:
                    out.entry(zin, info)
        finally:
            out.zip.close()
        return len(out.names)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apk", required=True)
    ap.add_argument("--hook", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    if os.path.exists(args.out):
        os.remove(args.out)
    count = rehook(args.apk, open(args.hook, "rb").read(), args.out)
    if count is None:
        print("up to date: the installed client already carries this hook")
        return
    check_alignment(args.out)
    print(f"done: {args.out} ({os.path.getsize(args.out) / 2**30:.2f} GiB, {count} entries)")


if __name__ == "__main__":
    main()
