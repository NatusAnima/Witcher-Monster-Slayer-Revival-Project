"""Fetch Alpine Linux aarch64 packages and read or patch the ELF files in them.

The phone runtime is the musl build of .NET plus Alpine's Python. Android has no musl, so the
companion ships musl's loader as a native library, and each program's ELF interpreter is
rewritten to that file's name.

Each package is checked against the checksum in the signed branch index. The index itself
comes from Alpine's CDN over HTTPS.
"""
import base64, hashlib, io, os, shutil, struct, tarfile, urllib.request, zlib

MIRROR = "https://dl-cdn.alpinelinux.org/alpine"
BRANCH, ARCH = "v3.22", "aarch64"
pending = []  # (link, target) symlinks, copied once every package is unpacked (resolve_links)


def fetch(url):
    with urllib.request.urlopen(url, timeout=120) as reply:
        return reply.read()


def index(repos=("main", "community")):
    """{name: (repo, version, checksum)} from the branch's APKINDEX files."""
    packages = {}
    for repo in repos:
        with tarfile.open(fileobj=io.BytesIO(fetch(f"{MIRROR}/{BRANCH}/{repo}/{ARCH}/APKINDEX.tar.gz"))) as tar:
            text = tar.extractfile("APKINDEX").read().decode()
        for record in text.split("\n\n"):
            fields = dict(line.split(":", 1) for line in record.splitlines() if line[1:2] == ":")
            if "P" in fields:
                packages[fields["P"]] = (repo, fields["V"], fields["C"])
    return packages


def gzip_members(data):
    """Split concatenated gzip streams: an .apk is signature + control + data."""
    members, pos = [], 0
    while pos < len(data):
        stream = zlib.decompressobj(31)
        body = stream.decompress(data[pos:])
        end = len(data) - len(stream.unused_data)
        members.append((data[pos:end], body))
        pos = end
    return members


def extract(name, packages, dest, cache):
    """Download one package (cached), check it against the index and unpack its files into dest."""
    repo, version, checksum = packages[name]
    path = os.path.join(cache, f"{name}-{version}.apk")
    if not os.path.exists(path):
        os.makedirs(cache, exist_ok=True)
        data = fetch(f"{MIRROR}/{BRANCH}/{repo}/{ARCH}/{name}-{version}.apk")
        with open(path + ".part", "wb") as f:
            f.write(data)
        os.replace(path + ".part", path)
    with open(path, "rb") as f:
        members = gzip_members(f.read())
    control = members[-2][0]  # the checksum covers the compressed control stream
    if not checksum.startswith("Q1") or hashlib.sha1(control).digest() != base64.b64decode(checksum[2:]):
        raise SystemExit(f"{name}-{version}: checksum does not match the index")
    with tarfile.open(fileobj=io.BytesIO(members[-1][1])) as tar:
        for member in tar:
            if member.name.startswith(".") or not (member.isfile() or member.issym() or member.isdir()):
                continue
            target = os.path.join(dest, member.name)
            if member.isdir():
                os.makedirs(target, exist_ok=True)
            elif member.issym():  # stored as a copy: Android extraction and zip assets have no symlinks
                os.makedirs(os.path.dirname(target), exist_ok=True)
                link = os.path.normpath(os.path.join(os.path.dirname(member.name), member.linkname))
                pending.append((target, os.path.join(dest, link)))
            else:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, "wb") as f:
                    f.write(tar.extractfile(member).read())
    return version


def resolve_links():
    while pending:
        progress = False
        for item in list(pending):
            target, source = item
            if os.path.isfile(source):
                shutil.copyfile(source, target)
                pending.remove(item)
                progress = True
        if not progress:
            pending.clear()  # dangling links (e.g. into packages we don't ship) are dropped


class Elf:
    """Just enough ELF64 (little-endian) to list DT_NEEDED and rewrite PT_INTERP."""

    def __init__(self, path):
        self.path = path
        with open(path, "rb") as f:
            self.data = bytearray(f.read(1 << 20))  # headers and dynamic tables sit at the start
        if self.data[:4] != b"\x7fELF" or self.data[4] != 2:
            raise ValueError(f"{path}: not an ELF64 file")
        phoff, = struct.unpack_from("<Q", self.data, 0x20)
        phentsize, phnum = struct.unpack_from("<HH", self.data, 0x36)
        self.segments = [struct.unpack_from("<IIQQQQQQ", self.data, phoff + i * phentsize) + (phoff + i * phentsize,)
                         for i in range(phnum)]

    def _offset(self, vaddr):
        for p_type, _, offset, seg_vaddr, _, filesz, _, _, _ in self.segments:
            if p_type == 1 and seg_vaddr <= vaddr < seg_vaddr + filesz:
                return vaddr - seg_vaddr + offset
        raise ValueError(f"{self.path}: address {vaddr:#x} is not in a loaded segment")

    def _read(self, offset, size):
        if offset + size > len(self.data):
            with open(self.path, "rb") as f:
                f.seek(offset)
                return f.read(size)
        return bytes(self.data[offset:offset + size])

    def interp(self):
        for p_type, _, offset, _, _, filesz, _, _, _ in self.segments:
            if p_type == 3:
                return self._read(offset, filesz).split(b"\0")[0].decode()
        return None

    def needed(self):
        dynamic = [s for s in self.segments if s[0] == 2]
        if not dynamic:
            return []
        _, _, offset, _, _, filesz, _, _, _ = dynamic[0]
        table = self._read(offset, filesz)
        entries = [struct.unpack_from("<qQ", table, i) for i in range(0, len(table), 16)]
        strtab = self._offset(next(value for tag, value in entries if tag == 5))
        names = []
        for tag, value in entries:
            if tag == 1:
                raw = self._read(strtab + value, 256)
                names.append(raw.split(b"\0")[0].decode())
        return names

    def set_interp(self, name):
        """Point PT_INTERP at name, in place. A relative name is resolved against the working directory."""
        encoded = name.encode() + b"\0"
        for p_type, _, offset, _, _, filesz, _, _, _ in self.segments:
            if p_type == 3:
                if len(encoded) > filesz:
                    raise ValueError(f"{self.path}: interpreter name longer than {filesz - 1} bytes")
                with open(self.path, "r+b") as f:
                    f.seek(offset)
                    f.write(encoded.ljust(filesz, b"\0"))
                return
        raise ValueError(f"{self.path}: no PT_INTERP segment")
