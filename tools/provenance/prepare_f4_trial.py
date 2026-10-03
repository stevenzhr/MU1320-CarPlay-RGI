#!/usr/bin/env python3
"""Stage the F4 renderer trial SD folder (mu1320-f4-render-v1/); never touches a vehicle.

The folder is copied as-is to the SD root.  It carries the renderer and feeder from
build_f4_render.py, the mount helper byte-identical to the vehicle-run F3 package,
and control/wrapper scripts rendered from scripts/f4_*.sh.in with pinned checksums.
"""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
PRIVATE = BASE.parent / "private-data" / "mu1320-rgi"
VERSION = 'v1'
FOLDER = f'mu1320-f4-render-{VERSION}'
CTX = 80
HOLD = 20
SETTLE = 3
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
    parser.add_argument('--build', type=Path, default=PRIVATE / 'f4-render-v1')
    parser.add_argument('--output', type=Path, default=BASE / FOLDER)
    parser.add_argument('--report', type=Path, default=BASE / 'reports/f4-render-prepare.json')
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
    build = json.loads((BASE / 'reports/f4-render-build.json').read_text())
    render_bin = args.build / 'src/build/maneuver_render'
    feed_bin = args.build / 'feed/f4_feed'
    atlas = args.build / 'src/maneuver_render/resources/flag_atlas.rgba'
    unbuf = args.build / 'unbuf/f4_unbuf.so'
    for name, path in (('maneuver_render', render_bin), ('f4_feed', feed_bin), ('flag_atlas.rgba', atlas),
                       ('f4_unbuf.so', unbuf)):
        if digest(path) != build['artifacts'][name]['sha256']:
            parser.error(f'{name} differs from reports/f4-render-build.json')
        if build['static_audit'].get(name, {'status': 'STATIC_PASS'})['status'] != 'STATIC_PASS':
            parser.error(f'{name} did not pass the static audit')
    if cksum(MOUNT_FROM / 'mount_state') != MOUNT_CKSUM:
        parser.error('mount_state differs from the vehicle-run F3 package')

    out.mkdir()
    shutil.copyfile(render_bin, out / 'maneuver_render')
    shutil.copyfile(feed_bin, out / 'f4_feed')
    shutil.copyfile(atlas, out / 'flag_atlas.rgba')
    shutil.copyfile(BASE / 'f4-src/f4_feed.c', out / 'f4_feed.c')
    shutil.copyfile(unbuf, out / 'f4_unbuf.so')
    shutil.copyfile(BASE / 'f4-src/f4_unbuf.c', out / 'f4_unbuf.c')
    shutil.copyfile(MOUNT_FROM / 'mount_state', out / 'mount_state')
    shutil.copyfile(MOUNT_FROM / 'mount_state.c', out / 'mount_state.c')
    for name in ('maneuver_render', 'f4_feed', 'mount_state'):
        (out / name).chmod(0o755)

    def pair(name):
        return ' '.join(cksum(out / name))

    control = render(BASE / 'scripts/f4_control.sh.in', {
        'CTX': CTX, 'HOLD': HOLD, 'SETTLE': SETTLE,
        'RENDER_SUM': pair('maneuver_render'), 'FEED_SUM': pair('f4_feed'),
        'ATLAS_SUM': pair('flag_atlas.rgba'), 'UNBUF_SUM': pair('f4_unbuf.so')})
    (out / 'control.sh').write_text(control)
    control_sum = cksum(out / 'control.sh')
    wrapper = render(BASE / 'scripts/f4_sd.sh.in', {
        'MOUNT_CKSUM': MOUNT_CKSUM[0], 'MOUNT_SIZE': MOUNT_CKSUM[1],
        'CONTROL_CKSUM': control_sum[0], 'CONTROL_SIZE': control_sum[1]})
    (out / 'f4_trial.sh').write_text(wrapper)
    for name in ('README.md', 'OBSERVATIONS-TEMPLATE.txt'):
        shutil.copyfile(BASE / 'f4-src' / ('sd-' + name), out / name)

    files = sorted(p.name for p in out.iterdir() if p.is_file())
    (out / 'SHA256SUMS').write_text(''.join(f'{digest(out / n)}  {n}\n' for n in files))
    report = {
        'folder': FOLDER, 'sd_path': f'/fs/sda0/{FOLDER}', 'vehicle_tested': False,
        'scope': 'native-only runtime trial: renderer + feeder + DisplayManager context via dmdt; '
                 'no Java, no SI/DIO, no writes under /mnt/app or /mnt/system',
        'context_id': CTX, 'test_context': [98, 102, 101, 33], 'stock_context_74': [20, 102, 101, 33],
        'hold_seconds': HOLD, 'settle_seconds': SETTLE,
        'files': {n: {'sha256': digest(out / n), 'cksum': ' '.join(cksum(out / n))} for n in files},
        'reused': {'mount_state': 'byte-identical to mu1320-f3-bap-v2/mount_state (vehicle-run)',
                   'maneuver_render': 'byte-identical to the 2026-09-22 native-probe build'
                   if build['renderer_matches_2026_09_22_native_probe'] else 'rebuilt'},
    }
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print('staged', out)
    for n in files:
        print(f'  {n:28s} {report["files"][n]["cksum"]}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
