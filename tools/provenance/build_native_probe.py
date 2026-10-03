#!/usr/bin/env python3
"""Build pinned upstream native sources in a private copy; never installs on a vehicle."""
import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
PRIVATE = BASE.parent / "private-data" / "mu1320-rgi"
PREFIX = 'arm-unknown-nto-qnx6.5.0eabi-'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--output', type=Path, default=PRIVATE / 'native-probe')
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        parser.error('output already exists; choose a new path; existing builds are never overwritten')
    if ':' in str(output) or '\n' in str(output):
        parser.error('unsupported Docker bind path')
    manifest = json.loads((BASE / 'reports/source-manifest.json').read_text())
    upstream = BASE.parent / 'mib2q-carplay-rgi'
    verified = {}
    for name, wanted in manifest['files'].items():
        source = upstream / name
        if digest(source) != wanted:
            parser.error('source differs from pinned manifest: ' + name)
        verified[name] = source.read_bytes()
    metadata = json.loads(subprocess.check_output(['docker', 'image', 'inspect', args.image], text=True))[0]
    image = metadata['Id']
    if metadata['Architecture'] != 'amd64' or metadata['Os'] != 'linux' or not re.fullmatch(r'sha256:[0-9a-f]{64}', image):
        parser.error('expected Linux amd64 image with immutable image ID')
    version = subprocess.check_output(['docker', 'run', '--rm', '--network=none',
                                      '--platform=linux/amd64', image, PREFIX + 'gcc', '-dumpversion'], text=True).strip()
    if version != '4.9.4':
        parser.error('expected GCC 4.9.4, received ' + version)
    src = output / 'src'
    src.mkdir(parents=True)
    for name, data in verified.items():
        if name.startswith(('hook/', 'common/', 'maneuver_render/', 'toolchain/', 'scripts/build_')):
            dest = src / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
    (src / 'build').mkdir()
    report = {'deployable': False, 'runtime_tested': False,
              'upstream_commit': manifest['commit'], 'source_manifest_sha256': digest(BASE / 'reports/source-manifest.json'),
              'image_requested': args.image, 'image_id': image, 'compiler_version': version,
              'upstream_abi_checks_preserved': True, 'builds': {}}
    report_path = output / 'build-report.json'
    for name in ('build_hook.sh', 'build_renderers.sh'):
        script = src / 'scripts' / name
        text = script.read_text()
        if text.count('IMG=qnx65-armv7-toolchain:latest') != 1:
            parser.error('unexpected image selector in ' + name)
        text = text.replace('IMG=qnx65-armv7-toolchain:latest', 'IMG=' + image)
        text = text.replace('docker run --rm ', 'docker run --rm --network=none ')
        script.write_text(text)
        log = output / (name + '.log')
        env = dict(os.environ, LOG='1', LOG_RGD_PACKET_RAW='0')
        with log.open('w') as stream:
            result = subprocess.run(['bash', str(script)], cwd=src, env=env,
                                    stdout=stream, stderr=subprocess.STDOUT)
        report['builds'][name] = {'exit_code': result.returncode, 'script_sha256': digest(script),
                                 'log_sha256': digest(log)}
        report_path.write_text(json.dumps(report, indent=2) + '\n')
        print(name, 'exit=', result.returncode, 'log=', log, flush=True)
        if result.returncode:
            print(log.read_text()[-6000:])
            return result.returncode
    report['artifacts'] = {name: {'size': (src / 'build' / name).stat().st_size,
                                 'sha256': digest(src / 'build' / name)}
                           for name in ('libcarplay_hook.so', 'maneuver_render')}
    report['limitations'] = ['Compiler success is not MU1320 dynamic symbol/ABI or runtime validation.',
                            'Renderer import stubs remain inside the build container; never deploy them.',
                            'Pinned upstream native feature set includes cover art; not navigation-only.']
    report_path.write_text(json.dumps(report, indent=2) + '\n')
    print('Private native probes built. Not copied to candidate/ or any vehicle.', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
