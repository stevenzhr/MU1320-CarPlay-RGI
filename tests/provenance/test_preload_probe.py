"""Fault tests of generated scripts with isolated QNX shims; no ARM execution."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
import test_env_probe as fixture

BASE = fixture.BASE
RESOURCE = fixture.RESOURCE

class PreloadProbeTests(unittest.TestCase):
    def setUp(self):
        self.env = fixture.EnvProbeTests(); self.env.setUp(); self.addCleanup(self.env.doCleanups)
        f = self.f = self.env.f
        self.root = f.app / 'root/mu1320-preload-probe-v1'
        self.sdflag = f.root / 'sd-state'; self.sdflag.write_text('ro\n')
        for p in (BASE / 'preload-probe').iterdir():
            if p.is_file(): shutil.copyfile(p, f.sd / p.name)
        def rewrite(s):
            s = re.sub(r'^PATH=.*$', f'PATH={f.commands}:/usr/bin:/bin', s, flags=re.M)
            s = re.sub(r'/mnt/app|/mnt/system/etc/eso|/mnt/system|/etc/eso|/proc/boot/libc.so.3|/ramdisk|/tmp|/fs/sda0', lambda m: str(f.sd.resolve()) if m.group() == '/fs/sda0' else str(f.vehicle / m.group().lstrip('/')), s)
            return s.replace('in /fs/*)', f'in {f.sd.resolve()}*)').replace(f'in {f.sd.resolve()}/*)', f'in {f.sd.resolve()}*)')
        helper = f.sd / 'mount_state'
        helper.write_text('#!/bin/sh\ncase "$1" in */mnt/app) cat "$MOUNT_FLAG" ;; */mnt/system) cat "$SYSTEM_FLAG" ;; *) cat "$SD_FLAG" ;; esac\n')
        helper.chmod(0o755)
        loader = f.sd / 'loader_check'
        loader.write_text('#!/bin/sh\n[ "${FAIL:-}" != loader ] || exit 4\necho PRELOAD_PROBE_STANDALONE_PASSED\n'); loader.chmod(0o755)
        mount = f.commands / 'mount'
        mount.write_text('''#!/bin/sh
echo "$*" >> "$MOUNT_CALLS"
case "$2" in */mnt/app) flag=$MOUNT_FLAG; kind=app ;; */mnt/system) flag=$SYSTEM_FLAG; kind=system ;; *) flag=$SD_FLAG; kind=sd ;; esac
case "$1" in -uw) [ "${FAIL:-}" != "$kind-rw" ] || exit 81; echo rw > "$flag" ;;
 -ur) [ "${FAIL:-}" != "$kind-ro" ] || exit 82; echo ro > "$flag" ;; *) exit 83 ;; esac
'''); mount.chmod(0o755)
        for name in ['collect_env.sh', 'control.sh', 'preload_probe.sh']:
            content = rewrite((BASE / 'preload-probe' / name).read_text())
            for dep in ['mount_state', 'loader_check', 'collect_env.sh', 'control.sh']:
                if dep == name: continue
                crc, size = subprocess.check_output(['cksum', str(f.sd / dep)], text=True).split()[:2]
                content = re.sub(r'check \d+ \d+ "\$stage_dir/' + re.escape(dep) + '"', f'check {crc} {size} "$stage_dir/{dep}"', content)
            (f.sd / name).write_text(content)
        self.script = f.sd / 'preload_probe.sh'
        pidin = f.commands / 'pidin'
        pidin.write_text(pidin.read_text().replace('mu1320_env_v2_a7f907b7', 'mu1320_preload_v1_b81d024a'))

    def run_action(self, *args, fail='', direct=False):
        f = self.f
        return subprocess.run(['/bin/sh', str(f.sd / 'control.sh' if direct else self.script), *args], capture_output=True, text=True, timeout=25,
                              env=dict(os.environ, MOUNT_FLAG=str(f.flag), SYSTEM_FLAG=str(self.env.s3.sysflag), SD_FLAG=str(self.sdflag),
                                       MOUNT_CALLS=str(f.calls), ACTIVE_FILE=str(self.env.active), PID_MODE='', PID_COUNTER=str(f.root / 'counter'), FAIL=fail))
    def ok(self, *args, **kwargs):
        r = self.run_action(*args, **kwargs); self.assertEqual(r.returncode, 0, r.stdout+r.stderr); return r
    def assert_mounts(self):
        for p in [self.f.flag, self.env.s3.sysflag, self.sdflag]: self.assertEqual(p.read_text(), 'ro\n')

    def test_install_collect_rollback_and_sd_logs(self):
        self.ok('collect', 'before'); self.ok('install')
        self.assertTrue((self.root / 'libmu1320_preload_probe.so').exists())
        self.env.propagate()
        receipt = self.f.vehicle / 'tmp/mu1320-preload-v1-loaded-202'
        receipt.write_text('MU1320_PRELOAD_V1_LOADED pid=202 ppid=101\n')
        result = self.ok('collect', 'marked')
        self.assertIn('MARKER_OBSERVED: role=DIO pid=202', result.stdout)
        self.assertIn('MU1320_PRELOAD_V1_LOADED pid=202 ppid=101', result.stdout)
        self.ok('rollback'); self.env.propagate(); self.ok('collect', 'restored')
        self.f.assert_production_unchanged(); self.assert_mounts()
        self.assertTrue((self.root / 'libmu1320_preload_probe.so').exists(), 'keep library while old SI could reference it')
        self.assertEqual(len(list((self.f.sd / 'out').glob('action-*.txt'))), 5)
        self.assertEqual(len(list((self.f.sd / 'out').glob('marked-*/DIO-202-load-receipt.txt'))), 1)
        self.assertFalse(any(p.is_dir() for p in (self.f.vehicle / 'tmp').iterdir()))

    def test_faults_never_claim_success_and_restore_mounts(self):
        for i, fault in enumerate(['loader', 'backup_copy', 'before_commit', 'after_commit', 'app-rw', 'system-rw', 'sd-rw']):
            with self.subTest(fault=fault):
                if i: self.doCleanups(); self.setUp()
                r = self.run_action('install', fail=fault)
                self.assertNotEqual(r.returncode, 0, r.stdout+r.stderr)
                self.assertNotIn('PRELOAD_PROBE_ACTION_PASSED', r.stdout)
                self.assert_mounts()
                self.ok('rollback'); self.f.assert_production_unchanged()

    def test_sd_restore_failure_is_not_success(self):
        result = self.run_action('status', fail='sd-ro')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('PRELOAD_PROBE_ACTION_PASSED', result.stdout)
        self.assertIn('SD state not restored', result.stderr)

    def test_initial_rw_is_preserved(self):
        self.sdflag.write_text('rw\n'); self.ok('status')
        self.assertEqual(self.sdflag.read_text(), 'rw\n'); self.assertFalse(self.f.calls.exists())

    def test_non_root_rejected_before_sd_remount(self):
        uid = self.f.commands / 'id'
        uid.write_text('#!/bin/sh\necho " 501"\n'); uid.chmod(0o755)
        result = self.run_action('install')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('effective UID must be 0', result.stderr)
        self.assertFalse(self.f.calls.exists()); self.assertFalse(self.root.exists())

    def test_corrupt_library_blocks_config_changes(self):
        (self.f.sd / 'libmu1320_preload_probe.so').write_bytes(b'corrupt')
        result = self.run_action('install')
        self.assertNotEqual(result.returncode, 0); self.assertFalse(self.root.exists())
        self.f.assert_production_unchanged(); self.assert_mounts()

    def test_unknown_config_and_bad_backup_preserved(self):
        self.ok('install'); current = self.env.system.read_bytes()
        (self.root / 'backup/smartphone_integrator.json').write_bytes(b'corrupt')
        self.assertNotEqual(self.run_action('rollback').returncode, 0)
        self.assertEqual(self.env.system.read_bytes(), current); self.assert_mounts()

    def test_sd_unavailable_direct_rollback(self):
        self.ok('install')
        (self.f.sd / 'out').rename(self.f.sd / 'old-out')
        (self.f.sd / 'out').write_text('blocked')
        self.assertNotEqual(self.run_action('rollback').returncode, 0)
        self.ok('rollback', direct=True); self.f.assert_production_unchanged(); self.assert_mounts()

    def test_receipt_collision_is_not_overwritten(self):
        # Compile the actual bounded constructor on host, then load it in a
        # separate process. This validates file semantics, not QNX loader ABI.
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp); lib = temp / 'probe.dylib'
            prefix = str(temp / 'receipt-')
            subprocess.run(['cc', '-dynamiclib' if sys.platform == 'darwin' else '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                            '-DRECEIPT_PREFIX=' + json.dumps(prefix), str(BASE / 'preload-probe/preload_probe.c'), '-o', str(lib)], check=True, capture_output=True)
            code = '''import ctypes,os,sys
from pathlib import Path
p=Path(sys.argv[2]+str(os.getpid()))
if sys.argv[3]=='collision': p.write_text('preserve')
lib=ctypes.CDLL(sys.argv[1]); assert lib.mu1320_preload_probe_identity()==13200401
print(p.read_text(),end='')
'''
            clean = subprocess.check_output([sys.executable, '-c', code, str(lib), prefix, 'clean'], text=True)
            self.assertRegex(clean, r'^MU1320_PRELOAD_V1_LOADED pid=\d+ ppid=\d+\n$')
            collided = subprocess.check_output([sys.executable, '-c', code, str(lib), prefix, 'collision'], text=True)
            self.assertEqual(collided, 'preserve')

if __name__ == '__main__': unittest.main()
