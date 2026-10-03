#!/usr/bin/env python3
"""Reproducible, read-only ARM evidence dump for the supplied MU1320 binaries."""
import hashlib
import json
import struct
from pathlib import Path
from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM
from elftools.elf.elffile import ELFFile
from elftools.elf.dynamic import DynamicSegment

BASE = Path(__file__).resolve().parents[1]
RESOURCE = BASE.parent / 'resource'

def inspect(path, ranges):
    with path.open('rb') as stream:
        elf = ELFFile(stream)
        segments = [s for s in elf.iter_segments() if s['p_type'] == 'PT_LOAD']
        def read(addr, size=4):
            for s in segments:
                if s['p_vaddr'] <= addr < s['p_vaddr'] + s['p_filesz']:
                    off = addr - s['p_vaddr']
                    return s.data()[off:off+size]
            return b''
        def word(addr):
            b = read(addr)
            return struct.unpack('<I', b)[0] if len(b) == 4 else 0
        dyn = next(s for s in elf.iter_segments() if isinstance(s, DynamicSegment))
        symbols = list(dyn.iter_symbols())
        names = {s['st_value']: s.name for s in symbols if s['st_value']}
        reloc = {r['r_offset']: symbols[r['r_info_sym']].name
                 for table in dyn.get_relocation_tables().values()
                 for r in table.iter_relocations() if r['r_info_sym']}
        md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
        md.detail = True
        md.skipdata = True
        # ARM PLT uses add ip, pc, #imm; add ip, ip, #imm; ldr pc, [ip, #imm].
        for s in segments:
            if not s['p_flags'] & 1:
                continue
            code = list(md.disasm(s.data(), s['p_vaddr']))
            for a,b,c in zip(code, code[1:], code[2:]):
                if (a.mnemonic == 'add' and a.op_str.startswith('ip, pc, #')
                    and b.mnemonic == 'add' and b.op_str.startswith('ip, ip, #')
                    and c.mnemonic == 'ldr' and c.op_str.startswith('pc, [ip')):
                    got = a.address + 8 + a.operands[2].imm + b.operands[2].imm + c.operands[1].mem.disp
                    if got in reloc:
                        names[a.address] = reloc[got]
        lines = []
        for start,size in ranges:
            lines.append('\nRANGE %08x %d' % (start,size))
            for ins in md.disasm(read(start,size), start):
                note = ''
                if ins.mnemonic in ('b','bl') and ins.op_str.startswith('#'):
                    note = names.get(int(ins.op_str[1:],16),'')
                if ins.mnemonic == 'ldr' and '[pc,' in ins.op_str:
                    addr = ins.address + 8 + ins.operands[1].mem.disp
                    note += ' literal[%08x]=%08x' % (addr,word(addr))
                lines.append('%08x %-8s %-32s %s' % (ins.address,ins.mnemonic,ins.op_str,note))
        return dict(path=str(path.relative_to(RESOURCE)),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),size=path.stat().st_size), '\n'.join(lines)+'\n'

def main():
    jobs = [
        ('smartphone_integrator',[(0x137a08,612),(0x137e9c,300),(0x139ca8,196),(0x16ce3c,224),(0x189970,5504)]),
        ('native-libs/mnt/app/eso/lib/libutil.so',[(0x2be98,2028),(0x2c75c,108),(0x2f0a0,220)]),
        ('native-libs/mnt/app/eso/lib/libosal.so',[(0x518a8,2980)])]
    manifest = []
    for p,ranges in jobs:
        identity,dump = inspect(RESOURCE/p,ranges)
        manifest.append(identity)
        (BASE/'reports'/('si-analysis-'+Path(p).name+'.asm.txt')).write_text(dump)
    (BASE/'reports/si-analysis-inputs.json').write_text(json.dumps(manifest,indent=2)+'\n')

if __name__ == '__main__':
    main()
