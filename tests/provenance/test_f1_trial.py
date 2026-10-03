"""Host transaction tests for the F1 NavActiveIgnore isolation trial."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import test_navhook_trial as fixture

BASE = fixture.BASE
RESOURCE = fixture.RESOURCE
STAGE = BASE / "f1-trial"  # v1; subclasses override the class attributes below


def pair(path):
    return subprocess.check_output(["cksum", str(path)], text=True).split()[:2]


def pair_bytes(data):
    with tempfile.NamedTemporaryFile() as stream:
        stream.write(data)
        stream.flush()
        return pair(stream.name)


class F1TrialTests(unittest.TestCase):
    STAGE = STAGE
    VERSION = "v1"
    ARCHIVE = "CarPlayRGI-MU1320-F1NaviSeam.jar"
    PAYLOAD = "carplay_mu1320_f1_naviseam_v1.jar.DISABLED"
    JAR_ENTRIES = 2

    def setUp(self):
        self.base = fixture.NavhookTrialTests()
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        f = self.f = self.base.f
        self.env = self.base.env
        self.sdflag = self.base.sdflag
        self.tmp = self.base.tmp
        self.root = f.app / ("root/mu1320-rgi-f1-" + self.VERSION)
        self.jars = f.app / "eso/hmi/lsd/jars"
        self.jars.mkdir(parents=True, exist_ok=True)
        for source in (RESOURCE / "jars").iterdir():
            target = self.jars / source.name
            shutil.copyfile(source, target)
            target.chmod(0o777 if source.name == "NavActiveIgnore.jar" else 0o644)
        self.old = self.jars / "NavActiveIgnore.jar"
        self.old_bytes = self.old.read_bytes()
        self.new = self.jars / self.ARCHIVE
        self.quarantine = self.root / "quarantine/NavActiveIgnore.jar"
        self.baseline_set = sorted(p.name for p in self.jars.iterdir())
        for path in self.STAGE.iterdir():
            shutil.copyfile(path, f.sd / path.name)

        def rewrite(text):
            text = re.sub(r"^PATH=.*$", f"PATH={f.commands}:/usr/bin:/bin", text, flags=re.M)
            text = re.sub(
                r"/mnt/app|/mnt/system/etc/eso|/mnt/system|/etc/eso|/proc/boot|/tmp|/fs/sda0",
                lambda m: str(f.sd.resolve()) if m.group() == "/fs/sda0"
                else str(f.vehicle / m.group().lstrip("/")), text)
            text = text.replace("in /fs/sda0/*)", f"in {f.sd.resolve()}*)")
            text = text.replace(f"in {f.sd.resolve()}/*)", f"in {f.sd.resolve()}*)")
            return text.replace(f"{f.sd.resolve()}/*|/fs/sdb0/*)", f"{f.sd.resolve()}*|/fs/sdb0/*)")

        helper = f.sd / "mount_state"
        old_helper = helper.read_bytes()
        helper.write_text('#!/bin/sh\ncase "$1" in */mnt/app) cat "$MOUNT_FLAG" ;; '
                          '*/mnt/system) cat "$SYSTEM_FLAG" ;; *) cat "$SD_FLAG" ;; esac\n')
        helper.chmod(0o755)
        replacements = {tuple(pair_bytes(old_helper)): tuple(pair(helper))}
        collector = f.sd / "collect_f1.sh"
        old_collector = collector.read_bytes()
        collector.write_text(rewrite(collector.read_text()))
        replacements[tuple(pair_bytes(old_collector))] = tuple(pair(collector))
        control = f.sd / "control.sh"
        text = rewrite(control.read_text())
        for old, new in replacements.items():
            text = text.replace(" ".join(old), " ".join(new))
        control.write_text(text)
        wrapper = f.sd / "f1_trial.sh"
        text = rewrite(wrapper.read_text())
        for label, path in [("mount helper checksum", helper), ("control checksum", control)]:
            c, n = pair(path)
            text = re.sub(r"\[ \"\$\{1:-\}\" = '\d+' \] && \[ \"\$\{2:-\}\" = '\d+' \] \|\| fail '" + label + "'",
                          f"[ \"${{1:-}}\" = '{c}' ] && [ \"${{2:-}}\" = '{n}' ] || fail '{label}'", text)
        wrapper.write_text(text)

        # mv with fault points for the two scan-tree renames.
        mv = f.commands / "mv"
        mv.write_text('#!/bin/sh\ncase "$*" in\n'
                      ' *NavActiveIgnore.jar\\ */quarantine/NavActiveIgnore.jar) [ "${FAIL:-}" != quarantine ] || exit 92 ;;\n'
                      ' *.mu1320-f1.pending.*' + self.ARCHIVE + ') [ "${FAIL:-}" != java_commit ] || exit 93 ;;\n'
                      'esac\n[ "$(cat "$MOUNT_FLAG")" = rw ] || exit 88\nexec /bin/mv "$@"\n')
        mv.chmod(0o755)
        find = f.commands / "find"
        find.write_text('#!/bin/sh\nexec /usr/bin/find "$@"\n')
        find.chmod(0o755)

    def run_action(self, *args, fail="", direct=False):
        script = self.f.sd / ("control.sh" if direct else "f1_trial.sh")
        return subprocess.run(
            ["/bin/sh", str(script), *args], capture_output=True, text=True, timeout=25,
            env=dict(os.environ, MOUNT_FLAG=str(self.f.flag), SYSTEM_FLAG=str(self.env.s3.sysflag),
                     SD_FLAG=str(self.sdflag), MOUNT_CALLS=str(self.f.calls), FAIL=fail,
                     ACTIVE_FILE=str(self.env.active), PID_MODE="", DIO_PID="202",
                     RUNTIME_ROOT=str(self.root)))

    def ok(self, *args, **kwargs):
        result = self.run_action(*args, **kwargs)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def assert_mounts(self):
        for path in [self.f.flag, self.env.s3.sysflag, self.sdflag]:
            self.assertEqual(path.read_text(), "ro\n")

    def assert_baseline(self):
        self.assertEqual(self.old.read_bytes(), self.old_bytes)
        self.assertEqual(self.old.stat().st_mode & 0o777, 0o777)
        self.assertFalse(self.new.exists())
        self.assertEqual(sorted(p.name for p in self.jars.iterdir()), self.baseline_set)

    def reboot(self):
        for path in list(self.tmp.iterdir()):
            if path.is_file():
                path.unlink()

    def test_status_is_baseline(self):
        result = self.ok("status")
        self.assertIn("FILES: INSTALLATION_BASELINE", result.stdout)
        self.assertIn("NAV_ACTIVE_IGNORE: ACTIVE_BASELINE", result.stdout)
        self.assertIn("SYSTEM_CONFIG: BASELINE", result.stdout)

    def test_install_collect_rollback_restored(self):
        result = self.ok("install")
        self.assertIn("F1_install_FILES_PASSED", result.stdout)
        self.assertFalse(self.old.exists())
        self.assertEqual(self.quarantine.read_bytes(), self.old_bytes)
        self.assertEqual((self.root / "backup/NavActiveIgnore.jar").read_bytes(), self.old_bytes)
        with zipfile.ZipFile(self.new) as archive:
            self.assertEqual(len(archive.namelist()), self.JAR_ENTRIES)
        self.assertEqual((self.root / "phase.txt").read_text(), "F1_INSTALLED\n")
        self.assertEqual(self.env.system.read_bytes(), (RESOURCE / "smartphone_integrator.json").read_bytes())
        self.assertNotIn("mnt/system", self.f.calls.read_text() if self.f.calls.exists() else "")
        self.assert_mounts()
        self.assertIn("FILES: F1_INSTALLED", self.ok("status").stdout)
        self.assertIn("INSTALL_ALREADY_COMPLETE", self.ok("install").stdout)

        self.reboot()
        self.check_f1_collect()

        self.assertIn("F1_rollback_FILES_PASSED", self.ok("rollback").stdout)
        self.assert_baseline()
        self.assertEqual((self.root / "phase.txt").read_text(), "INSTALLATION_BASELINE_RESTORED\n")
        self.assertIn("ROLLBACK_ALREADY_BASELINE", self.ok("rollback").stdout)
        self.reboot()
        self.check_restored_collect(self.ok("collect", "restored"))
        self.assert_mounts()

    def check_f1_collect(self):
        (self.tmp / "mu1320-f1-naviseam.log").write_text(
            "1 MU1320-F1-NAVISEAM-V1 ACTIVE stock_appstate_getters=1\n"
            "2 APPSTATE seq=1 id=2 owner=2 speech=0 action=SUPPRESS_NAVI\n"
            "3 APPSTATE seq=2 id=1 owner=2 speech=1 action=STOCK\n"
            "4 APPSTATE seq=3 id=3 owner=2 speech=3 action=STOCK\n")
        f1 = self.ok("collect", "f1")
        for line in ["F1_ACTIVE_STOCK_GETTERS=1", "F1_ACTIVE_NAVIGNORE_GETTERS=0", "F1_SUPPRESS_NAVI=1",
                     "F1_STOCK_PHONE=1", "F1_STOCK_SPEECH=1", "F1_STOCK_OTHER=0", "F1_LOG_PRESENT=1",
                     "ABSENT: " + str(self.tmp / "mu1320-f1-v1.install-witness"), "DIO_ENV_PRELOAD=0"]:
            self.assertIn(line, f1.stdout)

    def check_restored_collect(self, restored):
        self.assertIn("F1_LOG_PRESENT=0", restored.stdout)

    def test_rollback_uses_backup_when_quarantine_is_damaged(self):
        self.ok("install")
        self.quarantine.write_bytes(b"damaged")
        self.ok("rollback")
        self.assert_baseline()

    def test_interrupted_java_commit_leaves_baseline_then_resumes(self):
        result = self.run_action("install", fail="java_commit")
        self.assertNotEqual(result.returncode, 0)
        self.assert_baseline()
        self.assert_mounts()
        self.ok("install")
        self.assertFalse(self.old.exists())
        self.assertTrue(self.new.is_file())

    def test_interrupted_quarantine_is_resumable_and_rollbackable(self):
        result = self.run_action("install", fail="quarantine")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("INSTALL_INCOMPLETE", result.stdout + result.stderr)
        self.assertTrue(self.old.exists() and self.new.exists())
        self.assertIn("FILES: PARTIAL_F1_WITH_NAVIGNORE", self.ok("status").stdout)
        self.ok("rollback", direct=True)
        self.assert_baseline()
        self.run_action("install", fail="quarantine")
        resumed = self.ok("install")
        self.assertIn("RESUME_INSTALL", resumed.stdout)
        self.assertEqual(self.quarantine.read_bytes(), self.old_bytes)
        self.assert_mounts()

    def test_unknown_archive_or_modified_navignore_stops_before_writes(self):
        extra = self.jars / "sub/unexpected.jar"
        extra.parent.mkdir()
        extra.write_text("x")
        result = self.run_action("install")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown HMI archive", result.stdout + result.stderr)
        self.assertFalse(self.root.exists())
        extra.unlink()
        self.old.write_bytes(self.old_bytes + b"x")
        result = self.run_action("install")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.root.exists())
        self.assertFalse(self.new.exists())

    def test_install_refuses_native_trial_leftovers(self):
        (self.tmp / "carplay_verbose").write_text("x")
        result = self.run_action("install")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("trial marker present", result.stdout + result.stderr)
        (self.tmp / "carplay_verbose").unlink()
        self.env.system.write_text(self.env.system.read_text() + " ")
        result = self.run_action("install")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.root.exists())

    def test_corrupt_payload_stops_before_writes(self):
        (self.f.sd / self.PAYLOAD).write_text("bad")
        result = self.run_action("install")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.root.exists())
        self.assert_baseline()

    def test_navignore_left_in_scan_tree_detected_by_collector(self):
        (self.tmp / "mu1320-f1-naviseam.log").write_text(
            "1 MU1320-F1-NAVISEAM-V1 ACTIVE stock_appstate_getters=0\n"
            "2 APPSTATE seq=1 id=0 owner=0 speech=0 action=STOCK\n")
        result = self.ok("collect", "snapshot")
        self.assertIn("F1_ACTIVE_NAVIGNORE_GETTERS=1", result.stdout)
        self.assertIn("F1_SUPPRESS_NAVI=0", result.stdout)
        self.assertIn("F1_STOCK_OTHER=1", result.stdout)

    def test_scripts_avoid_and_fail_guard(self):
        for name in ["control.sh", "collect_f1.sh", "f1_trial.sh"]:
            self.assertNotRegex((self.STAGE / name).read_text(), r"exists [^\n;]*&&\s*fail")


class F1V2TrialTests(F1TrialTests):
    STAGE = BASE / "f1-trial-v2"
    VERSION = "v2"
    ARCHIVE = "CarPlayRGI-MU1320-F1NaviV2.jar"
    PAYLOAD = "carplay_mu1320_f1_navi_v2.jar.DISABLED"
    JAR_ENTRIES = 13

    def setUp(self):
        super().setUp()
        sloginfo = self.f.commands / "sloginfo"
        sloginfo.write_text("#!/bin/sh\necho 'Sep 25 00:01 j9 unrelated line'\n"
                            "echo 'Sep 25 00:02 j9 java.lang.VerifyError: sample terminalmode'\n")
        sloginfo.chmod(0o755)
        pidin = self.f.commands / "pidin"
        pidin.write_text(pidin.read_text().replace(
            "  print(si+' 1 '+names[si])", "  print('790585 1 ifs/jre/bin/j9')\n  print(si+' 1 '+names[si])"))

    def check_f1_collect(self):
        f1 = self.ok("collect", "f1")
        for line in ["ABSENT: " + str(self.tmp / "mu1320-f1-v2.install-witness"), "DIO_ENV_PRELOAD=0",
                     "HMI_J9 pid=790585", "HMI_J9_PROCESSES=1", "SLOG_EXCERPT_BEGIN lines=1",
                     "java.lang.VerifyError", str(self.new)]:
            self.assertIn(line, f1.stdout)
        self.assertNotIn(str(self.old), f1.stdout.split("HMI_ARCHIVES_END")[0])
        saved = sorted((self.f.sd / "out").glob("f1-*/sloginfo.txt"))
        self.assertEqual(len(saved), 1)
        self.assertEqual(len(saved[0].read_text().splitlines()), 2)

    def check_restored_collect(self, restored):
        self.assertIn("ABSENT: " + str(self.tmp / "mu1320-f1-v2.rollback-witness"), restored.stdout)
        self.assertIn(str(self.old), restored.stdout.split("HMI_ARCHIVES_END")[0])

    def test_navignore_left_in_scan_tree_detected_by_collector(self):
        # v2 has no seam log; a leftover NavActiveIgnore shows up in the archive list instead.
        self.ok("install")
        shutil.copyfile(self.quarantine, self.old)
        result = self.ok("collect", "snapshot")
        self.assertIn(str(self.old), result.stdout.split("HMI_ARCHIVES_END")[0])
        self.assertIn("FILES: UNKNOWN", result.stdout)

    def test_collector_survives_missing_sloginfo(self):
        (self.f.commands / "sloginfo").unlink()
        result = self.ok("collect", "snapshot")
        self.assertIn("SLOGINFO_SAVED exit=127", result.stdout)

    def test_v1_render_is_unchanged(self):
        issued = json.loads((BASE / "reports/f1-trial-package.json").read_text())["files"]
        for name, digest in issued.items():
            self.assertEqual(hashlib.sha256((BASE / "f1-trial" / name).read_bytes()).hexdigest(), digest, name)


if __name__ == "__main__":
    unittest.main()
