#!/usr/bin/env python3
"""Stage the read-only Toolbox inventory SD folder (mu1320-toolbox-inventory-v1/).

Never touches a vehicle.  The folder carries the worker (scripts/tbinv_control.sh), the SD
wrapper rendered from scripts/tbinv_sd.sh.in with pinned checksums, and the mount helper
byte-identical to the vehicle-run F3 v2 package.
"""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
FOLDER = 'mu1320-toolbox-inventory-v1'
MOUNT_FROM = BASE / 'mu1320-f3-bap-v2'
MOUNT_CKSUM = ('2952412687', '7302')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cksum(path):
    out = subprocess.check_output(['cksum', str(path)], text=True).split()
    return out[0], out[1]


def render(template, values):
    text = template.read_text()
    for key, value in values.items():
        token = '@' + key + '@'
        if token not in text:
            raise SystemExit(f'{template.name}: missing placeholder {token}')
        text = text.replace(token, str(value))
    leftover = re.search(r'@[A-Z_]+@', text)
    if leftover:
        raise SystemExit(f'{template.name}: unrendered placeholder {leftover.group()}')
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=BASE / FOLDER)
    parser.add_argument('--report', type=Path, default=BASE / 'reports/toolbox-inventory-prepare.json')
    parser.add_argument('--replace', action='store_true',
                        help='rebuild an existing, not-yet-used staging folder')
    args = parser.parse_args()
    out = args.output
    if out.exists():
        if not args.replace:
            parser.error(f'{out} exists; pass --replace only before it has been used on the car')
        if (out / 'out').exists():
            parser.error('staging folder already holds vehicle output; never replace it')
        shutil.rmtree(out)
    if cksum(MOUNT_FROM / 'mount_state') != MOUNT_CKSUM:
        parser.error('mount_state differs from the vehicle-run F3 package')

    out.mkdir()
    shutil.copyfile(MOUNT_FROM / 'mount_state', out / 'mount_state')
    shutil.copyfile(MOUNT_FROM / 'mount_state.c', out / 'mount_state.c')
    (out / 'mount_state').chmod(0o755)
    shutil.copyfile(BASE / 'scripts/tbinv_control.sh', out / 'control.sh')
    control_sum = cksum(out / 'control.sh')
    wrapper = render(BASE / 'scripts/tbinv_sd.sh.in', {
        'MOUNT_CKSUM': MOUNT_CKSUM[0], 'MOUNT_SIZE': MOUNT_CKSUM[1],
        'CONTROL_CKSUM': control_sum[0], 'CONTROL_SIZE': control_sum[1]})
    (out / 'toolbox_inventory.sh').write_text(wrapper)
    shutil.copyfile(BASE / 'tbinv-src/sd-README.md', out / 'README.md')

    files = sorted(p.name for p in out.iterdir() if p.is_file())
    (out / 'SHA256SUMS').write_text(''.join(f'{digest(out / n)}  {n}\n' for n in files))
    report = {
        'folder': FOLDER, 'sd_path': f'/fs/sda0/{FOLDER}', 'vehicle_tested': False,
        'scope': 'read-only inventory of the Toolbox green-menu tree, its SSH install and SWDL '
                 'FileCopyInfo; copies Toolbox pages/scripts and edited config to SD (never sshd keys); '
                 'no writes under /mnt/app or /mnt/system',
        'files': {n: {'sha256': digest(out / n), 'cksum': ' '.join(cksum(out / n))} for n in files},
        'reused': {'mount_state': 'byte-identical to mu1320-f3-bap-v2/mount_state (vehicle-run)'},
    }
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print('staged', out)
    for n in files:
        print(f'  {n:20s} {report["files"][n]["cksum"]}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
