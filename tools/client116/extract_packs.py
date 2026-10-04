"""Extract the 26 Play-delivered asset packs from an Android backup of the 1.1.116 game.

Make the backup on the phone (approve it there, leave the password empty):
  adb exec-out bu backup -noapk com.spokko.witchermonsterslayer > witcher_appdata.ab
Then:
  python tools/client116/extract_packs.py witcher_appdata.ab <out_dir>

Only the pack payloads (`f/assetpacks/<pack>/<ver>/<ver>/assets/assetpack/<pack>`) are written;
account data and everything else in the backup is skipped.
"""
import os, shutil, sys, tarfile, zlib

PACKS = 26
PACK_BYTES = 1442937044  # sum of the 26 originals (matches the 1.1.116 reconstruction's recovery record)


class Inflate:
    """File-like zlib stream over the backup body, for tarfile's streaming mode."""
    def __init__(self, f):
        self.f, self.d, self.buf = f, zlib.decompressobj(), b""

    def read(self, n):
        while len(self.buf) < n:
            chunk = self.f.read(1 << 20)
            if not chunk:
                self.buf += self.d.flush()
                break
            self.buf += self.d.decompress(chunk)
        out, self.buf = self.buf[:n], self.buf[n:]
        return out


def main(backup, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    found = {}
    with open(backup, "rb") as f:
        header = [f.readline() for _ in range(4)]
        if header[0] != b"ANDROID BACKUP\n" or header[3] != b"none\n":
            sys.exit("not an unencrypted Android backup (leave the backup password empty)")
        archive = tarfile.open(fileobj=Inflate(f), mode="r|")
        for m in archive:
            parts = m.name.split("/")
            if m.isfile() and "assetpacks" in parts and parts[-2] == "assetpack":
                with archive.extractfile(m) as src, open(os.path.join(out_dir, parts[-1]), "wb") as dst:
                    shutil.copyfileobj(src, dst, 1 << 22)
                found[parts[-1]] = m.size
    total = sum(found.values())
    print(f"{len(found)} packs, {total} bytes -> {out_dir}")
    if len(found) != PACKS or total != PACK_BYTES:
        sys.exit(f"expected {PACKS} packs / {PACK_BYTES} bytes: incomplete download or backup")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
