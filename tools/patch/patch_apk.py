"""Build the Frida-Gadget client from your own original APK (v1.0.43 build 200098, arm64-v8a).

Reproduces exactly how the dev phone's APK was patched: Frida Gadget 17.15.3 (must match the `frida` pip
package that frida_run.py uses) is added as lib/arm64-v8a/libgadget.so with a config that listens on
127.0.0.1:27042 and pauses the app at launch ("on_load": "wait") until frida_run.py resumes it;
libmain.so gets libgadget.so as a DT_NEEDED entry so it loads first; the original signature is dropped and
the APK is re-signed with a debug key by uber-apk-signer (needs `java` on PATH).

  python tools/patch/patch_apk.py "<original.apk>" [out.apk]
  adb install out.apk          (uninstall any differently-signed copy first)
  adb push main.200098.com.spokko.witchermonsterslayer.obb /sdcard/Android/obb/com.spokko.witchermonsterslayer/
"""
import lzma, os, subprocess, sys, urllib.request, zipfile
import lief

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, ".cache")
GADGET_URL = "https://github.com/frida/frida/releases/download/17.15.3/frida-gadget-17.15.3-android-arm64.so.xz"
SIGNER_URL = "https://github.com/patrickfav/uber-apk-signer/releases/download/v1.3.0/uber-apk-signer-1.3.0.jar"
CONFIG = b'{"interaction":{"type":"listen","address":"127.0.0.1","port":27042,"on_load":"wait"}}'
LIB = "lib/arm64-v8a/"


def fetch(url):
    path = os.path.join(CACHE, url.rsplit("/", 1)[1])
    if not os.path.exists(path):
        os.makedirs(CACHE, exist_ok=True)
        print("downloading", url)
        urllib.request.urlretrieve(url, path)
    return path


def main(src, out):
    gadget = lzma.decompress(open(fetch(GADGET_URL), "rb").read())
    orig, patched = os.path.join(CACHE, "libmain.orig.so"), os.path.join(CACHE, "libmain.so")
    with zipfile.ZipFile(src) as zin:
        open(orig, "wb").write(zin.read(LIB + "libmain.so"))
        libmain = lief.parse(orig)
        libmain.add_library("libgadget.so")
        libmain.write(patched)
        with zipfile.ZipFile(out, "w") as zout:
            for item in zin.infolist():
                name = item.filename
                if name.startswith("META-INF/") and name.rsplit(".", 1)[-1] in ("SF", "RSA", "DSA", "EC", "MF"):
                    continue  # old signature; the APK is re-signed below
                data = open(patched, "rb").read() if name == LIB + "libmain.so" else zin.read(item)
                zout.writestr(item, data, compress_type=item.compress_type)
            zout.writestr(LIB + "libgadget.so", gadget, compress_type=zipfile.ZIP_DEFLATED)
            zout.writestr(LIB + "libgadget.config.so", CONFIG, compress_type=zipfile.ZIP_DEFLATED)
    subprocess.run(["java", "-jar", fetch(SIGNER_URL), "--apks", out, "--overwrite"], check=True)
    print("done:", out)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "witcher_gadget.apk")
