#!/usr/bin/env python3
"""Build a catalog of the 1.1.116 client/server contract from local static inputs; no execution.

Inputs (local only, not distributed): the Il2CppDumper dump.cs of the pinned client, the pinned
ELF and metadata (for DataMember aliases). Output: contract-catalog.json and CATALOG.md with
* every Api.Method, its request/response classes and their fields (including base classes);
* every static-data Container table with its JSON key and the JSON keys of its element type;
* which methods the local backend currently answers (from GameSocketService.cs).
Field order is the class field order from the dump; it is not a verified wire order.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import struct

HERE = Path(__file__).resolve().parent
WORK = HERE.parents[2]  # Override with --work when this checkout lacks the local inputs.
DUMP = 'prototype-1.1.116-20260924/evidence/il2cpp-dump-1.1.116/out/dump.cs'
ELF = 'analysis-obb-200098-20260924/endgraph-result-check/libil2cpp-1.1.116.so'
META = 'analysis-1.1.116-vs-1.3.102-20260924/client/metadata-1.1.116.dat'
ELF_SHA = 'c8a5556b1d37e86bb9427ce5b3d70389ac9b39fd9abcb81f31651d904c5b4aa3'
META_SHA = '6e7c83e2e7933c30f5aaa214266b8a7a94dacfeabad493056792c92fc1d28207'
SERVICE = HERE.parent / 'WitcherRevival.Server/Net/GameSocketService.cs'
CLASS = re.compile(r'^(?:public|internal|private|protected)?\s*(?:sealed |abstract |static )*(class|struct|enum) '
                   r'([A-Za-z0-9_.<>`,]+)(?: : ([^/]+?))? // TypeDefIndex: (\d+)')
FIELD = re.compile(r'^\t(?:\[.*\] )?(public|private|protected|internal)( static)?( readonly)?( const)? (.+?) ([A-Za-z0-9_<>]+)(?: = (.+?))?;(?: // 0x([0-9A-F]+))?$')


def require(value, message):
    if not value:
        raise ValueError(message)


def parse_dump(text):
    types, current, namespace = {}, None, ''
    for line in text.splitlines():
        if line.startswith('// Namespace: '):
            namespace = line[len('// Namespace: '):].strip()
            continue
        m = CLASS.match(line)
        if m:
            kind, name, base, index = m.groups()
            current = {'kind': kind, 'name': name, 'namespace': namespace, 'type_index': int(index),
                       'base': (base or '').split(',')[0].strip() or None, 'fields': []}
            types.setdefault(name, []).append(current)
            continue
        if current is not None and line == '}':
            current = None
            continue
        if current is not None:
            f = FIELD.match(line)
            if f and (not f.group(2) or f.group(4)) and (f.group(8) or f.group(4)):
                _, _, readonly, const, ftype, fname, value, offset = f.groups()
                name = fname.removeprefix('<').split('>k__BackingField')[0]
                current['fields'].append({'name': name, 'type': ftype, 'offset': int(offset, 16) if offset else None,
                                          **({'const': value} if const else {})})
    return types


def lookup(types, name, namespace_hint=None):
    rows = types.get(name) or []
    if namespace_hint:
        preferred = [row for row in rows if row['namespace'].startswith(namespace_hint)]
        rows = preferred or rows
    return rows[0] if rows else None


def with_bases(types, cls, namespace_hint):
    chain, seen = [], set()
    while cls is not None and cls['type_index'] not in seen:
        seen.add(cls['type_index'])
        chain.append(cls)
        base = cls['base']
        if not base or base in ('IMethodArgument', 'object') or base.startswith('I') and base[1:2].isupper():
            break
        cls = lookup(types, base, namespace_hint) or lookup(types, 'Container.' + base.split('.')[-1])
    fields = []
    for c in reversed(chain):
        fields += [f for f in c['fields'] if 'const' not in f and not f['name'].startswith('_factory')]
    return [c['name'] for c in chain], fields


class Aliases:
    """DataMember Name= values from the attribute generators (same layout as the DataMember reviews)."""

    def __init__(self, work):
        self.elf, self.meta = (work / ELF).read_bytes(), (work / META).read_bytes()
        require(hashlib.sha256(self.elf).hexdigest() == ELF_SHA, 'ELF SHA mismatch.')
        require(hashlib.sha256(self.meta).hexdigest() == META_SHA, 'Metadata SHA mismatch.')
        ph = struct.unpack_from('<Q', self.elf, 32)[0]
        size, count = struct.unpack_from('<HH', self.elf, 54)
        self.segments = [struct.unpack_from('<II6Q', self.elf, ph + i * size) for i in range(count)]
        self.pairs = [struct.unpack_from('<II', self.meta, 8 + 8 * i) for i in range(32)]
        self.images = [struct.unpack_from('<10I', self.meta, i)
                       for i in range(self.pairs[20][0], sum(self.pairs[20]), 40)]
        self.generators = self.q(0x4540020)
        require(self.generators == 0x4338aa8, 'Generator table mismatch.')

    def off(self, va):
        hits = [s[2] + va - s[3] for s in self.segments if s[0] == 1 and s[3] <= va < s[3] + s[5]]
        require(len(hits) == 1, 'Address mapping mismatch.')
        return hits[0]

    def q(self, va):
        return struct.unpack_from('<Q', self.elf, self.off(va))[0]

    def op(self, va):
        return struct.unpack_from('<I', self.elf, self.off(va))[0]

    def name(self, index):
        start, length = self.pairs[2]
        return self.meta[start + index:self.meta.index(b'\0', start + index, start + length)].decode()

    def of_type(self, type_index):
        owner = struct.unpack_from('<17I8H2I', self.meta, self.pairs[19][0] + 92 * type_index)
        image, = [i for i in self.images if i[2] <= type_index < i[2] + i[3]]
        attrs = {struct.unpack_from('<Iii', self.meta, self.pairs[26][0] + 12 * i)[0]: i
                 for i in range(image[8], image[8] + image[9])}
        result = {}
        for index in range(owner[9], owner[9] + owner[19]):
            field_name, _type, token = struct.unpack_from('<III', self.meta, self.pairs[11][0] + 12 * index)
            if token not in attrs:
                continue
            start = self.q(self.generators + 8 * attrs[token])
            a, b = self.op(start + 0x20), self.op(start + 0x24)
            if a & 0x9f00001f != 0x90000000 or b & 0xffc003ff != 0x91000000:
                continue
            imm = (((a >> 5) & 0x7ffff) << 2) | ((a >> 29) & 3)
            imm = imm - (1 << 21) if imm & (1 << 20) else imm
            page = ((start + 0x20) & ~0xfff) + (imm << 12)
            literal = self.off(page + ((b >> 10) & 0xfff))
            result[self.name(field_name)] = self.elf[literal:self.elf.index(b'\0', literal)].decode()
        return result


def element_type(ftype):
    m = re.fullmatch(r'(?:List|IEnumerable|HashSet)<(.+)>|(.+)\[\]', ftype)
    return (m.group(1) or m.group(2)) if m else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--output-dir', type=Path, default=HERE)
    ap.add_argument('--work', type=Path, default=WORK, help='directory holding the local analysis inputs')
    args = ap.parse_args()
    types = parse_dump((args.work / DUMP).read_text(encoding='utf-8', errors='replace'))
    aliases = Aliases(args.work)
    socket_ns = 'WitcherWorld.WebstuffClient'
    enum = [t for t in types['Method'] if t['type_index'] == 11525][0]
    service = SERVICE.read_text()
    constants = {int(v): k for k, v in re.findall(r'\b(M_[A-Za-z]+) = (\d+)', service)}
    handled = set()
    for line in re.findall(r'^\s+(.+?)\s*=>', service, re.M):
        for token in re.split(r'\s+or\s+', line):
            token = token.strip()
            if token.isdigit():
                handled.add(int(token))
            elif token in constants.values():
                handled.update(k for k, v in constants.items() if v == token)
    methods = []
    for f in enum['fields']:
        if 'const' not in f:
            continue
        mid, name = int(f['const']), f['name']
        entry = {'id': mid, 'name': name, 'answered_by_local_backend': mid in handled}
        for role in ('Request', 'Response'):
            cls = lookup(types, name + role, socket_ns)
            if cls:
                chain, fields = with_bases(types, cls, socket_ns)
                entry[role.lower()] = {'class': chain, 'fields': [(fld['name'], fld['type']) for fld in fields]}
        methods.append(entry)
    container = [t for t in types['Container'] if t['type_index'] == 14824][0]
    container_alias = aliases.of_type(14824)
    tables = []
    for f in container['fields']:
        element = element_type(f['type'])
        row = {'field': f['name'], 'json': container_alias.get(f['name']), 'type': f['type']}
        if element:
            cls = lookup(types, element if '.' in element else 'Container.' + element) or lookup(types, element)
            if cls:
                chain, fields = with_bases(types, cls, 'WitcherWorld.Modules.DataManager.StaticData')
                keys = {}
                for c in chain:
                    c_obj = lookup(types, c, 'WitcherWorld.Modules.DataManager.StaticData')
                    keys.update(aliases.of_type(c_obj['type_index']))
                row['element'] = {'class': chain,
                                  'fields': [(fld['name'], fld['type'], keys.get(fld['name'])) for fld in fields]}
        tables.append(row)
    catalog = {'client': '1.1.116', 'elf_sha256': ELF_SHA, 'metadata_sha256': META_SHA,
               'note': 'Field order follows the class layout, not a verified wire order.',
               'methods': methods, 'static_data_tables': tables}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / 'contract-catalog.json').write_text(json.dumps(catalog, indent=1) + '\n')
    lines = ['# 1.1.116 client contract catalog', '',
             'Generated by [build_contract_catalog.py](build_contract_catalog.py) from local static inputs. '
             'Field order is the class layout, not a verified wire order. The Local column records '
             'the backend snapshot at generation time; use [RPC coverage](RPC_COVERAGE.md) for the maintained implementation reference.', '',
             f'## API methods ({len(methods)}; answered in the recorded backend snapshot: {sum(m["answered_by_local_backend"] for m in methods)})', '',
             '| Id | Method | Local | Request fields | Response fields |', '| ---: | --- | :---: | --- | --- |']
    for m in methods:
        req = ', '.join(n for n, _ in m.get('request', {}).get('fields', [])) or ('—' if 'request' in m else '?')
        res = ', '.join(n for n, _ in m.get('response', {}).get('fields', [])) or ('—' if 'response' in m else '?')
        lines.append(f"| {m['id']} | {m['name']} | {'yes' if m['answered_by_local_backend'] else ''} | {req} | {res} |")
    lines += ['', f'## Static data tables ({len(tables)})', '', '| JSON key | Container field | Element JSON keys |', '| --- | --- | --- |']
    for t in tables:
        keys = ', '.join(k or f'({n})' for n, _, k in t.get('element', {}).get('fields', []))
        lines.append(f"| `{t['json']}` | {t['field']} | {keys} |")
    (args.output_dir / 'CATALOG.md').write_text('\n'.join(lines) + '\n')
    print(json.dumps({'methods': len(methods), 'answered': sum(m['answered_by_local_backend'] for m in methods),
                      'tables': len(tables), 'tables_with_keys': sum(1 for t in tables if t.get('element'))}))


if __name__ == '__main__':
    main()
