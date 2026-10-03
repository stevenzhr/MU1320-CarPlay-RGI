#!/usr/bin/env python3
"""Read ELF segments (works for QNX IFS libraries without section tables)."""
import hashlib
import json
import re
from pathlib import Path
from elftools.elf.elffile import ELFFile
from elftools.elf.dynamic import DynamicSegment

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'mu1320-rgi/reports'


def inspect(path):
    with path.open('rb') as stream:
        elf = ELFFile(stream)
        dyn = next((s for s in elf.iter_segments() if isinstance(s, DynamicSegment)), None)
        symbols, exports, relocs, tags = {}, {}, [], {}
        if dyn:
            for t in dyn.iter_tags():
                val = getattr(t, 'needed', getattr(t, 'soname', getattr(t, 'rpath', t.entry.d_val)))
                tags.setdefault(t.entry.d_tag, []).append(val)
            for i, s in enumerate(dyn.iter_symbols()):
                symbols[i] = s.name
                if s['st_shndx'] != 'SHN_UNDEF' and s['st_info']['bind'] in ('STB_GLOBAL', 'STB_WEAK'):
                    exports[s.name] = {'address': hex(s['st_value']), 'size': s['st_size'],
                                       'visibility': s['st_other']['visibility']}
            for table in dyn.get_relocation_tables().values():
                for r in table.iter_relocations():
                    n = symbols.get(r['r_info_sym'])
                    if n:
                        relocs.append({'name': n, 'offset': hex(r['r_offset']), 'type': r['r_info_type']})
        return {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'size': path.stat().st_size,
                'class': elf.elfclass, 'little_endian': elf.little_endian,
                'machine': elf['e_machine'], 'flags': hex(elf['e_flags']),
                'dynamic': tags, 'exports': exports, 'relocations': relocs}


def main():
    files = sorted((ROOT / 'resource').glob('lib*.so*'))
    files += [ROOT / 'resource/dio_manager', ROOT / 'resource/dmdt']
    inventory = {p.name: inspect(p) for p in files}
    source = (ROOT / 'mib2q-carplay-rgi/hook/framework/hook_framework.c').read_text()
    names = sorted(set(re.findall(r'dlsym\(RTLD_NEXT, "([^"]+)"', source)))
    seams = {}
    for n in names:
        seams[n] = {'providers': {k: v['exports'][n] for k, v in inventory.items() if n in v['exports']},
                    'relocations': [{**r, 'file': k} for k, v in inventory.items()
                                    for r in v['relocations'] if r['name'] == n]}
    gfx_source = '\n'.join(p.read_text() for p in [ROOT/'mib2q-carplay-rgi/common/cluster_surface.c',
        *sorted((ROOT/'mib2q-carplay-rgi/maneuver_render').glob('*.c'))] if p.name != 'platform_macos.c')
    gfx = {n: [k for k, v in inventory.items() if n in v['exports']]
           for n in sorted(set(re.findall(r'\b(screen_[a-z_]+|egl[A-Z][A-Za-z0-9]+|gl[A-Z][A-Za-z0-9]+)\s*\(', gfx_source)))}
    result = {'scope': 'provided ELF files only; exports do not prove interposition or ABI behavior',
              'seams': seams, 'graphics_symbols': gfx,
              'missing_needed': sorted(set(n for v in inventory.values() for n in v['dynamic'].get('DT_NEEDED', [])
                                          if n not in {s for x in inventory.values() for s in x['dynamic'].get('DT_SONAME', [])})),
              'files': inventory}
    OUT.mkdir(exist_ok=True)
    (OUT/'native-audit.json').write_text(json.dumps(result, indent=2)+'\n')
    print('Native report:', OUT/'native-audit.json')
    for n, v in seams.items(): print(n, 'providers=', list(v['providers']), 'relocations=', len(v['relocations']))
    print('Missing graphics exports:', [n for n, ps in gfx.items() if not ps])


if __name__ == '__main__': main()
