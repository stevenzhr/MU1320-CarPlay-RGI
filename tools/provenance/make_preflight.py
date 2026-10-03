#!/usr/bin/env python3
"""Generate a read-only QNX baseline checker. It cannot install or approve a release."""
import subprocess
import hashlib
import json
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
RESOURCE = BASE.parent/'resource'
DEST = BASE/'preflight'


def main():
    pinned = {}
    for name in ['input-manifest.json', 'supplement-manifest.json']:
        pinned.update(json.loads((BASE/'reports'/name).read_text())['files'])
    mapping = {
        '/etc/eso/production/dio_manager.json': 'dio_manager.json',
        '/mnt/system/etc/eso/production/dio_manager.json': 'dio_manager.json',
        '/etc/eso/production/smartphone_integrator.json': 'smartphone_integrator.json',
        '/mnt/system/etc/eso/production/smartphone_integrator.json': 'smartphone_integrator.json',
        '/etc/scripts/carplay_cleanup.sh': 'carplay_cleanup.sh',
        '/mnt/app/eso/hmi/lsd/lsd.sh': 'lsd.sh',
        '/ifs/lsd.jxe': 'lsd.jxe',
        '/mnt/app/eso/bin/apps/dio_manager': 'dio_manager',
        '/mnt/app/eso/hmi/lsd/jars/NavActiveIgnore.jar': 'jars/NavActiveIgnore.jar',
        '/mnt/app/armle/usr/lib/cinemo/libNmeVfs.so': 'cinemo/libNmeVfs.so',
        '/mnt/app/armle/usr/lib/cinemo/cinemo_classes.xml': 'cinemo/cinemo_classes.xml',
        '/mnt/app/armle/usr/lib/libNmeBaseClasses.so': 'libNmeBaseClasses.so',
        '/mnt/app/armle/usr/lib/libNmeSDK.so': 'libNmeSDK.so',
        '/proc/boot/libscreen.so.1': 'native-libs/proc/boot/libscreen.so.1',
        '/proc/boot/libEGL.so.1': 'native-libs/proc/boot/libEGL.so.1',
        '/proc/boot/libGLESv2.so.1': 'native-libs/proc/boot/libGLESv2.so.1',
    }
    rows = []
    for vehicle, local in mapping.items():
        if hashlib.sha256((RESOURCE/local).read_bytes()).hexdigest() != pinned[local]['sha256']:
            raise ValueError('input differs from audited baseline: '+local)
        crc, length = subprocess.check_output(['cksum', str(RESOURCE/local)], text=True).split()[:2]
        rows.append(f'{crc} {length} {vehicle}')
    template = (BASE/'scripts/preflight.sh.in').read_text()
    assert template.count('@CHECKSUM_ROWS@') == 1
    DEST.mkdir(exist_ok=True)
    (DEST/'preflight.sh').write_text(template.replace('@CHECKSUM_ROWS@', '\n'.join(rows)))
    print('Generated read-only checker for', len(rows), 'baseline paths; NOT an installer.')


if __name__ == '__main__': main()
