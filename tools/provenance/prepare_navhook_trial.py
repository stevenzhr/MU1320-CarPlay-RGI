#!/usr/bin/env python3
"""Generate the gated, navigation-only MU1320 vehicle trial.

The generated SI candidate keeps the stock executable and path.  It changes
only the DIO config directory and appends a marker plus LD_PRELOAD.  The DIO
candidate adds exactly the five CarPlay route-guidance message identifiers.
"""
import copy
import difflib
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

from formats import config
from prepare_configs import add_ids

BASE = Path(__file__).resolve().parents[1]
PRIVATE = BASE.parent / "private-data" / "mu1320-rgi"
RESOURCE = BASE.parent / 'resource'
STAGE = BASE / 'navhook-trial'
BUILD = PRIVATE / 'navhook-v1-build/src/build'
RUNTIME = '/mnt/app/root/mu1320-rgi-navhook-v1'
HOOK = RUNTIME + '/libcarplay_hook.so'
CONFIG_DIR = RUNTIME + '/config'
MARKER = 'mu1320_navhook_v1_5c45c31e'
IMAGE = 'sha256:e52565b1f62dab0f93f12532d52611b94e90b89e4da04f972b11f54eaeb6a05d'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def crc(path):
    return subprocess.check_output(['cksum', str(path)], text=True).split()[:2]


def replace_once(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new)


