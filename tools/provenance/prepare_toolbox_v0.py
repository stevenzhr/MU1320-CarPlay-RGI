#!/usr/bin/env python3
"""Stage the MU1320 Toolbox v0 SD package (mu1320-toolbox-v0/).

Never touches a vehicle.  The package is upstream mib2-toolbox at a pinned commit, copied
byte for byte (metainfo2.txt and Toolbox/final/ stay identical, so the SWDL metadata the
car already accepted is unchanged), plus an overlay: one green-menu page
(Toolbox/GEM/mqb-mu1320.esd) and Toolbox/scripts/mu1320/, which the upstream final script
installs to /eso/hmi/engdefs/scripts/mqb/mu1320/.

The Lanye removal manifest lists the files Lanye's MHI2Q-CarPlay-RGI-MMI-Mirror adds to the
same upstream commit, with POSIX cksums.  When the vehicle Toolbox inventory is present it is
cross-checked against the car.
"""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
WORKSPACE = BASE.parent
FOLDER = 'mu1320-toolbox-v0'
UPSTREAM = WORKSPACE / 'mib2-toolbox'
UPSTREAM_COMMIT = 'af244e7cb8c912ab47f5c09cd7677370fe86b441'
LANYE = WORKSPACE / 'MHI2Q-CarPlay-RGI-MMI-Mirror'
LANYE_COMMIT = '441c150'
LANYE_COUNT = 17
SRC = BASE / 'tbv0-src'
MOUNT_FROM = BASE / 'mu1320-f3-bap-v2'
MOUNT_CKSUM = ('2952412687', '7302')
UNBUF_FROM = BASE / 'mu1320-f7-daily-v1'
UNBUF_CKSUM = ('1988489462', '5403')
INVENTORY = (WORKSPACE / 'resource/private/vehicle-dump/toolbox-inventory-v1/tbinv-3162251/manifest.txt')
ENGDEFS = '/mnt/app/eso/hmi/engdefs'
SCRIPTS = ['probe_ro.sh', 'probe_write.sh', 'bg_start.sh', 'bg_check.sh', 'lanye_check.sh', 'lanye_remove.sh']


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cksum(path):
    out = subprocess.check_output(['cksum', str(path)], text=True).split()
    return out[0], out[1]


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True)


def pinned_clone(repo, commit, paths, parser):
    head = git(repo, 'rev-parse', 'HEAD').strip()
    if not head.startswith(commit):
        parser.error(f'{repo.name} is at {head[:12]}, expected {commit[:12]}')
    if git(repo, 'status', '--porcelain', '--', *paths).strip():
        parser.error(f'{repo.name} has local changes under {paths}')
    return set(git(repo, 'ls-files', '--', *paths).splitlines())


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


def engdefs_path(rel):
    """Toolbox/GEM/x.esd -> x.esd; Toolbox/scripts/y -> scripts/mqb/y (upstream install_scripts.sh)."""
    if rel.startswith('Toolbox/GEM/'):
        return rel[len('Toolbox/GEM/'):]
    if rel.startswith('Toolbox/scripts/'):
        return 'scripts/mqb/' + rel[len('Toolbox/scripts/'):]
    raise SystemExit(f'unexpected Lanye path {rel}')


