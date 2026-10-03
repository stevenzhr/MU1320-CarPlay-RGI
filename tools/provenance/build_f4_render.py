#!/usr/bin/env python3
"""Build the F4 renderer trial binaries in a private copy; never installs on a vehicle.

maneuver_render is rebuilt from the pinned upstream sources (unmodified) with the
pinned toolchain image; f4_feed comes from f4-src/.  Both are statically audited
against the collected MU1320 runtime libraries.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
PRIVATE = BASE.parent / "private-data" / "mu1320-rgi"
sys.path.insert(0, str(BASE / 'scripts'))
PREFIX = 'arm-unknown-nto-qnx6.5.0eabi-'
IMAGE = 'sha256:e52565b1f62dab0f93f12532d52611b94e90b89e4da04f972b11f54eaeb6a05d'
PROBE_RENDER_SHA = '9fccf76c376c47c0a06a0f4c7f0520666c1eac6cd17ea0cdeba82fff931d0fc7'
FEED_CFLAGS = ['-O2', '-std=gnu99', '-Wall', '-Wextra', '-Werror', '-D__QNX__']
UNBUF_CFLAGS = ['-O2', '-std=gnu99', '-Wall', '-Wextra', '-Werror', '-fPIC', '-fvisibility=hidden', '-shared',
                '-Wl,-soname,f4_unbuf.so', '-Wl,--version-script=f4_unbuf.map', '-Wl,-z,defs']
UNBUF_INIT_ARRAY = 8   # compiler frame_dummy entry + our constructor


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(cmd, log, cwd=None):
    with log.open('a') as stream:
        stream.write('$ ' + ' '.join(cmd) + '\n')
        stream.flush()
        return subprocess.run(cmd, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT).returncode


def inventory():
    from audit_native import inspect
    resource = BASE.parent / 'resource'
    files = sorted(resource.glob('lib*.so*')) + sorted((resource / 'native-libs').rglob('*.so*'))
    return {str(p.relative_to(resource)): inspect(p) for p in files if p.is_file()}


def build_unbuf(output, report_path):
    """Add f4_unbuf.so (dmdt stdout shim) to an existing build without touching the other artifacts."""
    from audit_native_probe import check_binary
    work = output / 'unbuf'
    if work.exists():
        raise SystemExit('unbuf build already exists; never overwritten')
    work.mkdir()
    for name in ('f4_unbuf.c', 'f4_unbuf.map'):
        (work / name).write_bytes((BASE / 'f4-src' / name).read_bytes())
    log = output / 'build-unbuf.log'
    if run(['docker', 'run', '--rm', '--network=none', '--platform=linux/amd64',
            '-v', f'{work}:/work', '-w', '/work', IMAGE, 'bash', '-c',
            'export PATH=/opt/qnx650/host/linux/x86/usr/bin:$PATH '
            'QNX_HOST=/opt/qnx650/host/linux/x86 QNX_TARGET=/opt/qnx650/target/qnx6; '
            + ' '.join([PREFIX + 'gcc'] + UNBUF_CFLAGS + ['f4_unbuf.c', '-lc', '-o', 'f4_unbuf.so'])
            + ' && ' + PREFIX + 'readelf -d -S f4_unbuf.so'], log):
        print(log.read_text()[-4000:])
        return 1
    lib = work / 'f4_unbuf.so'
    audit = check_binary(lib, inventory(), shared_init_size=UNBUF_INIT_ARRAY)
    audit.pop('versioned_symbol_checks', None)
    audit.pop('required_symbols', None)
    report = json.loads(report_path.read_text())
    report['artifacts']['f4_unbuf.so'] = {'size': lib.stat().st_size, 'sha256': digest(lib)}
    report['unbuf_source_sha256'] = digest(BASE / 'f4-src/f4_unbuf.c')
    report['unbuf_cflags'] = UNBUF_CFLAGS
    report['static_audit']['f4_unbuf.so'] = audit
    report_path.write_text(json.dumps(report, indent=2) + '\n')
    print('f4_unbuf.so', audit['status'], audit['size'], audit['sha256'][:16],
          'deps=', audit['direct_dependencies'], 'unresolved=', audit['unresolved_required_symbols'])
    return 0 if audit['status'] == 'STATIC_PASS' else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=PRIVATE / 'f4-render-v1')
    parser.add_argument('--report', type=Path, default=BASE / 'reports/f4-render-build.json')
    parser.add_argument('--add-unbuf', action='store_true',
                        help='only build f4_unbuf.so into an existing build (v1 renderer/feeder stay as built)')
    args = parser.parse_args()
    output = args.output.resolve()
    if args.add_unbuf:
        if not output.exists():
            parser.error('--add-unbuf needs the existing build')
        return build_unbuf(output, args.report)
    if output.exists():
        parser.error('output already exists; existing builds are never overwritten')
    if ':' in str(output) or '\n' in str(output):
        parser.error('unsupported Docker bind path')

    manifest = json.loads((BASE / 'reports/source-manifest.json').read_text())
    upstream = BASE.parent / 'mib2q-carplay-rgi'
    wanted = [n for n in manifest['files']
              if n.startswith(('maneuver_render/', 'common/', 'toolchain/'))
              or n == 'scripts/build_renderers.sh']
    src = output / 'src'
    for name in wanted:
        source = upstream / name
        if digest(source) != manifest['files'][name]:
            parser.error('source differs from pinned manifest: ' + name)
        dest = src / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(source.read_bytes())
    (src / 'build').mkdir()

    meta = json.loads(subprocess.check_output(['docker', 'image', 'inspect', IMAGE], text=True))[0]
    if meta['Id'] != IMAGE or meta['Architecture'] != 'amd64' or meta['Os'] != 'linux':
        parser.error('pinned toolchain image missing or unexpected')
    version = subprocess.check_output(['docker', 'run', '--rm', '--network=none', '--platform=linux/amd64',
                                       IMAGE, PREFIX + 'gcc', '-dumpversion'], text=True).strip()
    if version != '4.9.4':
        parser.error('expected GCC 4.9.4, received ' + version)

    log = output / 'build.log'
    script = src / 'scripts/build_renderers.sh'
    text = script.read_text()
    if text.count('IMG=qnx65-armv7-toolchain:latest') != 1 or text.count('docker run --rm ') != 1:
        parser.error('unexpected build_renderers.sh shape')
    script.write_text(text.replace('IMG=qnx65-armv7-toolchain:latest', 'IMG=' + IMAGE)
                          .replace('docker run --rm ', 'docker run --rm --network=none '))
    if run(['bash', str(script)], log, cwd=src):
        print(log.read_text()[-4000:])
        return 1

    feed_dir = output / 'feed'
    feed_dir.mkdir()
    feed_src = BASE / 'f4-src/f4_feed.c'
    (feed_dir / 'f4_feed.c').write_bytes(feed_src.read_bytes())
    if run(['docker', 'run', '--rm', '--network=none', '--platform=linux/amd64',
            '-v', f'{feed_dir}:/work', '-w', '/work', IMAGE, 'bash', '-c',
            'export PATH=/opt/qnx650/host/linux/x86/usr/bin:$PATH '
            'QNX_HOST=/opt/qnx650/host/linux/x86 QNX_TARGET=/opt/qnx650/target/qnx6; '
            + ' '.join([PREFIX + 'gcc'] + FEED_CFLAGS + ['f4_feed.c', '-o', 'f4_feed', '-lsocket'])
            + ' && ' + PREFIX + 'readelf -h -d f4_feed'], log):
        print(log.read_text()[-4000:])
        return 1

    from audit_native_probe import check_binary
    inv = inventory()
    render = src / 'build/maneuver_render'
    feed = feed_dir / 'f4_feed'
    audits = {'maneuver_render': check_binary(render, inv),
              'f4_feed': check_binary(feed, inv)}
    for name, info in audits.items():
        info.pop('versioned_symbol_checks', None)
        info.pop('required_symbols', None)
    graphics = sorted(n for n in audits['maneuver_render']['direct_dependencies']
                      if re.match(r'lib(EGL|GLESv2|screen)\.so', n))
    report = {
        'deployable': False, 'runtime_tested': False,
        'upstream_commit': manifest['commit'],
        'source_manifest_sha256': digest(BASE / 'reports/source-manifest.json'),
        'renderer_source_modified': False,
        'image_id': IMAGE, 'compiler_version': version,
        'feed_source_sha256': digest(feed_src), 'feed_cflags': FEED_CFLAGS,
        'artifacts': {
            'maneuver_render': {'size': render.stat().st_size, 'sha256': digest(render)},
            'f4_feed': {'size': feed.stat().st_size, 'sha256': digest(feed)},
            'flag_atlas.rgba': {'size': (src / 'maneuver_render/resources/flag_atlas.rgba').stat().st_size,
                                'sha256': digest(src / 'maneuver_render/resources/flag_atlas.rgba')},
        },
        'renderer_matches_2026_09_22_native_probe': digest(render) == PROBE_RENDER_SHA,
        'renderer_graphics_imports': graphics,
        'static_audit': audits,
        'limitations': [
            'Static export/version checks do not prove Screen/EGL behaviour on the MU1320 BSP.',
            'Renderer import stubs stay inside the build container; the vehicle binds its own /proc/boot libraries.',
        ],
    }
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    for name, info in audits.items():
        print(name, info['status'], info['size'], info['sha256'][:16],
              'missing=', info['missing_dependencies'], 'unresolved=', info['unresolved_required_symbols'])
    print('renderer reproduces native-probe build:', report['renderer_matches_2026_09_22_native_probe'])
    if not all(i['status'] == 'STATIC_PASS' for i in audits.values()):
        return 1
    return build_unbuf(output, args.report)


if __name__ == '__main__':
    raise SystemExit(main())
