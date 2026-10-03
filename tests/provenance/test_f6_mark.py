"""Host tests for f6-src/f6_mark.sh (F6 step marker, read-only on the car).

The real script runs with vehicle paths rewritten into a temp tree, fake
id/uname/mount/sync, and a fake mount_state whose cksum replaces the pinned
one.  Run with /bin/sh and, when present, /bin/ksh (the car shell family).
"""
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
SCRIPT = BASE / "f6-src/f6_mark.sh"
SHELLS = [s for s in (os.environ.get("RC_SHELL", "/bin/sh"), "/bin/ksh") if Path(s).exists()]


def cksum(path):
    return subprocess.check_output(["cksum", str(path)], text=True).split()[:2]


class MarkTests(unittest.TestCase):
    SCRIPT = SCRIPT
    STAGE = "mu1320-f6-accept-v1"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.sd = self.tmp / "sd"
        self.stage = self.sd / self.STAGE
        self.stage.mkdir(parents=True)
        self.ram = self.tmp / "ram"
        self.ram.mkdir()
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.flag = self.tmp / "sdflag"
        self.flag.write_text("ro\n")
        helper = self.stage / "mount_state"
        helper.write_text('#!/bin/sh\ncat "$SD_FLAG"\n')
        helper.chmod(0o755)
        fakes = {
            "id": 'echo "${FAKE_UID:-0}"',
            "uname": 'echo "${FAKE_UNAME:-QNX mmx 6.5.0 2010/07/09-14:44:03EDT armle}"',
            "mount": 'echo "$*" >> "$MOUNT_CALLS"\n'
                     '[ "${FAIL:-}" != "mount $1" ] || exit 7\n'
                     'case "$1" in -uw) echo rw > "$SD_FLAG" ;; -ur) echo ro > "$SD_FLAG" ;; esac',
            "sync": ":",
            "date": 'case "${1:-}" in +%s) echo "${FAKE_EPOCH:-1790000000}" ;; *) echo "Sat Sep 26 10:00:00 UTC 2026" ;; esac',
        }
        for name, body in fakes.items():
            p = self.bin / name
            p.write_text("#!/bin/sh\n" + body + "\n")
            p.chmod(0o755)
        text = self.SCRIPT.read_text()
        text = re.sub(r"^PATH=.*$", "PATH=%s:/usr/bin:/bin" % self.bin, text, flags=re.M)
        text = text.replace("/fs/sda0", str(self.sd.resolve()))
        text = text.replace("/tmp/", str(self.ram) + "/")
        text = text.replace("'2952412687' ] && [ \"${2:-}\" = '7302'",
                            "'%s' ] && [ \"${2:-}\" = '%s'" % tuple(cksum(helper)))
        self.script = self.stage / "f6_mark.sh"
        self.script.write_text(text)
        self.env = dict(os.environ, SD_FLAG=str(self.flag), MOUNT_CALLS=str(self.tmp / "mounts"))
        self.marks = self.stage / "out/f6-marks.txt"

    def run_mark(self, *args, shell=None, **env):
        e = dict(self.env, **env)
        return subprocess.run([shell or SHELLS[0], str(self.script)] + list(args),
                              capture_output=True, text=True, env=e, timeout=20)

    def logs(self):
        (self.ram / "mu1320-f5-state.log").write_text(
            "F2 i=1 t=5 ev=SESSION rs=-1\nF2 i=42 t=91234 ev=UPDATE rs=1 act=1\n")
        (self.ram / "mu1320-f5-bap.log").write_text("B i=42 t=91240 CALL DIST_TURN 300 bar=-")  # no newline
        (self.ram / "mu1320-f5-ctx-mode").write_text("native\n")
        (self.ram / "mu1320-f5-bap-off").write_text("off\n")

    def test_marks_are_appended_and_sd_goes_back_read_only(self):
        self.logs()
        for shell in SHELLS:
            with self.subTest(shell=shell):
                r = self.run_mark("A2", "apple", "start", shell=shell)
                self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
                self.assertIn("F6_MARK_SAVED step=A2", r.stdout)
                self.assertEqual(self.flag.read_text().strip(), "ro")
        text = self.marks.read_text()
        self.assertEqual(text.count("F6MARK step=A2 note=apple start\n"), len(SHELLS))
        self.assertEqual(text.count("F6MARK_END\n"), len(SHELLS))
        self.assertIn("EPOCH: 1790000000", text)
        self.assertIn("LAST mu1320-f5-state.log: F2 i=42 t=91234 ev=UPDATE rs=1 act=1", text)
        self.assertIn("LAST mu1320-f5-bap.log: B i=42 t=91240 CALL DIST_TURN 300 bar=-", text)
        self.assertIn("LAST mu1320-f5-render.log: ABSENT", text)
        self.assertIn("CTX_MODE_FILE: native", text)
        self.assertIn("SWITCH mu1320-f5-bap-off: PRESENT", text)
        self.assertIn("SWITCH mu1320-f5-render-off: ABSENT", text)
        self.assertEqual(oct(self.marks.stat().st_mode & 0o777), "0o600")

    def test_block_parses_with_the_matrix_tool(self):
        import sys
        sys.path.insert(0, str(BASE / "scripts"))
        import f6_matrix
        self.logs()
        self.assertEqual(self.run_mark("B7", "reroute").returncode, 0)
        marks = f6_matrix.parse_marks(self.marks)
        self.assertEqual(marks[0]["step"], "B7")
        self.assertEqual(marks[0]["state_i"], 42)
        self.assertEqual(marks[0]["state_t"], 91234)

    def test_rw_sd_is_left_rw_and_not_remounted(self):
        self.flag.write_text("rw\n")
        r = self.run_mark("A1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.flag.read_text().strip(), "rw")
        self.assertFalse((self.tmp / "mounts").exists())

    def test_note_is_filtered(self):
        r = self.run_mark("A3", "x;$(rm", "-rf", "/)`y'\"")
        self.assertEqual(r.returncode, 0, r.stderr)
        line = self.marks.read_text().splitlines()[0]
        self.assertEqual(line, "F6MARK step=A3 note=x___rm -rf /__y__")

    def test_note_filter_without_tr_ranges(self):
        # The car's tr treats 'A-Z' as three literal characters (F6 session A:
        # "change to m" became "__a___ __ _").  Fake such a tr.
        fake = self.bin / "tr"
        fake.write_text("#!/usr/bin/env python3\nimport sys\nkeep = sys.argv[2]\nrepl = sys.argv[3]\n"
                        "data = sys.stdin.read()\nsys.stdout.write(''.join(c if c in keep else repl for c in data))\n")
        fake.chmod(0o755)
        r = self.run_mark("A5", "change to m", "Km/h=5")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.marks.read_text().splitlines()[0], "F6MARK step=A5 note=change to m Km/h=5")

    def test_bad_steps_write_nothing(self):
        for args in ([], ["a b"], ["../x"], ["x" * 17], ["A;1"]):
            with self.subTest(args=args):
                r = self.run_mark(*args)
                self.assertEqual(r.returncode, 2)
        self.assertFalse(self.marks.exists())
        self.assertEqual(self.flag.read_text().strip(), "ro")

    def test_refuses_non_root_wrong_platform_and_tampered_helper(self):
        self.assertEqual(self.run_mark("A1", FAKE_UID="1000").returncode, 1)
        self.assertEqual(self.run_mark("A1", FAKE_UNAME="Darwin host 25.6.0 arm64").returncode, 1)
        with (self.stage / "mount_state").open("a") as s:
            s.write("# changed\n")
        r = self.run_mark("A1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("mount helper checksum", r.stderr)
        self.assertFalse(self.marks.exists())
        self.assertEqual(self.flag.read_text().strip(), "ro")

    def test_failed_restore_is_reported(self):
        r = self.run_mark("A1", FAIL="mount -ur")
        self.assertEqual(r.returncode, 1)
        self.assertIn("SD state not restored", r.stderr)
        self.assertNotIn("F6_MARK_SAVED", r.stdout)

    def test_failed_remount_leaves_sd_alone(self):
        r = self.run_mark("A1", FAIL="mount -uw")
        self.assertEqual(r.returncode, 1)
        self.assertIn("SD remount rw", r.stderr)
        self.assertEqual(self.flag.read_text().strip(), "ro")

    def test_date_without_epoch_support(self):
        self.assertEqual(self.run_mark("A1", FAKE_EPOCH="%s").returncode, 0)
        self.assertIn("EPOCH: NA", self.marks.read_text())

    def test_static_rules(self):
        text = self.SCRIPT.read_text()
        self.assertNotRegex(text, r"&&\s*fail", "vehicle ksh exits under set -e on `cmd && fail`")
        self.assertNotIn("carplay_hook.log", text, "the hook log holds road names")
        self.assertNotIn("dmdt", text)
        self.assertNotIn("mount -u /", text)
        self.assertNotRegex(text, r"tr -c '[^']*[A-Za-z0-9]-[A-Za-z0-9]", "no tr ranges on the car")


if __name__ == "__main__":
    unittest.main()
