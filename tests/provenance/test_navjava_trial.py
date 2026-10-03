"""Host transaction tests for the combined native-to-Java ingress trial."""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import test_navhook_trial as fixture

BASE = fixture.BASE
RESOURCE = fixture.RESOURCE


class NavjavaTrialTests(unittest.TestCase):
    # Parametrized so later trials derived from these scripts (F2) reuse the
    # same transaction tests.
    STAGE = "navjava-trial"
    RUNTIME = "mu1320-rgi-navjava-v1"
    NEW_JAR = "CarPlayRGI-MU1320-IngressV1.jar"
    PAYLOAD_JAR = "carplay_mu1320_navjava_ingress_v1.jar.DISABLED"
    WRAPPER = "navjava_trial.sh"
    COLLECTOR = "collect_navjava.sh"
    ENV_MARKER = "MU1320_NAVJAVA_TRIAL=mu1320_navjava_v1_8b972a0d"
    LISTENER = "[CP/W][NavJava] MU1320-NAVJAVA-INGRESS-V1 LISTENER_READY receive-only\n"

    def write_java_evidence(self):
        with (self.tmp / "carplay_java.log").open("a") as stream:
            stream.write("[CP/W][RGI-Ingress] PARSE_OK frame=1 replay=0 keys=3 route_state=6\n")

    def assert_java_evidence(self, stdout):
        self.assertIn("JAVA_PARSE_OK_COUNT=1", stdout)
        self.assertIn("JAVA_PARSE_REJECT_COUNT=0", stdout)

    def setUp(self):
        self.base = fixture.NavhookTrialTests()
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.f = self.base.f
        self.env = self.base.env
        self.system = self.base.system
        self.active = self.base.active
        self.sdflag = self.base.sdflag
        self.tmp = self.base.tmp
        self.root = self.f.app / "root" / self.RUNTIME
        self.jars = self.f.app / "eso/hmi/lsd/jars"
        self.jars.mkdir(parents=True, exist_ok=True)
        for source in (RESOURCE / "jars").iterdir():
            target = self.jars / source.name
            shutil.copyfile(source, target)
            target.chmod(0o777 if source.name == "NavActiveIgnore.jar" else 0o644)
        self.old = self.jars / "NavActiveIgnore.jar"
        self.old_bytes = self.old.read_bytes()
        self.new = self.jars / self.NEW_JAR

        stage = BASE / self.STAGE
        for path in stage.iterdir():
            if path.is_file():
                shutil.copyfile(path, self.f.sd / path.name)

        def rewrite(text):
            text = re.sub(r"^PATH=.*$", f"PATH={self.f.commands}:/usr/bin:/bin", text,
                          flags=re.M)
            text = re.sub(
                r"/mnt/app|/mnt/system/etc/eso|/mnt/system|/etc/eso|/proc/boot|"
                r"/lib/libsocket\.so\.3|/ramdisk|/tmp|/fs/sda0",
                lambda match: str(self.f.sd.resolve()) if match.group() == "/fs/sda0"
                else str(self.f.vehicle / match.group().lstrip("/")), text)
            text = text.replace("in /fs/sda0/*)", f"in {self.f.sd.resolve()}*)")
            text = text.replace(f"in {self.f.sd.resolve()}/*)", f"in {self.f.sd.resolve()}*)")
            return text.replace(f"{self.f.sd.resolve()}/*|/fs/sdb0/*)",
                                f"{self.f.sd.resolve()}*|/fs/sdb0/*)")

        candidate = self.f.sd / "smartphone_integrator.json"
        old_candidate = candidate.read_bytes()
        candidate.write_text(candidate.read_text().replace(
            "/mnt/app/root/" + self.RUNTIME, str(self.root)))

        helper = self.f.sd / "mount_state"
        old_helper = helper.read_bytes()
        helper.write_text("#!/bin/sh\ncase \"$1\" in */mnt/app) cat \"$MOUNT_FLAG\" ;; "
                          "*/mnt/system) cat \"$SYSTEM_FLAG\" ;; *) cat \"$SD_FLAG\" ;; esac\n")
        helper.chmod(0o755)
        loader = self.f.sd / "loader_check"
        old_loader = loader.read_bytes()
        loader.write_text("#!/bin/sh\n[ \"${FAIL:-}\" != loader ] || exit 4\n"
                          "echo NAVJAVA_LOADER_PASSED\n")
        loader.chmod(0o755)

        def pair_bytes(data):
            with tempfile.NamedTemporaryFile() as stream:
                stream.write(data)
                stream.flush()
                return subprocess.check_output(["cksum", stream.name], text=True).split()[:2]

        def pair(path):
            return subprocess.check_output(["cksum", str(path)], text=True).split()[:2]

        replacements = {
            tuple(pair_bytes(old_candidate)): tuple(pair(candidate)),
            tuple(pair_bytes(old_helper)): tuple(pair(helper)),
            tuple(pair_bytes(old_loader)): tuple(pair(loader)),
        }
        collector = self.f.sd / self.COLLECTOR
        old_collector = collector.read_bytes()
        collector.write_text(rewrite(collector.read_text()))
        replacements[tuple(pair_bytes(old_collector))] = tuple(pair(collector))

        control = self.f.sd / "control.sh"
        original_control = control.read_bytes()
        text = rewrite(control.read_text())
        for old, new in replacements.items():
            text = text.replace(" ".join(old), " ".join(new))
        control.write_text(text)
        new_control_pair = pair(control)

        wrapper = self.f.sd / self.WRAPPER
        text = rewrite(wrapper.read_text())
        mount_pair = pair(helper)
        text = re.sub(
            r"\[ \"\$\{1:-\}\" = '\d+' \] && \[ \"\$\{2:-\}\" = '\d+' \] \|\| fail 'mount helper checksum'",
            f'[ "${{1:-}}" = \'{mount_pair[0]}\' ] && [ "${{2:-}}" = \'{mount_pair[1]}\' ] || fail \'mount helper checksum\'',
            text)
        text = re.sub(
            r"\[ \"\$\{1:-\}\" = '\d+' \] && \[ \"\$\{2:-\}\" = '\d+' \] \|\| fail 'control checksum'",
            f'[ "${{1:-}}" = \'{new_control_pair[0]}\' ] && [ "${{2:-}}" = \'{new_control_pair[1]}\' ] || fail \'control checksum\'',
            text)
        wrapper.write_text(text)
        self.script = wrapper

        pidin = self.f.commands / "pidin"
        pidin.write_text("#!" + sys.executable + "\n" + r'''import os,sys
from pathlib import Path
a=sys.argv[1:]; mode=os.environ.get('PID_MODE',''); dio=os.environ.get('DIO_PID','202')
si='101'; names={si:'/mnt/app/eso/bin/apps/smartphone_integrator',dio:'/mnt/app/eso/bin/apps/dio_manager'}
candidate=os.environ['ENV_MARKER'].split('=')[0]+'=' in Path(os.environ['ACTIVE_FILE']).read_text()
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
  env='LD_LIBRARY_PATH=/proc/boot:/lib IPL_CONFIG_DIR_DIO_MANAGER='+root+'/config '+os.environ['ENV_MARKER']+' LD_PRELOAD='+root+'/libcarplay_hook.so'
 print(p+' '+name+' '+env);sys.exit(0)
if 'mem' in a:
 print('pid tid vaddr size flags object')
 print(p+' 1 1000 100 r-x '+(os.environ['RUNTIME_ROOT']+'/libcarplay_hook.so' if p==dio and candidate else '/proc/boot/libc.so.3'))
 sys.exit(0)
print('pid parent name start');print(p+' '+parent+' '+name+' 2026-09-24_00:00:00')
''')
        pidin.chmod(0o755)

    def run_action(self, *args, fail="", mode="", direct=False, dio_pid="202"):
        script = self.f.sd / ("control.sh" if direct else self.WRAPPER)
        return subprocess.run(
            ["/bin/sh", str(script), *args], capture_output=True, text=True, timeout=25,
            env=dict(os.environ, MOUNT_FLAG=str(self.f.flag),
                     SYSTEM_FLAG=str(self.env.s3.sysflag), SD_FLAG=str(self.sdflag),
                     MOUNT_CALLS=str(self.f.calls), FAIL=fail, ACTIVE_FILE=str(self.active),
                     PID_MODE=mode, DIO_PID=dio_pid, RUNTIME_ROOT=str(self.root),
                     ENV_MARKER=self.ENV_MARKER))

    def ok(self, *args, **kwargs):
        result = self.run_action(*args, **kwargs)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def propagate(self):
        shutil.copyfile(self.system, self.active)

    def assert_mounts(self):
        for path in [self.f.flag, self.env.s3.sysflag, self.sdflag]:
            self.assertEqual(path.read_text(), "ro\n")

    def test_install_arm_parse_collect_and_rollback(self):
        self.ok("install")
        self.assertTrue(self.new.is_file())
        self.assertEqual(self.old.read_bytes(), self.old_bytes)
        self.assertEqual((self.root / "backup/NavActiveIgnore.jar").read_bytes(), self.old_bytes)
        self.assertNotEqual(self.system.read_bytes(), self.active.read_bytes())
        self.assertNotEqual(self.run_action("arm", mode="no_dio").returncode, 0)

        self.propagate()
        (self.tmp / "carplay_java.log").write_text(self.LISTENER)
        self.ok("arm", mode="no_dio")
        token = self.tmp / "mu1320-navhook-v1.arm"
        token.unlink()
        (self.tmp / "mu1320-navhook-v1-gate-202").write_text(
            "MU1320_NAVHOOK_V1_GATE mode=ACTIVE_TOKEN_CONSUMED pid=202 ppid=101\n")
        (self.tmp / "carplay_hook.log").write_text(
            "Registered module 'routeguidance'\nIdentify patched\nUpdate: state=6\nManeuver: idx=0\n")
        self.write_java_evidence()
        armed = self.ok("collect", "armed")
        self.assertIn("GLOBAL_GATE_RECEIPT_COUNT=1", armed.stdout)
        self.assert_java_evidence(armed.stdout)
        self.assertIn("DIO_ENV_MARKER=1 DIO_ENV_PRELOAD=1", armed.stdout)

        self.ok("rollback")
        self.assertFalse(self.new.exists())
        self.assertEqual(self.old.read_bytes(), self.old_bytes)
        self.propagate()
        for path in list(self.tmp.iterdir()):
            if path.is_file() or path.is_symlink():
                path.unlink()
        restored = self.ok("collect", "restored", dio_pid="303")
        self.assertIn("DIO_ENV_MARKER=0 DIO_ENV_PRELOAD=0", restored.stdout)
        self.assert_mounts()

    def test_arm_requires_java_listener_marker(self):
        self.ok("install")
        self.propagate()
        result = self.run_action("arm", mode="no_dio")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Java log absent", result.stdout + result.stderr)
        (self.tmp / "carplay_java.log").write_text("wrong build\n")
        result = self.run_action("arm", mode="no_dio")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("listener marker absent", result.stdout + result.stderr)

    def test_unknown_archive_and_corrupt_payload_stop_before_writes(self):
        unknown = self.jars / "unexpected.jar"
        unknown.write_text("unknown")
        result = self.run_action("install")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.root.exists())
        unknown.unlink()
        (self.f.sd / self.PAYLOAD_JAR).write_text("bad")
        result = self.run_action("install")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.root.exists())

    def test_system_remount_failure_rolls_back_installed_java(self):
        result = self.run_action("install", fail="system-rw")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.new.exists(), "known partial install is journaled and preserved")
        self.assertEqual(self.system.read_bytes(), (RESOURCE / "smartphone_integrator.json").read_bytes())
        self.ok("rollback", direct=True)
        self.assertFalse(self.new.exists())
        self.assertEqual(self.old.read_bytes(), self.old_bytes)
        self.assert_mounts()

    def test_partial_workspace_from_interrupted_install_resumes(self):
        self.root.mkdir(mode=0o700)
        (self.root / "backup").mkdir(mode=0o700)
        (self.root / "IDENTITY").write_text("truncated")
        result = self.ok("install")
        self.assertIn("RESUME_WORKSPACE", result.stdout)
        self.assertIn("install_STEP: write identity", result.stdout)
        self.assertTrue(self.new.is_file())
        self.assertEqual((self.root / "backup/NavActiveIgnore.jar").read_bytes(), self.old_bytes)
        self.assert_mounts()

    def test_reinstall_keeps_exact_hook_inode(self):
        # A cached SI can still start a DIO that maps the old hook; never rewrite it in place.
        self.ok("install")
        self.ok("rollback", direct=True)
        inode = (self.root / "libcarplay_hook.so").stat().st_ino
        result = self.ok("install")
        self.assertIn("runtime hook already exact", result.stdout)
        self.assertEqual((self.root / "libcarplay_hook.so").stat().st_ino, inode)

    def test_arm_detects_dio_with_vehicle_padded_pidin_name(self):
        # Vehicle pidin pads the name field: " mnt/app/eso/bin/apps/dio_manager ".
        pidin = self.f.commands / "pidin"
        pidin.write_text(pidin.read_text().replace(
            "  if mode!='no_dio': print(names[dio])",
            "  if mode!='no_dio': print(' '+names[dio].lstrip('/')+' ')"))
        self.ok("install")
        self.propagate()
        (self.tmp / "carplay_java.log").write_text(self.LISTENER)
        result = self.run_action("arm")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("dio_manager already exists", result.stdout + result.stderr)
        self.assertFalse((self.tmp / "mu1320-navhook-v1.arm").exists())

    def test_saved_action_log_has_control_exit_and_terminal_has_outer_exit(self):
        result = self.ok("status")
        logs = list((self.f.sd / "out").glob("action-status-*.txt"))
        self.assertEqual(len(logs), 1)
        self.assertIn("CONTROL_EXIT=0", logs[0].read_text())
        self.assertIn("OUTER_EXIT: 0", result.stdout)
        self.assertIn("SD_MOUNT_RESTORED", result.stdout)

    def test_scripts_keep_globbing_for_global_receipts_and_avoid_and_fail(self):
        collector = (BASE / self.STAGE / self.COLLECTOR).read_text()
        self.assertNotRegex(collector, r"(?m)^set -f$")
        self.assertIn("for f in /tmp/mu1320-navhook-v1-gate-*", collector)
        control = (BASE / self.STAGE / "control.sh").read_text()
        self.assertNotRegex(control, r"exists [^\n;]*&&\s*fail")


if __name__ == "__main__":
    unittest.main()