def vehicle_files():
    files = {}
    for line in INVENTORY.read_text(errors='replace').splitlines():
        parts = line.split(' ', 3)
        if len(parts) == 4 and parts[0] == 'FILE':
            files[parts[3]] = (parts[1], parts[2])
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=BASE / FOLDER)
    parser.add_argument('--report', type=Path, default=BASE / 'reports/toolbox-v0-prepare.json')
    parser.add_argument('--replace', action='store_true', help='rebuild an existing staging folder')
    args = parser.parse_args()
    final = args.output
    if final.exists() and not args.replace:
        parser.error(f'{final} exists; pass --replace to rebuild it')
    # build in a sibling temp dir and swap it in at the end: a failed run leaves no partial package
    out = final.with_name(final.name + '.building')
    if out.exists():
        shutil.rmtree(out)
    out.mkdir()

    upstream = pinned_clone(UPSTREAM, UPSTREAM_COMMIT, ['Toolbox', 'metainfo2.txt', 'LICENSE'], parser)
    lanye = pinned_clone(LANYE, LANYE_COMMIT, ['Toolbox/GEM', 'Toolbox/scripts'], parser)
    if cksum(MOUNT_FROM / 'mount_state') != MOUNT_CKSUM:
        parser.error('mount_state differs from the vehicle-run F3 package')
    if cksum(UNBUF_FROM / 'f4_unbuf.so') != UNBUF_CKSUM:
        parser.error('f4_unbuf.so differs from the F7 package')

    # 1. upstream, byte for byte (tracked files only)
    shipped = sorted(p for p in upstream if p.startswith('Toolbox/') or p == 'metainfo2.txt')
    for rel in shipped:
        dst = out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(UPSTREAM / rel, dst)
    shutil.copyfile(UPSTREAM / 'LICENSE', out / 'LICENSE-mib2-toolbox.txt')
    if (out / 'Toolbox/GEM/mqb-mu1320.esd').exists() or (out / 'Toolbox/scripts/mu1320').exists():
        parser.error('upstream already has an mu1320 path')

    # 2. Lanye manifest: files Lanye adds on top of the same upstream commit
    upstream_names = {p for p in upstream if p.startswith(('Toolbox/GEM/', 'Toolbox/scripts/'))}
    added = sorted(p for p in lanye if p not in upstream_names)
    if len(added) != LANYE_COUNT:
        parser.error(f'expected {LANYE_COUNT} Lanye files, found {len(added)}')
    rows = []
    for rel in added:
        crc, size = cksum(LANYE / rel)
        rows.append((crc, size, engdefs_path(rel)))
    rows.sort(key=lambda r: r[2])
    vehicle = {}
    if INVENTORY.exists():
        car = vehicle_files()
        for crc, size, rel in rows:
            got = car.get(f'{ENGDEFS}/{rel}')
            if got != (crc, size):
                parser.error(f'Lanye file {rel} differs from the car inventory: {got}')
            vehicle[rel] = 'matches car inventory'

    # 3. overlay
    gem = out / 'Toolbox/GEM/mqb-mu1320.esd'
    shutil.copyfile(SRC / 'mqb-mu1320.esd', gem)
    sdir = out / 'Toolbox/scripts/mu1320'
    sdir.mkdir()
    manifest = sdir / 'lanye_manifest.txt'
    manifest.write_text(''.join(f'{c} {s} {r}\n' for c, s, r in rows))
    man_sum = cksum(manifest)
    (sdir / 'lib.sh').write_text(render(SRC / 'lib.sh.in', {
        'MS_CKSUM': MOUNT_CKSUM[0], 'MS_SIZE': MOUNT_CKSUM[1],
        'UNBUF_CKSUM': UNBUF_CKSUM[0], 'UNBUF_SIZE': UNBUF_CKSUM[1],
        'MANIFEST_CKSUM': man_sum[0], 'MANIFEST_SIZE': man_sum[1]}))
    for name in SCRIPTS:
        shutil.copyfile(SRC / name, sdir / name)
    shutil.copyfile(MOUNT_FROM / 'mount_state', sdir / 'mount_state')
    shutil.copyfile(MOUNT_FROM / 'mount_state.c', sdir / 'mount_state.c')
    shutil.copyfile(UNBUF_FROM / 'f4_unbuf.so', sdir / 'f4_unbuf.so')
    for p in sdir.iterdir():
        p.chmod(0o755 if p.suffix in ('.sh', '') and p.name != 'lanye_manifest.txt' else 0o644)
    shutil.copyfile(SRC / 'sd-README.md', out / 'MU1320-README.md')
    shutil.copyfile(SRC / 'sd-OBSERVATIONS.txt', out / 'MU1320-OBSERVATIONS.txt')

    # 4. checks and sums
    for p in out.rglob('*'):
        if p.name.startswith('._') or p.name == '.DS_Store':
            parser.error(f'macOS metadata file in package: {p}')
    for p in [gem, *sdir.iterdir()]:
        if p.suffix in ('.sh', '.esd', '.txt') and b'\r' in p.read_bytes():
            parser.error(f'CR line ending in {p}')
    files = sorted(str(p.relative_to(out)) for p in out.rglob('*') if p.is_file())
    (out / 'MU1320-SHA256SUMS').write_text(''.join(f'{digest(out / n)}  {n}\n' for n in files))
    ours = sorted(str(p.relative_to(out)) for p in [gem, *sdir.iterdir()])
    report = {
        'folder': FOLDER, 'vehicle_tested': False,
        'install': 'copy the folder contents to the SD root (replacing Toolbox/ and metainfo2.txt), '
                   'dot_clean the card, then run the Toolbox update from the green menu',
        'upstream': {'repo': 'jilleb/mib2-toolbox', 'commit': UPSTREAM_COMMIT, 'files': len(shipped),
                     'metainfo2_and_final_unchanged': True},
        'lanye_manifest': {'repo': 'Lanye-z/MHI2Q-CarPlay-RGI-MMI-Mirror', 'commit': LANYE_COMMIT,
                           'entries': [' '.join(r) for r in rows], 'vehicle_check': vehicle or 'inventory absent'},
        'overlay': {n: {'sha256': digest(out / n), 'cksum': ' '.join(cksum(out / n))} for n in ours},
        'reused': {'mount_state': 'byte-identical to mu1320-f3-bap-v2 (vehicle-run)',
                   'f4_unbuf.so': 'byte-identical to mu1320-f7-daily-v1 (F4/F5 car path)'},
    }
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    if final.exists():
        shutil.rmtree(final)
    out.rename(final)
    print('staged', final, f'({len(files)} files; upstream {len(shipped)}, overlay {len(ours)})')
    for n in ours:
        print(f'  {n:45s} {report["overlay"][n]["cksum"]}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
