#!/usr/bin/env python3
"""Generate the SD wrapper only after checking native ELF imports and pinned runtime files."""
import hashlib
import json
import subprocess
from pathlib import Path
from audit_native import inspect
from audit_native_probe import check_binary

BASE = Path(__file__).resolve().parents[1]
RESOURCE = BASE.parent / 'resource'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    previous = json.loads((BASE / 'reports/native-probe-audit.json').read_text())
    inventory = {}
    for name, sha in previous['runtime_input_sha256'].items():
        path = RESOURCE / name
        if digest(path) != sha:
            raise ValueError('runtime file changed: ' + name)
        inventory[name] = inspect(path)
    binary = BASE / 'stage0/native_smoke'
    audit = check_binary(binary, inventory)
    assert audit['status'] == 'STATIC_PASS', audit
    assert set(audit['dependency_closure']) == {'libc.so.3', 'libsocket.so.3'}, audit
    # This executable intentionally has no file, configuration, graphics, hook or connection APIs.
    allowed = {'__libc_exit', '__libc_start_main', '_exit', 'exit', 'alarm', 'puts',
               'uname', 'strcmp', 'clock_gettime', 'socket', 'close',
               'confstr', 'printf', 'memset', '__get_errno_ptr',
               'signal', 'sigprocmask', 'sigemptyset', 'sigaddset',
               # QNX CRT startup and cleanup helpers emitted by the toolchain.
               '_init_libc', '_init_array', '_preinit_array', '_fini_array', 'atexit'}
    assert audit['headers']['init_array_size'] == 4, 'unexpected initialization array'
    unexpected = set(audit['required_symbols']) - allowed
    if unexpected:
        raise ValueError('review unexpected strong imports before packaging: ' + repr(sorted(unexpected)))
    mappings = [
        (binary, '"$stage_dir/native_smoke"'),
        (RESOURCE / 'native-libs/proc/boot/libc.so.3', '/proc/boot/libc.so.3'),
        (RESOURCE / 'native-libs/lib/libsocket.so.3', '/lib/libsocket.so.3'),
    ]
    checks = []
    for local, target in mappings:
        crc, size = subprocess.check_output(['cksum', str(local)], text=True).split()[:2]
        checks.append('check_file ' + crc + ' ' + size + ' ' + target + ' || exit 1')
    template = (BASE / 'scripts/run_stage0.sh.in').read_text()
    assert template.count('@CHECKS@') == 1
    (BASE / 'stage0/run_stage0.sh').write_text(template.replace('@CHECKS@', '\n'.join(checks)))
    report = {'deploys_rgi': False, 'vehicle_execution_tested': False,
              'source_sha256': digest(BASE / 'stage0/native_smoke.c'),
              'wrapper_sha256': digest(BASE / 'stage0/run_stage0.sh'),
              'binary': audit,
              'strong_import_allowlist_passed': True,
              'scope': 'standalone libc/socket/basic floating point checks; no persistent configuration changes'}
    (BASE / 'reports/stage0-audit.json').write_text(json.dumps(report, indent=2) + '\n')
    print('Stage 0 wrapper generated; ELF and strong-import allowlist passed.')


if __name__ == '__main__':
    main()
