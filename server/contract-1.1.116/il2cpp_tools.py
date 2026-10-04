#!/usr/bin/env python3
"""Static-analysis helpers for the 1.1.116 client's libil2cpp.so and its Il2CppDumper output.

The client loads metadata through GOT slots (adrp+ldr gives the slot, .rela.dyn R_AARCH64_RELATIVE gives the
address that script.json names), so plain disassembly shows no names. These commands add them:

  annotate <start> <stop>      disassemble a range with method names (bl/b targets) and metadata names (GOT loads)
  callers <rva>...             every bl/b to the given addresses, with the calling method
  names <Class>...             JSON names of [DataMember] fields: the C string each attribute generator passes to
                               DataMemberAttribute.set_Name (the dump does not show attribute arguments)
  getters <Class>...           which field offset each simple getter of a class reads

Inputs: --lib (libil2cpp.so) and --dump (the Il2CppDumper output directory with dump.cs and script.json), or the
MS_LIBIL2CPP and MS_IL2CPP_DUMP environment variables. Requires llvm-objdump, readelf and numpy.
"""
import argparse, bisect, json, os, re, subprocess, sys
from pathlib import Path

SET_NAME = 0x1D79F9C   # System.Runtime.Serialization.DataMemberAttribute.set_Name in 1.1.116


