#!/usr/bin/env python3
"""Check built ARM ELF files against collected runtime exports without executing them."""
import argparse
import json
from pathlib import Path

from elftools.elf.elffile import ELFFile
from elftools.elf.dynamic import DynamicSegment
from audit_native import inspect
from elf_versions import read_versions

BASE = Path(__file__).resolve().parents[1]
PRIVATE = BASE.parent / "private-data" / "mu1320-rgi"
RESOURCE = BASE.parent / 'resource'


def check_binary(path, inventory, shared_init_size=None):
    info = inspect(path)
    by_soname = {}
    for name, lib in inventory.items():
        for soname in lib['dynamic'].get('DT_SONAME', []):
            by_soname.setdefault(soname, []).append((name, lib))
    pending = list(info['dynamic'].get('DT_NEEDED', []))
    closure, missing = set(), set()
    while pending:
        soname = pending.pop()
        if soname in closure:
            continue
        closure.add(soname)
        if soname not in by_soname:
            missing.add(soname)
        for _, lib in by_soname.get(soname, []):
            pending.extend(lib['dynamic'].get('DT_NEEDED', []))
    with path.open('rb') as stream:
        elf = ELFFile(stream)
        dynamic = next(s for s in elf.iter_segments() if isinstance(s, DynamicSegment))
        symbols = list(dynamic.iter_symbols())
        undefined = sorted({s.name for s in symbols if s.name and s['st_shndx'] == 'SHN_UNDEF'
                            and s['st_info']['bind'] == 'STB_GLOBAL'})
        weak = sorted({s.name for s in symbols if s.name and s['st_shndx'] == 'SHN_UNDEF'
                       and s['st_info']['bind'] == 'STB_WEAK'})
        headers = {'type': elf['e_type'], 'flags': elf['e_flags'],
                   'interpreter': next((s.get_interp_name() for s in elf.iter_segments()
                                        if s['p_type'] == 'PT_INTERP'), None)}
        init = elf.get_section_by_name('.init_array')
        headers['init_array_size'] = init['sh_size'] if init else 0
    providers = {}
    for symbol in undefined:
        # Conservative: a SONAME is acceptable only if every collected variant
        # exports this symbol. Actual runtime search order still needs verification.
        providers[symbol] = [soname for soname in sorted(closure)
                             if by_soname.get(soname) and all(
                                 symbol in lib['exports'] and lib['exports'][symbol]['visibility'] in
                                 ('STV_DEFAULT', 'STV_PROTECTED') for _, lib in by_soname[soname])]
    unresolved = [symbol for symbol, libs in providers.items() if not libs]
    versions = read_versions(path)
    version_checks = {}
    for symbol, need in versions['requirements'].items():
        candidates = by_soname.get(need['library'], [])
        version_checks[symbol] = {
            **need,
            'providers': {name: need['version'] in read_versions(RESOURCE / name)['definitions'].get(symbol, [])
                          for name, _ in candidates}}
    versions_passed = all(v['providers'] and all(v['providers'].values()) for v in version_checks.values())
    arm_eabi_soft = (info['class'] == 32 and info['little_endian'] and info['machine'] == 'EM_ARM'
                     and headers['flags'] & 0xff000000 == 0x05000000
                     and not headers['flags'] & 0x400)
    hook = path.name == 'libcarplay_hook.so'
    shape = (headers['type'] == 'ET_DYN' and headers['init_array_size'] == (shared_init_size if shared_init_size is not None else 4)) if (hook or shared_init_size is not None) else (
        headers['type'] == 'ET_EXEC' and headers['interpreter'] == '/usr/lib/ldqnx.so.2')
    emutls = [s.name for s in symbols if 'emutls' in s.name]
    passed = arm_eabi_soft and shape and not missing and not unresolved and not emutls and versions_passed
    return {'status': 'STATIC_PASS' if passed else 'STATIC_FAIL_OR_UNRESOLVED',
            'sha256': info['sha256'], 'size': info['size'], 'headers': headers,
            'arm_eabi5_without_hard_float_flag': arm_eabi_soft,
            'expected_elf_shape': shape, 'emutls_dynamic_symbols': emutls,
            'direct_dependencies': info['dynamic'].get('DT_NEEDED', []),
            'dependency_closure': sorted(closure), 'missing_dependencies': sorted(missing),
            'required_symbols': providers, 'unresolved_required_symbols': unresolved,
            'optional_weak_symbols': weak,
            'versioned_symbol_checks': version_checks, 'version_requirements_satisfied': versions_passed,
            'multiple_collected_variants': {s: [n for n, _ in by_soname[s]] for s in sorted(closure)
                                           if len(by_soname.get(s, [])) > 1},
            'limitations': ['ELF header checks do not validate all ARM attributes or calling conventions.',
                            'Export names and versions do not establish implementation ABI or loader scope.',
                            'Runtime library selection, interposition and screen behavior remain untested.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, default=PRIVATE / 'native-probe')
    args = parser.parse_args()
    files = sorted(RESOURCE.glob('lib*.so*')) + sorted((RESOURCE / 'native-libs').rglob('*.so*'))
    files += sorted((RESOURCE / 'cinemo').glob('*.so'))
    inventory = {str(p.relative_to(RESOURCE)): inspect(p) for p in files if p.is_file()}
    result = {'deployable': False, 'runtime_tested': False,
              'runtime_input_sha256': {name: info['sha256'] for name, info in inventory.items()},
              'artifacts': {name: check_binary(args.build / 'src/build' / name, inventory)
                            for name in ('libcarplay_hook.so', 'maneuver_render')}}
    out = args.build / 'elf-audit.json'
    out.write_text(json.dumps(result, indent=2) + '\n')
    for name, info in result['artifacts'].items():
        print(name, info['status'], 'missing=', info['missing_dependencies'],
              'unresolved=', info['unresolved_required_symbols'])
    return 0 if all(x['status'] == 'STATIC_PASS' for x in result['artifacts'].values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
