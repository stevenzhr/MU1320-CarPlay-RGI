#!/usr/bin/env python3
"""Audit the second MU1320 dump. No vehicle access; raw process logs stay private."""
import hashlib
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
RESOURCE = BASE.parent / 'resource'
HOOKS = {
    'Decode': '_ZN14NmeIAP2Message6DecodeEPKhi',
    'Encode': '_ZNK14NmeIAP2Message6EncodeER8NmeArrayIhE',
    'Send': '_ZN12NmeTransport4SendEPKhjPj',
    'Recv': '_ZN12NmeTransport4RecvER8NmeArrayIhE',
}


def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def parse_displays(text):
    result = {}
    for m in re.finditer(r'^\s*(-?\d+)\s+(Overlay|Software|Image)\s+(\d+)\s*x\s*(\d+)', text, re.M):
        result[m[1]] = {'type': m[2], 'width': int(m[3]), 'height': int(m[4])}
    return result


def main():
    from audit_native import inspect
    paths = sorted(RESOURCE.glob('lib*.so*')) + [RESOURCE/'dio_manager', RESOURCE/'dmdt']
    paths += sorted((RESOURCE/'cinemo').glob('*.so'))
    paths += sorted((RESOURCE/'native-libs').rglob('*.so*'))
    # Full relative path is required: /proc/boot and /mnt/app have different libc/libm.
    inventory = {str(p.relative_to(RESOURCE)): inspect(p) for p in paths if p.is_file()}
    plugin = inventory['cinemo/libNmeVfs.so']
    seams = {}
    for label, symbol in HOOKS.items():
        seams[label] = {
            'symbol': symbol,
            'plugin_relocations': [r for r in plugin['relocations'] if r['name'] == symbol],
            'providers': {n: x['exports'][symbol] for n, x in inventory.items() if symbol in x['exports']},
        }
    disassembly = subprocess.check_output(['objdump', '-d', str(RESOURCE/'cinemo/libNmeVfs.so')], text=True)
    for seam in seams.values():
        seam['direct_calls_to_plt'] = [line.strip() for line in disassembly.splitlines()
                                       if '<'+seam['symbol']+'@plt>' in line and re.search(r'\s(?:bl|b)\s', line)]
    sonames = {s for x in inventory.values() for s in x['dynamic'].get('DT_SONAME', [])}
    missing = {n: [s for s in x['dynamic'].get('DT_NEEDED', []) if s not in sonames]
               for n, x in inventory.items()}
    missing = {n: ss for n, ss in missing.items() if ss}
    duplicates = {}
    for n, x in inventory.items():
        for so in x['dynamic'].get('DT_SONAME', []):
            duplicates.setdefault(so, []).append({'path': n, 'sha256': x['sha256'], 'size': x['size']})
    duplicates = {k: v for k, v in duplicates.items() if len(set(x['sha256'] for x in v)) > 1}
    xml = ET.parse(RESOURCE/'cinemo/cinemo_classes.xml')
    factory = [{'class_id': c.findtext('class_id'), 'create': c.findtext('create'),
                'create_dll': c.findtext('create_dll')} for c in xml.iter('class')
               if c.findtext('class_id') == 'NmeIAPDevice']
    logs = RESOURCE/'private/vehicle-dump'
    collected = (logs/'collect_readonly.txt').read_text()
    gd, gs = (logs/'dmdt_gd.txt').read_text(), (logs/'dmdt_gs.txt').read_text()
    config_checks = {}
    for name in ['dio_manager.json', 'smartphone_integrator.json']:
        host = subprocess.check_output(['cksum', str(RESOURCE/name)], text=True).split()[:2]
        sampled = {}
        for prefix in ['/etc/eso/production/', '/mnt/system/etc/eso/production/']:
            m = re.search(r'^\s*(\d+)\s+(\d+)\s+'+re.escape(prefix+name)+r'\s*$', collected, re.M)
            sampled[prefix+name] = list(m.groups()) if m else None
        config_checks[name] = {'workstation_cksum': host, 'vehicle_samples': sampled,
                               'samples_match_workstation': all(v == host for v in sampled.values()),
                               'alias_proven': False}
    old = json.loads((BASE/'reports/input-manifest.json').read_text())['files']
    old_changes = [n for n, v in old.items() if digest(RESOURCE/n) != v['sha256']]
    plugin_sizes = {}
    for p in sorted((RESOURCE/'cinemo').iterdir()):
        if p.suffix not in ('.so', '.xml'): continue
        ms = re.findall(r'^-\S+\s+\d+\s+root\s+root\s+(\d+)\s+[^\n]*\s'+re.escape(p.name)+r'\s*$', collected, re.M)
        plugin_sizes[p.name] = {'size': p.stat().st_size,
                                'vehicle_size_matches': bool(ms) and all(int(x) == p.stat().st_size for x in ms)}
    passed = all(any(r['type'] == 22 for r in x['plugin_relocations']) and x['direct_calls_to_plt']
                 for x in seams.values())
    result = {
        'date': '2026-09-22', 'native_interposition_static_evidence': 'PASS' if passed else 'FAIL',
        'runtime_interposition_tested': False, 'elf_file_count': len(inventory),
        'hook_seams': seams, 'iap_factory_registration': factory,
        'plugin_has_DT_SYMBOLIC': 'DT_SYMBOLIC' in plugin['dynamic'],
        'unprovided_dependencies': missing, 'different_files_same_soname': duplicates,
        'graphics_displayables': parse_displays(gd),
        'cluster_context_74_observed': bool(re.search(r'Cluster Display[\s\S]*context id:\s*74', gs)),
        'context_74_layer_order': [20, 102, 101, 33] if re.search(r'context id:\s*74\s+20[^\n]*\n\s*102[^\n]*\n\s*101[^\n]*\n\s*33', gs) else None,
        'qnx_6_5_armle_observed': bool(re.search(r'^QNX mmx 6\.5\.0 .* armle$', collected, re.M)),
        'armle_alias_confirmed': '/armle -> /mnt/app/armle' in collected,
        'live_HMI_stock_JXE': '-jxe:/ifs/lsd.jxe' in collected,
        'live_HMI_NavActiveIgnore_loaded': '/jars/NavActiveIgnore.jar:' in collected,
        'live_dio_manager_observed': bool(re.search(r'^\s*\d+\s+/mnt/app/eso/bin/apps/dio_manager\s*$', collected, re.M)),
        'configuration_identity': config_checks,
        'previous_input_changes': old_changes,
        'plugin_listing_comparison': plugin_sizes,
        'limitations': ['Static PLT/branch evidence is not an on-unit LD_PRELOAD test.',
                        'Equal cksum/content does not prove two paths are aliases.',
                        'Same SONAME does not prove active library selection; retain path identities.',
                        'No QNX build toolchain or verified independent recovery was supplied.'],
    }
    (BASE/'reports/supplement-audit.json').write_text(json.dumps(result, indent=2)+'\n')
    new_paths = sorted(p for p in RESOURCE.rglob('*') if p.is_file() and
                       (str(p.relative_to(RESOURCE)) not in old or str(p.relative_to(RESOURCE)) in old_changes)
                       and p.name != '.DS_Store')
    manifest = {'date': '2026-09-22', 'privacy': 'raw process log is private and not included in packages',
                'files': {str(p.relative_to(RESOURCE)): {'size': p.stat().st_size, 'sha256': digest(p)} for p in new_paths}}
    (BASE/'reports/supplement-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print('ELFs:', len(inventory), 'critical PLT/branch evidence:', result['native_interposition_static_evidence'])
    print('Configurations match samples:', all(x['samples_match_workstation'] for x in config_checks.values()))
    print('Original input changes:', old_changes)
    print('Different same-SONAME files:', list(duplicates))
    print('Missing dependencies:', missing)
    return 0 if passed else 1


if __name__ == '__main__': raise SystemExit(main())