class Image:
    def __init__(self, lib: Path, dump: Path):
        self.lib, self.dump = lib, dump
        script = json.loads((dump / 'script.json').read_text())
        self.methods = {}
        for m in script['ScriptMethod']:
            self.methods.setdefault(m['Address'], m['Name'])
        self.starts = sorted(self.methods)
        self.meta = {m['Address']: m['Name'] for m in script['ScriptMetadata'] + script['ScriptMetadataMethod']}
        self.meta.update({m['Address']: 'STR ' + repr(m['Value'])[:80] for m in script['ScriptString']})
        self.got = {}
        for line in subprocess.run(['readelf', '-rW', str(lib)], capture_output=True, text=True).stdout.splitlines():
            p = line.split()
            if len(p) >= 4 and 'RELATIVE' in p[2]:
                self.got[int(p[0], 16)] = int(p[3], 16)
        self.segments = []
        for line in subprocess.run(['readelf', '-lW', str(lib)], capture_output=True, text=True).stdout.splitlines():
            p = line.split()
            if p and p[0] == 'LOAD':
                self.segments.append((int(p[2], 16), int(p[1], 16), int(p[4], 16)))
        self.data = lib.read_bytes()
        self._lines = None

    def method_at(self, address):
        i = bisect.bisect_right(self.starts, address) - 1
        return self.methods[self.starts[i]] if i >= 0 else '?'

    def cstring(self, address):
        for va, offset, size in self.segments:
            if va <= address < va + size:
                o = address - va + offset
                return self.data[o:self.data.index(b'\0', o)].decode()
        raise ValueError(hex(address))

    def disassemble(self, start, stop):
        return subprocess.run(['llvm-objdump', '-d', '--no-show-raw-insn', f'--start-address={start:#x}',
                               f'--stop-address={stop:#x}', str(self.lib)], capture_output=True, text=True).stdout

    def annotate(self, start, stop):
        page = {}
        for line in self.disassemble(start, stop).splitlines():
            note = ''
            m = re.search(r'adrp\s+(x\d+), 0x([0-9a-f]+)', line)
            if m: page[m.group(1)] = int(m.group(2), 16)
            m = re.search(r'ldr\s+x\d+, \[(x\d+), #0x([0-9a-f]+)\]', line)
            if m and m.group(1) in page:
                slot = page[m.group(1)] + int(m.group(2), 16)
                if self.got.get(slot) in self.meta: note = '  ; ' + self.meta[self.got[slot]]
            m = re.search(r'\bbl?\s+0x([0-9a-f]+)', line)
            if m and int(m.group(1), 16) in self.methods: note = '  ; ' + self.methods[int(m.group(1), 16)]
            yield line + note

    def callers(self, targets):
        import numpy as np
        sections = subprocess.run(['readelf', '-SW', str(self.lib)], capture_output=True, text=True).stdout
        for line in sections.splitlines():
            p = line.replace('[ ', '[').split()
            if len(p) > 5 and p[1] in ('.text', 'il2cpp'):
                address, offset, size = int(p[3], 16), int(p[4], 16), int(p[5], 16)
                words = np.fromfile(self.lib, dtype='<u4', count=size // 4, offset=offset)
                branch = ((words & 0xFC000000) == 0x94000000) | ((words & 0xFC000000) == 0x14000000)
                imm = (words & 0x03FFFFFF).astype(np.int64)
                imm = np.where(imm & 0x02000000, imm - 0x04000000, imm)
                pcs = address + np.arange(len(words), dtype=np.int64) * 4
                destination = pcs + imm * 4
                for target in targets:
                    for i in np.nonzero(branch & (destination == target))[0]:
                        yield target, int(pcs[i]), self.method_at(int(pcs[i]))

    def lines(self):
        if self._lines is None:
            self._lines = (self.dump / 'dump.cs').read_text(encoding='utf-8', errors='replace').split('\n')
        return self._lines

    def class_body(self, name):
        lines = self.lines()
        start = next(i for i, l in enumerate(lines) if re.match(
            r'^(public|internal|private)( sealed| static| abstract)* (class|struct) ' + re.escape(name) + r'( :| //)', l))
        for line in lines[start + 1:]:
            if line.startswith('}'): return
            yield line

    def datamember_names(self, name):
        pending = None
        for line in self.class_body(name):
            m = re.search(r'\[DataMemberAttribute\] // RVA: (0x[0-9A-F]+)', line)
            if m:
                pending = int(m.group(1), 16)
                continue
            f = re.match(r'\s+(?:public|private|protected|internal)[^(]*? ([A-Za-z0-9_<>.\[\], ]+?) ([A-Za-z0-9_<>]+); // (0x[0-9A-F]+)', line)
            if f and pending is not None:
                asm = self.disassemble(pending, pending + 0x60)
                json_name = f.group(2)
                if f'{SET_NAME:x}' in asm:
                    a = re.search(r'adrp\s+x0, 0x([0-9a-f]+)', asm); b = re.search(r'add\s+x0, x0, #0x([0-9a-f]+)', asm)
                    json_name = self.cstring(int(a.group(1), 16) + int(b.group(1), 16)) if a and b else '?'
                yield f.group(3), json_name, f.group(1).strip(), f.group(2)
            pending = None if f else pending

    def getters(self, name):
        rva = None
        for line in self.class_body(name):
            m = re.search(r'// RVA: (0x[0-9A-F]+)', line)
            if m:
                rva = int(m.group(1), 16)
                continue
            g = re.search(r' ([A-Za-z0-9_\[\]<>]+) get_([A-Za-z0-9_]+)\(\)', line)
            if g and rva is not None:
                body = [l.split('\t', 1)[-1].strip() for l in self.disassemble(rva, rva + 0x10).splitlines()
                        if re.match(r'\s+[0-9a-f]+:', l)]
                read = re.match(r'ldrb?\s+[wx]0, \[x0, #0x([0-9a-f]+)\]', body[0]) if body else None
                yield g.group(2), g.group(1), (f'+0x{read.group(1)}' if read else ' ; '.join(body[:3]))
            rva = None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--lib', type=Path, default=os.environ.get('MS_LIBIL2CPP'))
    parser.add_argument('--dump', type=Path, default=os.environ.get('MS_IL2CPP_DUMP'))
    parser.add_argument('command', choices=['annotate', 'callers', 'names', 'getters'])
    parser.add_argument('args', nargs='+')
    a = parser.parse_args()
    if not a.lib or not a.dump:
        parser.error('give --lib and --dump, or set MS_LIBIL2CPP and MS_IL2CPP_DUMP')
    image = Image(a.lib, a.dump)
    if a.command == 'annotate':
        for line in image.annotate(int(a.args[0], 16), int(a.args[1], 16)):
            print(line)
    elif a.command == 'callers':
        for target, pc, method in image.callers([int(x, 16) for x in a.args]):
            print(f'{target:#x} {pc:#x} {method}')
    elif a.command == 'names':
        for cls in a.args:
            print(f'== {cls}')
            for offset, json_name, type_name, field in image.datamember_names(cls):
                print(f'  {offset:>6} {json_name:<32} {type_name} {field}')
    else:
        for cls in a.args:
            print(f'== {cls}')
            for getter, type_name, source in image.getters(cls):
                print(f'  {getter:<28} {type_name:<8} {source}')


if __name__ == '__main__':
    sys.exit(main())
