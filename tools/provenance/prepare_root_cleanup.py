#!/usr/bin/env python3
"""Stage the /mnt/app/root cleanup SD folder (mu1320-root-cleanup-v1/); never touches a vehicle.

The delete whitelist is generated from the vehicle root inventory (manifest.txt of
mu1320-root-inventory-v1): exactly the recorded directories and files (with their QNX
cksum) under the 12 trial directories.  Every recorded file must also match the byte copy
the inventory brought back, so the workstation holds everything the car will lose.
"""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
FOLDER = 'mu1320-root-cleanup-v1'
INVENTORY = BASE.parent / 'resource/private/vehicle-dump/root-inventory-v1/inv-3317899'
MOUNT_FROM = BASE / 'mu1320-f3-bap-v2'
MOUNT_CKSUM = ('2952412687', '7302')
ROOT = '/mnt/app/root'
WHITELIST = [
    'mu1320-env-probe-v2', 'mu1320-preload-probe-v1',
    'mu1320-rgi-stage1-v2', 'mu1320-rgi-stage2-v2', 'mu1320-rgi-stage3-v1',
    'mu1320-rgi-navhook-v1', 'mu1320-rgi-navjava-v1',
    'mu1320-rgi-f1-v1', 'mu1320-rgi-f1-v2', 'mu1320-rgi-f2-v1', 'mu1320-rgi-f3-v1', 'mu1320-rgi-f3-v2',
]
EXPECTED_DIRS, EXPECTED_FILES = 38, 77
SAFE_PATH = re.compile(r'^/mnt/app/root/[A-Za-z0-9._/-]+$')


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


def load_inventory(inv):
    dirs, files = [], []
    for line in (inv / 'manifest.txt').read_text().splitlines():
        parts = line.split(' ')
        if parts[0] not in ('DIR', 'FILE', 'LINK', 'OTHER', 'DEPTH_LIMIT', 'CKSUM_FAIL'):
            continue
        path = parts[-1]
        rel = path[len(ROOT) + 1:] if path.startswith(ROOT + '/') else None
        if rel is None or rel.split('/')[0] not in WHITELIST:
            continue
        if not SAFE_PATH.match(path) or '/../' in path or path.endswith('/..'):
            raise SystemExit(f'unsafe path in inventory: {path}')
        if parts[0] == 'DIR':
            dirs.append(path)
        elif parts[0] == 'FILE' and len(parts) == 4:
            files.append((parts[1], parts[2], path))
        else:
            raise SystemExit(f'inventory entry the cleanup cannot handle: {line}')
    tops = sorted(d.split('/')[4] for d in dirs if d.count('/') == 4)
    if tops != sorted(WHITELIST):
        raise SystemExit(f'whitelisted directories missing from inventory: {set(WHITELIST) - set(tops)}')
    if (len(dirs), len(files)) != (EXPECTED_DIRS, EXPECTED_FILES):
        raise SystemExit(f'inventory has {len(dirs)} dirs / {len(files)} files, expected '
                         f'{EXPECTED_DIRS}/{EXPECTED_FILES}')
    for c, n, path in files:
        copy = inv / 'copy' / path.lstrip('/')
        if cksum(copy) != (c, n):
            raise SystemExit(f'workstation copy differs from car cksum: {path}')
    return dirs, files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', type=Path, default=INVENTORY)
    parser.add_argument('--output', type=Path, default=BASE / FOLDER)
    parser.add_argument('--report', type=Path, default=BASE / 'reports/root-cleanup-prepare.json')
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
    dirs, files = load_inventory(args.inventory)

    records = [f'D {d}' for d in dirs] + [f'F {c} {n} {p}' for c, n, p in files]
    case = '\n'.join(f"        '{r}') return 0 ;;" for r in records)
    steps = [f"del_file {c} {n} '{p}'" for c, n, p in files]
    steps += [f"del_dir '{d}'" for d in sorted(dirs, key=lambda d: (-d.count('/'), d))]

    out.mkdir()
    shutil.copyfile(MOUNT_FROM / 'mount_state', out / 'mount_state')
    shutil.copyfile(MOUNT_FROM / 'mount_state.c', out / 'mount_state.c')
    (out / 'mount_state').chmod(0o755)
    control = render(BASE / 'scripts/rootclean_control.sh.in', {
        'INVENTORY': 'root-inventory-v1 inv-3317899, 2026-09-26',
        'WHITELIST': ' '.join(WHITELIST), 'EXPECTED_COUNT': len(records),
        'EXPECTED_CASE': case, 'DELETE_STEPS': '\n'.join(steps),
        'MOUNT_SUM': ' '.join(MOUNT_CKSUM)})
    (out / 'control.sh').write_text(control)
    control_sum = cksum(out / 'control.sh')
    wrapper = render(BASE / 'scripts/rootclean_sd.sh.in', {
        'MOUNT_CKSUM': MOUNT_CKSUM[0], 'MOUNT_SIZE': MOUNT_CKSUM[1],
        'CONTROL_CKSUM': control_sum[0], 'CONTROL_SIZE': control_sum[1]})
    (out / 'root_cleanup.sh').write_text(wrapper)
    shutil.copyfile(BASE / 'rootclean-src/sd-README.md', out / 'README.md')

    names = sorted(p.name for p in out.iterdir() if p.is_file())
    (out / 'SHA256SUMS').write_text(''.join(f'{digest(out / n)}  {n}\n' for n in names))
    report = {
        'folder': FOLDER, 'sd_path': f'/fs/sda0/{FOLDER}', 'vehicle_tested': False,
        'inventory': str(args.inventory.relative_to(BASE.parent)) if args.inventory.is_relative_to(BASE.parent)
        else str(args.inventory),
        'whitelist': WHITELIST, 'dirs': len(dirs), 'files': len(files),
        'bytes': sum(int(n) for _, n, _ in files),
        'kept': 'every other /mnt/app/root entry (bin-target, hooks, .ssh, .profile, scp, scpr, ...)',
        'staged_files': {n: {'sha256': digest(out / n), 'cksum': ' '.join(cksum(out / n))} for n in names},
    }
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print('staged', out, f'({len(dirs)} dirs, {len(files)} files whitelisted)')
    for n in names:
        print(f'  {n:18s} {report["staged_files"][n]["cksum"]}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
