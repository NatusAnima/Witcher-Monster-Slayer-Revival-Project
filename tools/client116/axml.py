"""Minimal Android binary-XML (AXML) editor: enough to patch AndroidManifest.xml in place.

Strings are only ever appended, so existing string indices in element chunks stay valid.
"""
import struct

STRING, BOOL = 0x03, 0x12
TRUE = -1  # AXML boolean true


class Manifest:
    def __init__(self, data):
        assert struct.unpack_from("<HHI", data)[0] == 0x0003, "not binary XML"
        self.chunks, pos = [], 8
        while pos < len(data):
            t, _, size = struct.unpack_from("<HHI", data, pos)
            self.chunks.append([t, data[pos:pos + size]])
            pos += size
        pool = next(c[1] for c in self.chunks if c[0] == 0x0001)
        count, styles, self.flags, start = struct.unpack_from("<IIII", pool, 8)
        assert styles == 0 and not self.flags & 0x100, "only UTF-16 pools without styles are supported"
        self.strings = []
        for off in struct.unpack_from(f"<{count}I", pool, 28):
            p = start + off
            n = struct.unpack_from("<H", pool, p)[0]
            p += 2
            if n & 0x8000:
                n = ((n & 0x7FFF) << 16) | struct.unpack_from("<H", pool, p)[0]
                p += 2
            self.strings.append(pool[p:p + 2 * n].decode("utf-16le"))
        rm = next(c[1] for c in self.chunks if c[0] == 0x0180)
        self.resmap = list(struct.unpack_from(f"<{(len(rm) - 8) // 4}I", rm, 8))

    def string(self, s):
        if s not in self.strings:
            self.strings.append(s)
        return self.strings.index(s)

    def elements(self, name):
        """Yield (chunk, attributes) for start elements called `name`; attributes are mutable lists."""
        for c in self.chunks:
            if c[0] == 0x0102 and self.strings[struct.unpack_from("<I", c[1], 20)[0]] == name:
                count = struct.unpack_from("<H", c[1], 28)[0]
                yield c, [list(struct.unpack_from("<IIiHBBi", c[1], 36 + 20 * i)) for i in range(count)]

    def attr_name(self, a):
        return self.strings[a[1]]

    def set_attrs(self, chunk, attrs):
        """Write attributes back (sorted by resource id, as Android expects); id/class/style must be unused."""
        assert struct.unpack_from("<HHH", chunk[1], 30) == (0, 0, 0)
        res = lambda a: (self.resmap[a[1]] if a[1] < len(self.resmap) else 0) or 0xFFFFFFFF  # id-less last
        attrs.sort(key=res)
        body = b"".join(struct.pack("<IIiHBBi", *a) for a in attrs)
        head = bytearray(chunk[1][:36])
        struct.pack_into("<I", head, 4, 36 + len(body))
        struct.pack_into("<H", head, 28, len(attrs))
        chunk[1] = bytes(head) + body

    def android_attr(self, name, resource_id, data_type, data, raw=-1):
        """A new android:<name> attribute; its name string gets `resource_id` in the resource map."""
        idx = self.string(name)
        if idx >= len(self.resmap):
            self.resmap += [0] * (idx + 1 - len(self.resmap))
        self.resmap[idx] = resource_id
        ns = self.strings.index("http://schemas.android.com/apk/res/android")
        return [ns, idx, raw, 8, 0, data_type, data]

    def to_bytes(self):
        offs, blob = [], bytearray()
        for s in self.strings:
            offs.append(len(blob))
            n = len(s.encode("utf-16le")) // 2
            blob += struct.pack("<H", n) if n < 0x8000 else struct.pack("<HH", 0x8000 | n >> 16, n & 0xFFFF)
            blob += s.encode("utf-16le") + b"\0\0"
        blob += b"\0" * (-len(blob) % 4)
        start = 28 + 4 * len(offs)
        pool = struct.pack("<HHIIIIII", 0x0001, 28, start + len(blob), len(offs), 0, self.flags, start, 0)
        pool += struct.pack(f"<{len(offs)}I", *offs) + blob
        rm = struct.pack("<HHI", 0x0180, 8, 8 + 4 * len(self.resmap)) + struct.pack(f"<{len(self.resmap)}I", *self.resmap)
        out = b"".join(pool if t == 0x0001 else rm if t == 0x0180 else c for t, c in self.chunks)
        return struct.pack("<HHI", 0x0003, 8, 8 + len(out)) + out


if __name__ == "__main__":  # self-check: an unmodified manifest must round-trip byte for byte
    import sys, zipfile
    original = zipfile.ZipFile(sys.argv[1]).read("AndroidManifest.xml")
    assert Manifest(original).to_bytes() == original, "round trip changed the manifest"
    print("round trip ok")
