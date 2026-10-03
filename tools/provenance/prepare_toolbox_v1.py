#!/usr/bin/env python3
"""Stage the MU1320 Toolbox v1 SD package (mu1320-toolbox-v1/): the F7 green menu.

Never touches a vehicle.  Same construction as Toolbox v0 (scripts/prepare_toolbox_v0.py),
which the car accepted on 2026-09-27: upstream mib2-toolbox at the pinned commit, byte for
byte (metainfo2.txt and Toolbox/final/ unchanged), plus an overlay:

  Toolbox/GEM/mqb-mu1320.esd        the F7 page; same file name as v0, so the SWDL update
                                    replaces the v0 diagnostics page
  Toolbox/scripts/mu1320/f7menu.sh  the dispatcher (tbv1-src/f7menu.sh)
  Toolbox/scripts/mu1320/f7_{status,install,uninstall,collect,stop}.sh   one stub per button

SWDL only adds and overwrites, so the v0 helper scripts already on the car stay in
scripts/mqb/mu1320/ unreferenced; none of their names is reused.
"""
import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
WORKSPACE = BASE.parent
FOLDER = 'mu1320-toolbox-v1'
UPSTREAM = WORKSPACE / 'mib2-toolbox'
UPSTREAM_COMMIT = 'af244e7cb8c912ab47f5c09cd7677370fe86b441'
SRC = BASE / 'tbv1-src'
BUTTONS = ['status', 'install', 'uninstall', 'collect', 'stop']
SCRIPTS = ['f7menu.sh'] + ['f7_%s.sh' % b for b in BUTTONS]
V0_REPORT = BASE / 'reports/toolbox-v0-prepare.json'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cksum(path):
    out = subprocess.check_output(['cksum', str(path)], text=True).split()
    return out[0], out[1]


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=BASE / FOLDER)
    parser.add_argument('--report', type=Path, default=BASE / 'reports/toolbox-v1-prepare.json')
    parser.add_argument('--replace', action='store_true', help='rebuild an existing staging folder')
    args = parser.parse_args()
    final = args.output
    if final.exists() and not args.replace:
        parser.error(f'{final} exists; pass --replace to rebuild it')
    out = final.with_name(final.name + '.building')
    if out.exists():
        shutil.rmtree(out)
    out.mkdir()

    head = git(UPSTREAM, 'rev-parse', 'HEAD').strip()
    if head != UPSTREAM_COMMIT:
        parser.error(f'mib2-toolbox is at {head[:12]}, expected {UPSTREAM_COMMIT[:12]}')
    if git(UPSTREAM, 'status', '--porcelain', '--', 'Toolbox', 'metainfo2.txt', 'LICENSE').strip():
        parser.error('mib2-toolbox has local changes')
    upstream = set(git(UPSTREAM, 'ls-files', '--', 'Toolbox', 'metainfo2.txt', 'LICENSE').splitlines())

    # 1. upstream, byte for byte (tracked files only)
    shipped = sorted(p for p in upstream if p.startswith('Toolbox/') or p == 'metainfo2.txt')
    for rel in shipped:
        dst = out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(UPSTREAM / rel, dst)
    shutil.copyfile(UPSTREAM / 'LICENSE', out / 'LICENSE-mib2-toolbox.txt')
    if (out / 'Toolbox/GEM/mqb-mu1320.esd').exists() or (out / 'Toolbox/scripts/mu1320').exists():
        parser.error('upstream already has an mu1320 path')

    # 2. overlay
    gem = out / 'Toolbox/GEM/mqb-mu1320.esd'
    shutil.copyfile(SRC / 'mqb-mu1320.esd', gem)
    sdir = out / 'Toolbox/scripts/mu1320'
    sdir.mkdir()
    for name in SCRIPTS:
        shutil.copyfile(SRC / name, sdir / name)
        (sdir / name).chmod(0o755)
    shutil.copyfile(SRC / 'sd-README.md', out / 'MU1320-README.md')

    # 3. checks: the page names exactly the stubs, the stubs source the dispatcher, v0 names unused
    esd = gem.read_text()
    for b in BUTTONS:
        stub = (sdir / f'f7_{b}.sh').read_text()
        if f'"/eso/hmi/engdefs/scripts/mqb/mu1320/f7_{b}.sh"' not in esd:
            parser.error(f'page does not run f7_{b}.sh')
        if stub != ('#!/bin/sh\n# MU1320 Toolbox v1 button: ' + stub.splitlines()[1].split(': ', 1)[1] + '\n'
                    '. /eso/hmi/engdefs/scripts/mqb/mu1320/f7menu.sh\n' f'f7m_main {b}\n'):
            parser.error(f'unexpected stub f7_{b}.sh')
    if esd.count('0x0100 "') != len(BUTTONS):
        parser.error('page has other script buttons')
    v0 = json.loads(V0_REPORT.read_text())
    v0_names = {Path(n).name for n in v0['overlay'] if n.startswith('Toolbox/scripts/mu1320/')}
    reused = sorted(v0_names & set(SCRIPTS))
    if reused:
        parser.error(f'v1 reuses v0 script names {reused}')
    for p in out.rglob('*'):
        if p.name.startswith('._') or p.name == '.DS_Store':
            parser.error(f'macOS metadata file in package: {p}')
    for p in [gem, *sdir.iterdir()]:
        if b'\r' in p.read_bytes():
            parser.error(f'CR line ending in {p}')
        if p.suffix == '.sh':
            for shell in ('/bin/sh', '/bin/ksh'):
                if Path(shell).exists():
                    subprocess.run([shell, '-n', str(p)], check=True)
            code = '\n'.join(l for l in p.read_text().splitlines() if not l.lstrip().startswith('#'))
            if 'dmdt' in code:
                parser.error(f'{p.name} must not call dmdt')

    files = sorted(str(p.relative_to(out)) for p in out.rglob('*') if p.is_file())
    (out / 'MU1320-SHA256SUMS').write_text(''.join(f'{digest(out / n)}  {n}\n' for n in files))
    ours = sorted(str(p.relative_to(out)) for p in [gem, *sdir.iterdir()])
    report = {
        'folder': FOLDER, 'vehicle_tested': False,
        'install': 'copy the folder contents to the SD root (replacing Toolbox/ and metainfo2.txt), '
                   'dot_clean the card, then run the Toolbox update from the green menu',
        'upstream': {'repo': 'jilleb/mib2-toolbox', 'commit': UPSTREAM_COMMIT, 'files': len(shipped),
                     'metainfo2_and_final_unchanged': True},
        'overlay': {n: {'sha256': digest(out / n), 'cksum': ' '.join(cksum(out / n))} for n in ours},
        'replaces_on_car': ['engdefs/mqb-mu1320.esd (Toolbox v0 diagnostics page)'],
        'left_on_car_unreferenced': sorted('scripts/mqb/mu1320/' + n for n in v0_names),
        'dispatcher': {'buttons': {b: 'f7_%s.sh' % b for b in BUTTONS},
                       'f7_sh_actions': {'status': 'status', 'install': 'install', 'uninstall': 'rollback',
                                         'collect': 'collect snapshot', 'stop': 'stop'},
                       'folder_rule': 'exactly one /fs/sda0|sdb0/mu1320-f7-*/ with TOOLBOX-ENTRY '
                                      '"MU1320_F7_TOOLBOX_ENTRY 1"'},
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
