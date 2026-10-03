#!/usr/bin/env python3
"""Audit, test and package the load-only experiment without replacing old ZIPs."""
import copy
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path
from audit_native import inspect
from audit_native_probe import check_binary
from formats import config

BASE = Path(__file__).resolve().parents[1]
RESOURCE = BASE.parent / 'resource'
STAGE = BASE / 'preload-probe'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    # v1 shipped with an SD filesystem check the vehicle rejected; v1.1 keeps the v1 layout.
    archive = BASE.parent / 'archive/trial-zips/MU1320-RGI-si-preload-probe-v1.1.zip'
    assert not archive.exists(), 'Never overwrite a shipped archive'
    build = json.loads((BASE / 'reports/preload-probe-build.json').read_text())
    for n, digest in build['files'].items(): assert sha(STAGE / n) == digest, n
    before = config((RESOURCE / 'smartphone_integrator.json').read_text())
    expected = copy.deepcopy(before)
    expected['children']['carplay']['envs'] += ['MU1320_SI_PROBE=' + build['marker'], 'LD_PRELOAD=' + build['library_path']]
    assert config((STAGE / 'smartphone_integrator.json').read_text()) == expected
    inventory = {str(p.relative_to(RESOURCE)): inspect(p) for p in (RESOURCE / 'native-libs').rglob('*.so*') if p.is_file()}
    audits = {name: check_binary(STAGE / name, inventory, shared_init_size=8 if name.endswith('.so') else None)
              for name in ['mount_state', 'loader_check', 'libmu1320_preload_probe.so']}
    assert all(x['status'] == 'STATIC_PASS' for x in audits.values()), audits
    library = inspect(STAGE / 'libmu1320_preload_probe.so')
    assert set(library['exports']) == {'mu1320_preload_probe_identity'}, library['exports']
    assert set(audits['libmu1320_preload_probe.so']['required_symbols']) == {'__get_errno_ptr', 'open', 'write', 'close', 'getpid', 'getppid'}
    assert audits['libmu1320_preload_probe.so']['direct_dependencies'] == ['libc.so.3']
    for name in ['control.sh', 'collect_env.sh', 'preload_probe.sh']:
        subprocess.run(['/bin/sh', '-n', str(STAGE / name)], check=True)
    tests = subprocess.run(['python3', '-m', 'unittest', 'discover', '-s', str(BASE / 'tests'), '-p', 'test_preload_probe*.py', '-v'], capture_output=True, text=True)
    (BASE / 'reports/preload-probe-host-tests.txt').write_text(tests.stdout + tests.stderr)
    assert tests.returncode == 0, tests.stdout + tests.stderr
    names = sorted(p.name for p in STAGE.iterdir() if p.is_file() and p.name != 'SHA256SUMS')
    (STAGE / 'SHA256SUMS').write_text(''.join(f'{sha(STAGE / n)}  {n}\n' for n in names))
    with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED) as z:
        for n in names + ['SHA256SUMS']:
            entry = zipfile.ZipInfo('mu1320-preload-probe-v1/' + n, (2026, 9, 24, 0, 0, 0))
            entry.create_system = 3; entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = (0o100755 if n in ['loader_check', 'mount_state'] else 0o100644) << 16
            z.writestr(entry, (STAGE / n).read_bytes())
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        for n in names + ['SHA256SUMS']: assert z.read('mu1320-preload-probe-v1/' + n) == (STAGE / n).read_bytes()
    report = dict(package=archive.name, sha256=sha(archive), size=archive.stat().st_size, host_tests='PASS', vehicle_tested=False,
                  navigation_hook_included=False, native_audit=audits,
                  host_test_log_sha256=sha(BASE / 'reports/preload-probe-host-tests.txt'),
                  files={n: sha(STAGE / n) for n in names + ['SHA256SUMS']})
    (BASE / 'reports/preload-probe-package.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: report[k] for k in ['package', 'sha256', 'size', 'host_tests', 'vehicle_tested']}, indent=2))
if __name__ == '__main__': main()
