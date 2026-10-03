#!/usr/bin/env python3
"""Generate Stage4 load-only trial from the already exercised env-probe scripts.

The original templates and old shipped packages are not modified. Every source
transformation asserts its anchor, and the JSON delta is compared structurally.
"""
import copy
import difflib
import hashlib
import json
import re
import subprocess
from pathlib import Path
from formats import config

BASE = Path(__file__).resolve().parents[1]
STAGE = BASE / 'preload-probe'
RESOURCE = BASE.parent / 'resource'
ROOT = '/mnt/app/root/mu1320-preload-probe-v1'
LIBRARY = ROOT + '/libmu1320_preload_probe.so'
MARKER = 'mu1320_preload_v1_b81d024a'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def crc(p): return subprocess.check_output(['cksum', str(p)], text=True).split()[:2]
def replace(source, old, new):
    assert source.count(old) == 1, old
    return source.replace(old, new)

def main():
    original = RESOURCE / 'smartphone_integrator.json'
    assert sha(original) == 'dd7bf2233198eaf26d7fefc0f01f459c1ce291e0d881eb0b9beeb2ecf4d1055d'
    source = original.read_text()
    start = source.index('"carplay":{'); end = source.index('"carlife":{', start)
    needle = '"IPL_CONFIG_DIR_DIO_MANAGER=/etc/eso/production"]'
    part = replace(source[start:end], needle, needle[:-1] + ', "MU1320_SI_PROBE=' + MARKER + '", "LD_PRELOAD=' + LIBRARY + '"]')
    patched = source[:start] + part + source[end:]
    expected = copy.deepcopy(config(source))
    expected['children']['carplay']['envs'] += ['MU1320_SI_PROBE=' + MARKER, 'LD_PRELOAD=' + LIBRARY]
    assert config(patched) == expected
    (STAGE / 'smartphone_integrator.json').write_text(patched)
    (STAGE / 'IDENTITY').write_text('MU1320-PRELOAD-LOAD-ONLY-V1\n')
    values = {'MARKER': MARKER, 'VERSION': 'v1'}
    def pin(label, p):
        c, n = crc(p); values[label + '_CRC'] = c; values[label + '_SIZE'] = n
    for label, p in [('OLD', original), ('NEW', STAGE / 'smartphone_integrator.json'),
                     ('IDENTITY', STAGE / 'IDENTITY'), ('MOUNT', STAGE / 'mount_state'),
                     ('LIB', STAGE / 'libmu1320_preload_probe.so'), ('LOADER', STAGE / 'loader_check')]:
        pin(label, p)
    def render(content, name):
        for k, v in values.items(): content = content.replace('@' + k + '@', v)
        assert not re.search(r'@[A-Z_]+@', content)
        (STAGE / name).write_text(content)
        subprocess.run(['/bin/sh', '-n', str(STAGE / name)], check=True)
    def common(content):
        return content.replace('mu1320-env-probe-@VERSION@', 'mu1320-preload-probe-v1').replace('ENV_PROBE', 'PRELOAD_PROBE').replace('env_probe.sh', 'preload_probe.sh')
    collector = common((BASE / 'scripts/collect_env.sh.in').read_text())
    collector = replace(collector, '    echo IDENTITY_AFTER', '''    echo PRELOAD_RECEIPT_BEGIN
    receipt="/tmp/mu1320-preload-v1-loaded-$obs_pid"
    if [ -f "$receipt" ] && [ ! -L "$receipt" ]; then
        cp "$receipt" "$logdir/$obs_role-$obs_pid-load-receipt.txt"
        cat "$receipt"
    else echo NO_RECEIPT; fi
    echo PRELOAD_RECEIPT_END
    echo MEMORY_MAP_BEGIN
    pidin -p "$obs_pid" mem > "$logdir/$obs_role-$obs_pid-mem.txt" 2>&1
    echo "MEMORY_MAP_EXIT=$?"
    cat "$logdir/$obs_role-$obs_pid-mem.txt"
    echo MEMORY_MAP_END
    # Include receipt/map collection in the identity race check.
    identity_after=$(identity "$obs_pid" 2>&1); identity_after_rc=$?
    echo IDENTITY_AFTER''')
    collector = replace(collector, 'pidin mkdir cat cksum tr sync', 'pidin mkdir cat cksum tr sync cp')
    collector = replace(collector, 'no automatic preload decision', 'a marker alone is not proof of library loading; compare DIO receipt, map and full restart evidence')
    render(collector, 'collect_env.sh'); pin('COLLECT', STAGE / 'collect_env.sh')
    control = common((BASE / 'scripts/env_probe.sh.in').read_text())
    control = replace(control, '# MU1320 env-only controlled trial. No hook, wrapper, DIO replacement or Java.',
                      '# Stage4 load-only trial. No navigation hook, wrapper, DIO replacement or Java.')
    checks = []
    for name in ['smartphone_integrator', 'dio_manager']:
        c, n = crc(RESOURCE / name)
        checks.append(f'check {c} {n} /mnt/app/eso/bin/apps/{name} || fail "{name} baseline"')
    checks += ['check @LIB_CRC@ @LIB_SIZE@ "$stage_dir/libmu1320_preload_probe.so" || fail "probe library checksum"',
               'check @LOADER_CRC@ @LOADER_SIZE@ "$stage_dir/loader_check" || fail "loader checksum"']
    # Expand the nested values now; the general renderer is intentionally one pass.
    native = '\n    '.join(checks)
    for k, v in values.items(): native = native.replace('@' + k + '@', v)
    values['NATIVE_CHECKS'] = native
    control = replace(control, '    source="$stage_dir/smartphone_integrator.json"', '''    # Library is complete and smoke-tested before SI can ever refer to it.
    cp "$stage_dir/libmu1320_preload_probe.so" "$ROOT/libmu1320_preload_probe.so"
    chmod 644 "$ROOT/libmu1320_preload_probe.so"
    check @LIB_CRC@ @LIB_SIZE@ "$ROOT/libmu1320_preload_probe.so" || fail 'installed library checksum'
    [ "$(attrs "$ROOT/libmu1320_preload_probe.so")" = '-rw-r--r-- 0 0' ] || fail 'installed library attributes'
    sync
    run_clean "$stage_dir/loader_check" "$ROOT/libmu1320_preload_probe.so" || fail 'standalone loader; SI has not been patched'
    source="$stage_dir/smartphone_integrator.json"''')
    control = control.replace('.mu1320-env-probe-', '.mu1320-preload-probe-')
    render(control, 'control.sh'); pin('CONTROL', STAGE / 'control.sh')
    render((BASE / 'scripts/preload_sd.sh.in').read_text(), 'preload_probe.sh')
    (BASE / 'reports/preload-probe-si.diff').write_text(''.join(difflib.unified_diff(source.splitlines(True), patched.splitlines(True), fromfile='stock/SI', tofile='preload-probe/SI')))
    report = dict(marker=MARKER, library_path=LIBRARY, runtime_tested=False,
                  toolchain_image='sha256:e52565b1f62dab0f93f12532d52611b94e90b89e4da04f972b11f54eaeb6a05d',
                  build_script_sha256=sha(BASE / 'scripts/build_preload_probe.sh'),
                  scope='LD_PRELOAD load receipt only; no interposition or navigation protocol changes',
                  source_templates={n: sha(BASE / 'scripts' / n) for n in ['env_probe.sh.in', 'collect_env.sh.in', 'preload_sd.sh.in']},
                  files={p.name: sha(p) for p in STAGE.iterdir() if p.is_file() and p.name != 'SHA256SUMS'})
    (BASE / 'reports/preload-probe-build.json').write_text(json.dumps(report, indent=2) + '\n')
    print('Generated load-only trial; old packages unchanged.')
if __name__ == '__main__': main()
