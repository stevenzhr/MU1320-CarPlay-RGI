#!/usr/bin/env python3
"""Audit returned Stage4 evidence without trusting collector verdict strings."""
import hashlib
import json
import re
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
OUT = BASE.parent / 'resource/private/vehicle-dump/preload-probe-v1-out/out'
REPORT = BASE / 'reports/preload-probe-vehicle-v1.json'
MARKER = 'MU1320_SI_PROBE=mu1320_preload_v1_b81d024a'
PRELOAD = 'LD_PRELOAD=/mnt/app/root/mu1320-preload-probe-v1/libmu1320_preload_probe.so'
BASELINE = ('535418540', '7359')
PATCHED = ('2782255039', '7484')

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def one(pattern):
    matches = sorted(OUT.glob(pattern))
    assert len(matches) == 1, (pattern, matches)
    return matches[0]
def read(path): return path.read_text(errors='replace')
def configs(text):
    found = re.findall(r'^\s*(\d+)\s+(\d+)\s+/(?:mnt/system/)?etc/eso/production/smartphone_integrator\.json$', text, re.M)
    assert len(found) == 2, found
    return [tuple(x) for x in found]
def process(text, role):
    blocks = re.findall(r'PROCESS_BEGIN: role=' + role + r' pid=(\d+)\n(.*?)\nPROCESS_END', text, re.S)
    assert len(blocks) <= 1, blocks
    if not blocks: return None
    pid, block = blocks[0]
    identity = re.search(r'^\s*' + pid + r'\s+(\d+)\s+(\S*' + ('dio_manager' if role == 'DIO' else 'smartphone_integrator') + r')\s+(.+)$', block, re.M)
    assert identity, (role, pid)
    env = re.search(r'ENVIRONMENT_BEGIN: exit=(\d+).*?\n(.*?)\nENVIRONMENT_END', block, re.S)
    assert env and env.group(1) == '0' and re.search(r'^\s*' + pid + r'\s+', env.group(2), re.M)
    receipt = re.search(r'PRELOAD_RECEIPT_BEGIN\n(.*?)\nPRELOAD_RECEIPT_END', block, re.S)
    mmap = re.search(r'MEMORY_MAP_BEGIN\nMEMORY_MAP_EXIT=(\d+)\n(.*?)\nMEMORY_MAP_END', block, re.S)
    assert receipt and mmap and mmap.group(1) == '0'
    return {'pid': pid, 'ppid': identity.group(1), 'name': identity.group(2),
            'start': identity.group(3).strip(), 'environment': env.group(2),
            'receipt': receipt.group(1).strip(), 'memory_map': mmap.group(2)}

def phase(name, expected_config, directory=None):
    directory = directory or one(name + '-*')
    text = read(directory / 'collect.txt')
    assert configs(text) == [expected_config, expected_config]
    si = process(text, 'SI'); dio = process(text, 'DIO')
    assert si and MARKER not in si['environment'] and PRELOAD not in si['environment']
    if dio:
        assert dio['ppid'] == si['pid']
        env_file = one(directory.name + '/DIO-' + dio['pid'] + '-environment.txt')
        assert read(env_file).strip() in text
    return {'directory': directory.name, 'collect_sha256': sha(directory / 'collect.txt'),
            'config': {'crc': expected_config[0], 'size': int(expected_config[1])},
            'si': {k: v for k, v in si.items() if k not in ('environment', 'memory_map')},
            'dio': None if not dio else {
                'pid': dio['pid'], 'ppid': dio['ppid'], 'start': dio['start'],
                'marker': MARKER in dio['environment'], 'preload_env': PRELOAD in dio['environment'],
                'receipt': dio['receipt'],
                'receipt_matches_identity': dio['receipt'] == f'MU1320_PRELOAD_V1_LOADED pid={dio["pid"]} ppid={dio["ppid"]}',
                'mapped_probe_name_truncated': '0_preload_probe.so' in dio['memory_map'],
                'identity_stable': text.count(dio['pid'] + '  ' + dio['ppid']) >= 2}}

def main():
    before = phase('before', BASELINE)
    marked = phase('marked', PATCHED)
    restored_dirs = sorted(OUT.glob('restored-*'))
    assert restored_dirs
    # A first restored capture may precede USB/DIO startup. Prefer the returned
    # capture that actually contains a live DIO; retain every input hash below.
    restored_dir = next((d for d in reversed(restored_dirs)
                         if 'DIO_PROCESSES_OBSERVED=1' in read(d / 'collect.txt')),
                        restored_dirs[-1])
    restored = phase('restored', BASELINE, restored_dir)
    b, m = before['dio'], marked['dio']
    assert b and not b['marker'] and not b['preload_env'] and b['receipt'] == 'NO_RECEIPT'
    assert m and m['marker'] and m['preload_env'] and m['receipt_matches_identity'] and m['mapped_probe_name_truncated'] and m['identity_stable']
    install = read(one('action-install-*.txt')); rollback = read(one('action-rollback-*.txt'))
    assert 'PRELOAD_PROBE_STANDALONE_PASSED' in install
    assert 'PRELOAD_PROBE_install_FILES_PASSED' in install and 'MOUNTS_RESTORED: app=ro system=ro' in install
    assert 'PRELOAD_PROBE_rollback_FILES_PASSED' in rollback and 'MOUNTS_RESTORED: app=ro system=ro' in rollback
    restored_text = read(OUT / restored['directory'] / 'collect.txt')
    full_boot_support = all(x in restored_text for x in [
        'RAM_WITNESS_ABSENT: /tmp/mu1320-preload-probe-v1-install-witness',
        'RAM_WITNESS_ABSENT: /tmp/mu1320-preload-probe-v1-rollback-witness'])
    runtime_rollback = bool(restored['dio'] and not restored['dio']['marker'] and
                            not restored['dio']['preload_env'] and restored['dio']['receipt'] == 'NO_RECEIPT')
    result = {
        'status': 'PRELOAD_LOADING_VERIFIED_RUNTIME_ROLLBACK_OBSERVATION_PENDING' if not runtime_rollback else 'PRELOAD_LOADING_AND_RUNTIME_ROLLBACK_VERIFIED',
        'vehicle_preload_loading_verified': True,
        'navigation_hook_loaded': False,
        'file_rollback_verified': True,
        'full_boot_after_rollback_supported': full_boot_support,
        'runtime_rollback_verified_with_live_dio': runtime_rollback,
        'restored_limitation': None if runtime_rollback else 'No live dio_manager or children PID file existed in restored capture; collect exit 0 only establishes successful collection.',
        'phases': {'before': before, 'marked': marked, 'restored': restored},
        'restored_inputs': {d.name: sha(d / 'collect.txt') for d in restored_dirs},
        'actions': {'install_sha256': sha(one('action-install-*.txt')), 'rollback_sha256': sha(one('action-rollback-*.txt'))},
        'interpretation': [
            'The marked DIO was a live direct SI child and had both exact env entries.',
            'The same DIO identity wrote the constructor receipt and had the probe library in its memory map.',
            'These independent signals establish actual LD_PRELOAD loading, not merely environment propagation.',
            'This experiment did not load libcarplay_hook.so and does not validate Cinemo interposition or route guidance.'
        ]}
    REPORT.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: result[k] for k in ['status', 'vehicle_preload_loading_verified', 'file_rollback_verified', 'runtime_rollback_verified_with_live_dio']}, indent=2))
if __name__ == '__main__': main()