def main():
    assert not STAGE.exists(), 'Preserve an existing generated trial; remove it explicitly before regeneration.'
    build = json.loads((BASE / 'reports/navhook-trial-build.json').read_text())
    assert build['image_id'] == IMAGE
    assert sha(BUILD / 'libcarplay_hook.so') == build['artifact']['sha256']
    assert build['scope'].startswith('navigation-only')
    STAGE.mkdir()

    stock_si = RESOURCE / 'smartphone_integrator.json'
    stock_dio = RESOURCE / 'dio_manager.json'
    assert sha(stock_si) == 'dd7bf2233198eaf26d7fefc0f01f459c1ce291e0d881eb0b9beeb2ecf4d1055d'
    source = stock_si.read_text()
    begin = source.index('"carplay":{')
    end = source.index('"carlife":{', begin)
    carplay_text = source[begin:end]
    old_env = '"IPL_CONFIG_DIR_DIO_MANAGER=/etc/eso/production"]'
    new_env = ('"IPL_CONFIG_DIR_DIO_MANAGER=' + CONFIG_DIR + '", '
               '"MU1320_NAVHOOK_TRIAL=' + MARKER + '", '
               '"LD_PRELOAD=' + HOOK + '"]')
    carplay_text = replace_once(carplay_text, old_env, new_env)
    patched_si = source[:begin] + carplay_text + source[end:]

    expected_si = copy.deepcopy(config(source))
    child = expected_si['children']['carplay']
    assert child['exec'] == 'dio_manager' and child['path'] == '/mnt/app/eso/bin/apps'
    assert not any(x.startswith('LD_PRELOAD=') for x in child['envs'])
    child['envs'] = [('IPL_CONFIG_DIR_DIO_MANAGER=' + CONFIG_DIR)
                     if x == 'IPL_CONFIG_DIR_DIO_MANAGER=/etc/eso/production' else x
                     for x in child['envs']]
    child['envs'] += ['MU1320_NAVHOOK_TRIAL=' + MARKER, 'LD_PRELOAD=' + HOOK]
    assert config(patched_si) == expected_si
    actual_child = config(patched_si)['children']['carplay']
    assert actual_child['exec'] == 'dio_manager' and actual_child['path'] == '/mnt/app/eso/bin/apps'
    (STAGE / 'smartphone_integrator.json').write_text(patched_si)

    patched_dio = add_ids(stock_dio.read_text())
    before_dio, after_dio = config(stock_dio.read_text()), config(patched_dio)
    expected_dio = copy.deepcopy(before_dio)
    expected_dio['iap2']['MessagesSentByAccessory'] += ['0x5200', '0x5203']
    expected_dio['iap2']['MessagesReceivedFromDevice'] += ['0x5201', '0x5202', '0x5204']
    assert after_dio == expected_dio
    (STAGE / 'dio_manager.json').write_text(patched_dio)
    (STAGE / 'IDENTITY').write_text('MU1320-NAVHOOK-ONESHOT-V1\n')
    (STAGE / 'ARM-TOKEN').write_text('MU1320-NAVHOOK-ONE-SHOT-V1\n')

    copies = {
        'libcarplay_hook.so': BUILD / 'libcarplay_hook.so',
        'loader_check': BASE / 'stage1/loader_check',
        'loader_check.c': BASE / 'stage1/loader_check.c',
        'mount_state': BASE / 'preload-probe/mount_state',
        'mount_state.c': BASE / 'preload-probe/mount_state.c',
        'trial_gate.c': BASE / 'navhook-src/trial_gate.c',
        'trial_gate.h': BASE / 'navhook-src/trial_gate.h',
        'README.md': BASE / 'navhook-src/README.md',
    }
    for name, path in copies.items():
        shutil.copyfile(path, STAGE / name)
    for name in ['loader_check', 'mount_state']:
        (STAGE / name).chmod(0o755)

    values = {'MARKER': MARKER}

    def pin(label, path):
        c, n = crc(path)
        values[label + '_CRC'], values[label + '_SIZE'] = c, n

    for label, path in [
        ('SI_OLD', stock_si), ('SI_NEW', STAGE / 'smartphone_integrator.json'),
        ('DIO_OLD', stock_dio), ('DIO_NEW', STAGE / 'dio_manager.json'),
        ('IDENTITY', STAGE / 'IDENTITY'), ('ARM', STAGE / 'ARM-TOKEN'),
        ('HOOK', STAGE / 'libcarplay_hook.so'), ('MOUNT', STAGE / 'mount_state'),
        ('LOADER', STAGE / 'loader_check'),
    ]:
        pin(label, path)

    runtime_files = [
        ('smartphone_integrator', RESOURCE / 'smartphone_integrator', '/mnt/app/eso/bin/apps/smartphone_integrator'),
        ('dio_manager', RESOURCE / 'dio_manager', '/mnt/app/eso/bin/apps/dio_manager'),
        ('libsocket.so.3', RESOURCE / 'native-libs/lib/libsocket.so.3', '/lib/libsocket.so.3'),
        ('libNme.so', RESOURCE / 'native-libs/mnt/app/armle/usr/lib/libNme.so', '/mnt/app/armle/usr/lib/libNme.so'),
        ('libNmeBaseClasses.so', RESOURCE / 'native-libs/mnt/app/armle/usr/lib/libNmeBaseClasses.so', '/mnt/app/armle/usr/lib/libNmeBaseClasses.so'),
        ('libNmeSDK.so', RESOURCE / 'native-libs/mnt/app/armle/usr/lib/libNmeSDK.so', '/mnt/app/armle/usr/lib/libNmeSDK.so'),
        ('libNmeTransport.so', RESOURCE / 'cinemo/libNmeTransport.so', '/mnt/app/armle/usr/lib/cinemo/libNmeTransport.so'),
        ('libNmeNav.so', RESOURCE / 'cinemo/libNmeNav.so', '/mnt/app/armle/usr/lib/cinemo/libNmeNav.so'),
    ]
    native_checks = []
    for name, local, target in runtime_files:
        c, n = crc(local)
        native_checks.append(f'check {c} {n} {target} || fail "{name} baseline"')
    values['NATIVE_CHECKS'] = '\n    '.join(native_checks)

    payload_checks = []
    for label, name in [('SI_NEW', 'smartphone_integrator.json'), ('DIO_NEW', 'dio_manager.json'),
                        ('IDENTITY', 'IDENTITY'), ('ARM', 'ARM-TOKEN'),
                        ('HOOK', 'libcarplay_hook.so'), ('LOADER', 'loader_check')]:
        payload_checks.append(f'check @{label}_CRC@ @{label}_SIZE@ "$stage_dir/{name}" || fail "{name} payload checksum"')
    values['PAYLOAD_CHECKS'] = '\n    '.join(payload_checks)

    def render(template, output):
        text = (BASE / 'scripts' / template).read_text()
        # Values may themselves contain checksum placeholders.
        for _ in range(2):
            for key, value in values.items():
                text = text.replace('@' + key + '@', value)
        assert not re.search(r'@[A-Z_]+@', text), output
        (STAGE / output).write_text(text)
        subprocess.run(['/bin/sh', '-n', str(STAGE / output)], check=True)

    render('collect_navhook.sh.in', 'collect_navhook.sh')
    pin('COLLECT', STAGE / 'collect_navhook.sh')
    render('navhook_control.sh.in', 'control.sh')
    pin('CONTROL', STAGE / 'control.sh')
    render('navhook_sd.sh.in', 'navhook_trial.sh')

    si_diff = ''.join(difflib.unified_diff(source.splitlines(True), patched_si.splitlines(True),
                                           fromfile='stock/smartphone_integrator.json',
                                           tofile='navhook-trial/smartphone_integrator.json'))
    dio_source = stock_dio.read_text()
    dio_diff = ''.join(difflib.unified_diff(dio_source.splitlines(True), patched_dio.splitlines(True),
                                            fromfile='stock/dio_manager.json',
                                            tofile='navhook-trial/dio_manager.json'))
    (BASE / 'reports/navhook-trial-si.diff').write_text(si_diff)
    (BASE / 'reports/navhook-trial-dio.diff').write_text(dio_diff)
    report = {
        'version': '1.2',
        'marker': 'MU1320_NAVHOOK_TRIAL=' + MARKER,
        'runtime_root': RUNTIME,
        'toolchain_image': IMAGE,
        'stock_exec_path_preserved': True,
        'semantic_changes': {
            'smartphone_integrator.json': [
                'change carplay IPL_CONFIG_DIR_DIO_MANAGER to the private runtime config directory',
                'append one unique marker',
                'append LD_PRELOAD for the private navigation-only hook',
            ],
            'dio_manager.json': [
                'append accessory route-guidance IDs 0x5200 and 0x5203',
                'append device route-guidance IDs 0x5201, 0x5202 and 0x5204',
            ],
        },
        'one_shot_gate': 'exact root-owned mode-0600 /tmp token consumed before active hook initialization',
        'replacement_dio_behavior': 'same library remains loaded but forwards passively after token consumption',
        'java_included': False,
        'renderer_included': False,
        'vehicle_tested': False,
        'build_artifact_sha256': build['artifact']['sha256'],
        'files': {p.name: sha(p) for p in STAGE.iterdir() if p.is_file()},
    }
    (BASE / 'reports/navhook-trial-prepare-v1.2.json').write_text(json.dumps(report, indent=2) + '\n')
    print('Generated gated navigation-hook trial; no vehicle writes were performed.')


if __name__ == '__main__':
    main()
