"""Read GNU symbol versions via PT_DYNAMIC, including stripped QNX IFS libraries."""
import struct
from elftools.elf.elffile import ELFFile
from elftools.elf.dynamic import DynamicSegment


def read_versions(path):
    raw = path.read_bytes()
    with path.open('rb') as stream:
        elf = ELFFile(stream)
        if elf.elfclass != 32 or not elf.little_endian:
            raise ValueError('expected ELF32 little-endian: ' + str(path))
        loads = [s for s in elf.iter_segments() if s['p_type'] == 'PT_LOAD']
        dynamic = next(s for s in elf.iter_segments() if isinstance(s, DynamicSegment))
        tags = {t.entry.d_tag: t.entry.d_val for t in dynamic.iter_tags()}
        symbols = list(dynamic.iter_symbols())

        def offset(address, size):
            for segment in loads:
                delta = address - segment['p_vaddr']
                if 0 <= delta and delta + size <= segment['p_filesz']:
                    return segment['p_offset'] + delta
            raise ValueError('version address outside file-backed load segment')

        def unpack(fmt, address):
            return struct.unpack_from(fmt, raw, offset(address, struct.calcsize(fmt)))

        def string(index):
            if not 0 <= index < tags['DT_STRSZ']:
                raise ValueError('bad version string index')
            start = offset(tags['DT_STRTAB'] + index, 1)
            end = raw.index(b'\0', start, start + tags['DT_STRSZ'] - index)
            return raw[start:end].decode('utf-8')

        required_indices, defined_indices = {}, {}
        address = tags.get('DT_VERNEED', 0)
        for _ in range(tags.get('DT_VERNEEDNUM', 0)):
            version, count, file_index, aux, following = unpack('<HHIII', address)
            if version != 1:
                raise ValueError('unsupported version need record')
            auxiliary = address + aux
            for _ in range(count):
                _, flags, index, name, next_aux = unpack('<IHHII', auxiliary)
                required_indices[index & 0x7fff] = {'library': string(file_index),
                                                  'version': string(name), 'flags': flags}
                auxiliary += next_aux
            address += following
        address = tags.get('DT_VERDEF', 0)
        for _ in range(tags.get('DT_VERDEFNUM', 0)):
            version, _, index, count, _, aux, following = unpack('<HHHHIII', address)
            if version != 1 or not count:
                raise ValueError('unsupported version definition record')
            name, _ = unpack('<II', address + aux)
            defined_indices[index & 0x7fff] = string(name)
            address += following
        requirements, definitions = {}, {}
        if 'DT_VERSYM' in tags:
            for i, symbol in enumerate(symbols):
                index = unpack('<H', tags['DT_VERSYM'] + i * 2)[0] & 0x7fff
                if not symbol.name or index <= 1:
                    continue
                if symbol['st_shndx'] == 'SHN_UNDEF':
                    requirements[symbol.name] = required_indices[index]
                elif symbol['st_info']['bind'] in ('STB_GLOBAL', 'STB_WEAK') and symbol['st_other']['visibility'] in ('STV_DEFAULT', 'STV_PROTECTED'):
                    definitions.setdefault(symbol.name, []).append(defined_indices[index])
        return {'requirements': requirements, 'definitions': definitions}
