"""Host-side transaction tests for the generated gated navigation-hook trial."""
import os
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

import test_preload_probe as fixture

BASE = fixture.BASE
RESOURCE = fixture.RESOURCE


class NavhookTrialTests(unittest.TestCase):
    def setUp(self):
        self.preload = fixture.PreloadProbeTests()
        self.preload.setUp()
        self.addCleanup(self.preload.doCleanups)
        self.f = self.preload.f
        self.env = self.preload.env
        f = self.f
        self.root = f.app / 'root/mu1320-rgi-navhook-v1'
        self.system = self.env.system
        self.active = self.env.active
        self.sdflag = self.preload.sdflag
        self.tmp = f.vehicle / 'tmp'

        # Add the two runtime inputs not needed by the preceding load-only test.
        for local, target in [
            ('cinemo/libNmeNav.so', 'armle/usr/lib/cinemo/libNmeNav.so'),
            ('native-libs/proc/boot/libc.so.3', '../proc/boot/libc.so.3'),
        ]:
            if target.startswith('../'):
                path = f.vehicle / target[3:]
            else:
                path = f.app / target
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(RESOURCE / local, path)

        stage = BASE / 'navhook-trial'
        for path in stage.iterdir():
            if path.is_file():
                shutil.copyfile(path, f.sd / path.name)

        def rewrite(text):
            text = re.sub(r'^PATH=.*$', f'PATH={f.commands}:/usr/bin:/bin', text, flags=re.M)
            text = re.sub(
                r'/mnt/app|/mnt/system/etc/eso|/mnt/system|/etc/eso|/proc/boot|/lib/libsocket\.so\.3|/ramdisk|/tmp|/fs/sda0',
                lambda m: str(f.sd.resolve()) if m.group() == '/fs/sda0'
                else str(f.vehicle / m.group().lstrip('/')),
                text,
            )
            text = text.replace('in /fs/sda0/*)', f'in {f.sd.resolve()}*)')
            text = text.replace(f'in {f.sd.resolve()}/*)', f'in {f.sd.resolve()}*)')
            return text.replace(f'{f.sd.resolve()}/*|/fs/sdb0/*)',
                                f'{f.sd.resolve()}*|/fs/sdb0/*)')

        # Use a fixture-local runtime path inside the SI candidate too.
        candidate = f.sd / 'smartphone_integrator.json'
        old_candidate = candidate.read_bytes()
        candidate.write_text(candidate.read_text().replace(
            '/mnt/app/root/mu1320-rgi-navhook-v1', str(self.root)))

        helper = f.sd / 'mount_state'
        old_helper = helper.read_bytes()
        helper.write_text('#!/bin/sh\ncase "$1" in */mnt/app) cat "$MOUNT_FLAG" ;; */mnt/system) cat "$SYSTEM_FLAG" ;; *) cat "$SD_FLAG" ;; esac\n')
        helper.chmod(0o755)
        loader = f.sd / 'loader_check'
        old_loader = loader.read_bytes()
        loader.write_text('#!/bin/sh\n[ "${FAIL:-}" != loader ] || exit 4\necho STAGE1_LOADER_PASSED\n')
        loader.chmod(0o755)

        def pair_bytes(data):
            import tempfile
            with tempfile.NamedTemporaryFile() as stream:
                stream.write(data); stream.flush()
                return subprocess.check_output(['cksum', stream.name], text=True).split()[:2]

        def pair(path):
            return subprocess.check_output(['cksum', str(path)], text=True).split()[:2]

        replacements = {
            tuple(pair_bytes(old_candidate)): tuple(pair(candidate)),
            tuple(pair_bytes(old_helper)): tuple(pair(helper)),
            tuple(pair_bytes(old_loader)): tuple(pair(loader)),
        }

        collector = f.sd / 'collect_navhook.sh'
        old_collector = collector.read_bytes()
        collector.write_text(rewrite(collector.read_text()))
        replacements[tuple(pair_bytes(old_collector))] = tuple(pair(collector))

        control = f.sd / 'control.sh'
        text = rewrite(control.read_text())
        for old, new in replacements.items():
            text = text.replace(' '.join(old), ' '.join(new))
        control.write_text(text)
        old_control_pair = pair_bytes((stage / 'control.sh').read_bytes())
        new_control_pair = pair(control)

        wrapper = f.sd / 'navhook_trial.sh'
        text = rewrite(wrapper.read_text())
        mount_pair = pair(helper)
        text = re.sub(
            r'\[ "\$\{1:-\}" = \'\d+\' \] && \[ "\$\{2:-\}" = \'\d+\' \] \|\| fail \'mount helper checksum\'',
            f'[ "${{1:-}}" = \'{mount_pair[0]}\' ] && [ "${{2:-}}" = \'{mount_pair[1]}\' ] || fail \'mount helper checksum\'',
            text,
        )
        text = re.sub(
            r'\[ "\$\{1:-\}" = \'\d+\' \] && \[ "\$\{2:-\}" = \'\d+\' \] \|\| fail \'control checksum\'',
            f'[ "${{1:-}}" = \'{new_control_pair[0]}\' ] && [ "${{2:-}}" = \'{new_control_pair[1]}\' ] || fail \'control checksum\'',
            text,
        )
        wrapper.write_text(text)
        self.script = wrapper

        # The control script needs an rm command in the fixture command path.
        rm = f.commands / 'rm'
        rm.write_text('#!/bin/sh\nexec /bin/rm "$@"\n'); rm.chmod(0o755)

        pidin = f.commands / 'pidin'
        pidin.write_text('#!' + sys.executable + '\n' + r'''import os,sys
from pathlib import Path
a=sys.argv[1:]; mode=os.environ.get('PID_MODE',''); dio=os.environ.get('DIO_PID','202')
si='101'; names={si:'/mnt/app/eso/bin/apps/smartphone_integrator',dio:'/mnt/app/eso/bin/apps/dio_manager'}
candidate='MU1320_NAVHOOK_TRIAL=' in Path(os.environ['ACTIVE_FILE']).read_text()
if '-p' not in a:
 fmt=a[a.index('-F')+1] if '-F' in a else ''
 if fmt=='%256n':
  print(names[si])
  if mode!='no_dio': print(names[dio])
 else:
  print('pid parent name')
  print(si+' 1 '+names[si])
  if mode!='no_dio': print(dio+' '+si+' '+names[dio])
 sys.exit(0)
p=a[a.index('-p')+1]; name=names[p]; parent='1' if p==si else si
if 'environment' in a:
 env='LD_LIBRARY_PATH=/proc/boot:/lib IPL_CONFIG_DIR_DIO_MANAGER=/etc/eso/production'
 if p==dio and candidate:
  root=os.environ['RUNTIME_ROOT']
  env='LD_LIBRARY_PATH=/proc/boot:/lib IPL_CONFIG_DIR_DIO_MANAGER='+root+'/config MU1320_NAVHOOK_TRIAL=mu1320_navhook_v1_5c45c31e LD_PRELOAD='+root+'/libcarplay_hook.so'
 print(p+' '+name+' '+env);sys.exit(0)
if 'mem' in a:
 print('pid tid vaddr size flags object')
 print(p+' 1 1000 100 r-x '+(os.environ['RUNTIME_ROOT']+'/libcarplay_hook.so' if p==dio and candidate else '/proc/boot/libc.so.3'))
 sys.exit(0)
print('pid parent name start');print(p+' '+parent+' '+name+' 2026-09-24_00:00:00')
''')
        pidin.chmod(0o755)

    def run_action(self, *args, fail='', mode='', direct=False, dio_pid='202'):
        script = self.f.sd / ('control.sh' if direct else 'navhook_trial.sh')
        return subprocess.run(
            ['/bin/sh', str(script), *args], capture_output=True, text=True, timeout=25,
            env=dict(os.environ, MOUNT_FLAG=str(self.f.flag), SYSTEM_FLAG=str(self.env.s3.sysflag),
                     SD_FLAG=str(self.sdflag), MOUNT_CALLS=str(self.f.calls), FAIL=fail,
                     ACTIVE_FILE=str(self.active), PID_MODE=mode, DIO_PID=dio_pid,
                     RUNTIME_ROOT=str(self.root)),
        )

    def ok(self, *args, **kwargs):
        result = self.run_action(*args, **kwargs)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def propagate(self):
        shutil.copyfile(self.system, self.active)

    def assert_mounts(self):
        for path in [self.f.flag, self.env.s3.sysflag, self.sdflag]:
            self.assertEqual(path.read_text(), 'ro\n')

    def test_full_file_arm_collect_and_runtime_rollback_flow(self):
        self.ok('collect', 'snapshot')
        self.ok('install')
        self.assertTrue((self.root / 'libcarplay_hook.so').is_file())
        self.assertIn('0x5204', (self.root / 'config/dio_manager.json').read_text())
        self.assertNotEqual(self.system.read_bytes(), self.active.read_bytes())
        self.assertNotEqual(self.run_action('arm', mode='no_dio').returncode, 0)

        self.propagate()
        self.ok('arm', mode='no_dio')
        token = self.tmp / 'mu1320-navhook-v1.arm'
        self.assertEqual(token.read_text(), 'MU1320-NAVHOOK-ONE-SHOT-V1\n')
        self.assertTrue((self.tmp / 'carplay_verbose').is_file())

        # Model the first interposed boundary: active DIO consumes the token.
        token.unlink()
        (self.tmp / 'mu1320-navhook-v1-gate-202').write_text(
            'MU1320_NAVHOOK_V1_GATE mode=ACTIVE_TOKEN_CONSUMED pid=202 ppid=101\n')
        (self.tmp / 'carplay_hook.log').write_text(
            "lazy runtime init complete (constructor-free; first Cinemo boundary)\n"
            "Registered module 'routeguidance'\nRouteGuidance Update 0x5202\n")
        armed = self.ok('collect', 'armed')
        self.assertIn('mode=ACTIVE_TOKEN_CONSUMED pid=202 ppid=101', armed.stdout)
        self.assertIn('DIO_ENV_MARKER=1 DIO_ENV_PRELOAD=1', armed.stdout)
        self.assertIn(str(self.root / 'libcarplay_hook.so'), armed.stdout)

        self.ok('rollback')
        self.propagate()
        # A required full restart clears /tmp and starts a fresh stock-env DIO.
        for path in list(self.tmp.iterdir()):
            if path.is_file() or path.is_symlink():
                path.unlink()
        restored = self.ok('collect', 'restored', dio_pid='303')
        self.assertIn('DIO_ENV_MARKER=0 DIO_ENV_PRELOAD=0', restored.stdout)
        self.assertNotIn('MU1320_NAVHOOK_V1_GATE mode=', restored.stdout)
        self.f.assert_production_unchanged()
        self.assert_mounts()
        self.assertTrue(self.root.is_dir(), 'runtime files stay available until stock restart is proved')
        self.assertGreaterEqual(len(list((self.f.sd / 'out').glob('action-*.txt'))), 6)

    def test_arm_rejects_live_dio_and_unknown_ram_files(self):
        self.ok('install'); self.propagate()
        result = self.run_action('arm')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('dio_manager already exists', result.stdout + result.stderr)
        token = self.tmp / 'mu1320-navhook-v1.arm'
        token.write_text('unknown\n')
        result = self.run_action('arm', mode='no_dio')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(token.read_text(), 'unknown\n')

    def test_disarm_preserves_unknown_token_and_moves_owned_token(self):
        self.ok('install'); self.propagate(); self.ok('arm', mode='no_dio')
        self.ok('disarm')
        self.assertFalse((self.tmp / 'mu1320-navhook-v1.arm').exists())
        self.assertEqual(len(list(self.tmp.glob('mu1320-navhook-v1.disarmed.*'))), 1)
        token = self.tmp / 'mu1320-navhook-v1.arm'; token.write_text('unknown\n')
        self.assertNotEqual(self.run_action('disarm').returncode, 0)
        self.assertEqual(token.read_text(), 'unknown\n')

    def test_corrupt_payload_blocks_before_persistent_writes(self):
        (self.f.sd / 'libcarplay_hook.so').write_bytes(b'corrupt')
        result = self.run_action('install')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.root.exists())
        self.f.assert_production_unchanged(); self.assert_mounts()

    def test_loader_failure_keeps_si_stock_and_direct_rollback_recovers(self):
        result = self.run_action('install', fail='loader')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.system.read_bytes(), (RESOURCE / 'smartphone_integrator.json').read_bytes())
        self.assert_mounts()
        # The preserved workspace makes the failed install explicit; baseline rollback is idempotent.
        self.ok('rollback', direct=True)
        self.f.assert_production_unchanged(); self.assert_mounts()

    def test_precommit_system_remount_failure_resumes_verified_workspace(self):
        first = self.run_action('install', fail='system-rw')
        self.assertNotEqual(first.returncode, 0)
        self.assertIn('STOP: system remount rw', first.stdout + first.stderr)
        self.assertTrue((self.root / 'libcarplay_hook.so').is_file())
        self.assertEqual(self.system.read_bytes(), (RESOURCE / 'smartphone_integrator.json').read_bytes())
        self.assert_mounts()
        second = self.ok('install')
        self.assertIn('RESUME_WORKSPACE_VERIFIED', second.stdout)
        self.assertIn('reuse verified private runtime workspace', second.stdout)
        self.assertNotEqual(self.system.read_bytes(), (RESOURCE / 'smartphone_integrator.json').read_bytes())
        self.ok('rollback', direct=True)
        self.f.assert_production_unchanged(); self.assert_mounts()

    def test_vehicle_scripts_never_guard_with_and_fail(self):
        # On the vehicle's QNX 6.5 ksh, `pending=...; exists "$pending" && fail ...`
        # after `trap cleanup 0` exited silently under set -e (v1/v1.1 install).
        for name in ['control.sh', 'collect_navhook.sh', 'navhook_trial.sh']:
            text = (BASE / 'navhook-trial' / name).read_text()
            self.assertNotRegex(text, r'&&\s*fail\b', name)

    def test_sd_restore_failure_cannot_claim_success(self):
        result = self.run_action('status', fail='sd-ro')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('NAVHOOK_TRIAL_ACTION_PASSED', result.stdout)
        self.assertIn('SD state not restored', result.stderr)

    def test_initial_rw_sd_state_is_preserved(self):
        self.sdflag.write_text('rw\n')
        self.ok('status')
        self.assertEqual(self.sdflag.read_text(), 'rw\n')


if __name__ == '__main__':
    unittest.main()
