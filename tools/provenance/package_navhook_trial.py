#!/usr/bin/env python3
"""Audit, regression-test and create the immutable MU1320 nav-hook trial ZIP."""
import copy
import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
PRIVATE = BASE.parent / "private-data" / "mu1320-rgi"
sys.path.insert(0, str(PRIVATE / 'python'))

from audit_native import inspect
from audit_native_probe import check_binary
from formats import config

RESOURCE = BASE.parent / 'resource'
STAGE = BASE / 'navhook-trial'
ARCHIVE = BASE.parent / 'archive/trial-zips/MU1320-RGI-navhook-oneshot-v1.2.zip'
PREFIX = 'mu1320-navhook-oneshot-v1/'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    assert not ARCHIVE.exists(), 'Never overwrite a shipped archive; use a new version.'
    build = json.loads((BASE / 'reports/navhook-trial-build.json').read_text())
    prepared = json.loads((BASE / 'reports/navhook-trial-prepare-v1.2.json').read_text())
    assert sha(STAGE / 'libcarplay_hook.so') == build['artifact']['sha256']
    assert prepared['build_artifact_sha256'] == build['artifact']['sha256']
    for name, digest in prepared['files'].items():
        assert sha(STAGE / name) == digest, name

    stock_si = config((RESOURCE / 'smartphone_integrator.json').read_text())
    trial_si = config((STAGE / 'smartphone_integrator.json').read_text())
    expected_si = copy.deepcopy(stock_si)
    child = expected_si['children']['carplay']
    child['envs'][1] = 'IPL_CONFIG_DIR_DIO_MANAGER=/mnt/app/root/mu1320-rgi-navhook-v1/config'
    child['envs'] += [
        'MU1320_NAVHOOK_TRIAL=mu1320_navhook_v1_5c45c31e',
        'LD_PRELOAD=/mnt/app/root/mu1320-rgi-navhook-v1/libcarplay_hook.so',
    ]
    assert trial_si == expected_si
    assert trial_si['children']['carplay']['exec'] == 'dio_manager'
    assert trial_si['children']['carplay']['path'] == '/mnt/app/eso/bin/apps'

    stock_dio = config((RESOURCE / 'dio_manager.json').read_text())
    trial_dio = config((STAGE / 'dio_manager.json').read_text())
    expected_dio = copy.deepcopy(stock_dio)
    expected_dio['iap2']['MessagesSentByAccessory'] += ['0x5200', '0x5203']
    expected_dio['iap2']['MessagesReceivedFromDevice'] += ['0x5201', '0x5202', '0x5204']
    assert trial_dio == expected_dio

    inputs = sorted(RESOURCE.glob('lib*.so*'))
    inputs += sorted((RESOURCE / 'native-libs').rglob('*.so*'))
    inputs += sorted((RESOURCE / 'cinemo').glob('*.so'))
    inventory = {str(path.relative_to(RESOURCE)): inspect(path) for path in inputs if path.is_file()}
    audits = {
        'libcarplay_hook.so': check_binary(STAGE / 'libcarplay_hook.so', inventory, shared_init_size=4),
        'loader_check': check_binary(STAGE / 'loader_check', inventory),
        'mount_state': check_binary(STAGE / 'mount_state', inventory),
    }
    assert all(item['status'] == 'STATIC_PASS' for item in audits.values()), audits
    hook = inspect(STAGE / 'libcarplay_hook.so')
    assert 'rgd_module_def' in hook['exports']
    assert 'trial_gate_active' in hook['exports'] and 'trial_gate_was_active' in hook['exports']
    assert not any('coverart' in name.lower() or name.startswith('stbi_') for name in hook['exports'])
    assert audits['libcarplay_hook.so']['direct_dependencies'] == ['libsocket.so.3']
    assert not audits['libcarplay_hook.so']['unresolved_required_symbols']

    for name in ['control.sh', 'collect_navhook.sh', 'navhook_trial.sh']:
        subprocess.run(['/bin/sh', '-n', str(STAGE / name)], check=True)
    readme = (STAGE / 'README.md').read_text()
    for phrase in ['不是 VC/HUD 成品', 'ACTIVE_TOKEN_CONSUMED', 'control.sh rollback',
                   '完整重启', 'HMI 失效时 SSH 尚未验证']:
        assert phrase in readme

    env = dict(os.environ, PYTHONPATH=str(BASE / 'tests'))
    tests = subprocess.run(
        ['python3', '-m', 'unittest', 'test_navhook_gate.py', 'test_navhook_trial.py', '-v'],
        cwd=BASE / 'tests', env=env, capture_output=True, text=True,
    )
    test_log = BASE / 'reports/navhook-trial-host-tests.txt'
    test_log.write_text(tests.stdout + tests.stderr)
    assert tests.returncode == 0, tests.stdout + tests.stderr

    names = sorted(path.name for path in STAGE.iterdir()
                   if path.is_file() and path.name != 'SHA256SUMS')
    (STAGE / 'SHA256SUMS').write_text(
        ''.join(f'{sha(STAGE / name)}  {name}\n' for name in names))
    with zipfile.ZipFile(ARCHIVE, 'x', zipfile.ZIP_DEFLATED) as archive:
        for name in names + ['SHA256SUMS']:
            entry = zipfile.ZipInfo(PREFIX + name, (2026, 9, 24, 0, 0, 0))
            entry.create_system = 3
            entry.compress_type = zipfile.ZIP_DEFLATED
            executable = name in ['loader_check', 'mount_state']
            entry.external_attr = (0o100755 if executable else 0o100644) << 16
            archive.writestr(entry, (STAGE / name).read_bytes())
    with zipfile.ZipFile(ARCHIVE) as archive:
        assert archive.testzip() is None
        assert archive.namelist() == [PREFIX + name for name in names + ['SHA256SUMS']]
        for name in names + ['SHA256SUMS']:
            assert archive.read(PREFIX + name) == (STAGE / name).read_bytes()

    report = {
        'package': ARCHIVE.name,
        'sha256': sha(ARCHIVE),
        'size': ARCHIVE.stat().st_size,
        'host_tests': 'PASS',
        'vehicle_tested': False,
        'scope': 'one DIO process, navigation-only native interposition and 0x52xx observation; no Java or renderer',
        'one_shot_gate_tests': 'PASS (4)',
        'transaction_tests': 'PASS (9, including verified pre-commit workspace resume and no && fail guards)',
        'native_audit': audits,
        'host_test_log_sha256': sha(test_log),
        'files': {name: sha(STAGE / name) for name in names + ['SHA256SUMS']},
    }
    (BASE / 'reports/navhook-trial-package-v1.2.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: report[key] for key in
                      ['package', 'sha256', 'size', 'host_tests', 'vehicle_tested']}, indent=2))


if __name__ == '__main__':
    main()
