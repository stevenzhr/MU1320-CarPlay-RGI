#!/usr/bin/env python3
"""Generate REVIEW copies only; no head-unit access and no installation."""
import argparse
import copy
import difflib
import hashlib
import json
import re
from pathlib import Path
from formats import config, uncomment

BASE = Path(__file__).resolve().parents[1]
SOURCE = BASE.parent / 'resource'


def add_ids(text):
    before = config(text)
    expected = copy.deepcopy(before)
    for key, extra in [('MessagesSentByAccessory', ['0x5200', '0x5203']),
                       ('MessagesReceivedFromDevice', ['0x5201', '0x5202', '0x5204'])]:
        # Exact object path, no recursive best-guess patching.
        old = expected['iap2'][key]
        if not isinstance(old, list) or any(not isinstance(x, str) for x in old):
            raise ValueError('unexpected iap2 message list')
        numbers = [int(x, 16) for x in old]
        if len(numbers) != len(set(numbers)):
            raise ValueError('duplicate iAP2 ID: ' + key)
        additions = [x for x in extra if int(x, 16) not in numbers]
        expected['iap2'][key] += additions
        matches = list(re.finditer(r'"' + key + r'"\s*:\s*\[([^\]]*)\]', uncomment(text)))
        if len(matches) != 1:
            raise ValueError('ambiguous message list: ' + key)
        if additions:
            at = matches[0].end() - 1
            text = text[:at] + (', ' if old[:-len(additions)] else '') + ', '.join(json.dumps(x) for x in additions) + text[at:]
    if config(text) != expected:
        raise ValueError('unexpected semantic change')
    return text


def prepare(source, dest, manifest):
    recorded = json.loads(manifest.read_text())['files']
    for name in ['dio_manager.json', 'smartphone_integrator.json']:
        data = (source/name).read_bytes()
        if hashlib.sha256(data).hexdigest() != recorded[name]['sha256']:
            raise ValueError('input differs from audited baseline: ' + name)
    dest.mkdir(parents=True, exist_ok=True)
    original = (source/'dio_manager.json').read_text()
    patched = add_ids(original)
    (dest/'dio_manager.json.REVIEW').write_text(patched)
    # Keep the stock watchdog, timeouts, environment and cleanup script.
    si = config((source/'smartphone_integrator.json').read_text())
    child = copy.deepcopy(si['children']['carplay'])
    if child['exec'] != 'dio_manager' or child['path'] != '/mnt/app/eso/bin/apps':
        raise ValueError('non-stock child; manual review required')
    if any(e.startswith('LD_PRELOAD=') for e in child['envs']):
        raise ValueError('existing preload; manual review required')
    child['exec'] = 'carplay_startup_mu1320.sh'
    child['path'] = '/mnt/app/root/mu1320-rgi'
    (dest/'carplay-child.json.REVIEW').write_text(json.dumps(child, indent=2)+'\n')
    diff = ''.join(difflib.unified_diff(original.splitlines(True), patched.splitlines(True),
                                      fromfile='stock/dio_manager.json', tofile='review/dio_manager.json'))
    (dest/'dio-manager.diff').write_text(diff)
    print('REVIEW ONLY: no release binaries, no activation, no head-unit writes.')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, default=SOURCE)
    p.add_argument('--out', type=Path, default=BASE/'candidate')
    p.add_argument('--manifest', type=Path, default=BASE/'reports/input-manifest.json')
    a = p.parse_args()
    prepare(a.source, a.out, a.manifest)
