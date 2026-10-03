"""Host tests for f7-v1.1-src/f7_mark.sh: the F6 marker suites (v1 + v2
touchpad cases) rerun on the F7 marker with its labels mapped back
(F7MARK/F7_MARK_SAVED/f7-marks.txt), plus the F7 lines it adds: keeper log,
F7 runtime switches and the gate strike count.  Run with /bin/sh and /bin/ksh."""
import os
import re
import subprocess
import unittest

import test_f6_v2_mark as v2

BASE = v2.BASE


class MappedMarks(os.PathLike):
    """The F7 marks file, read with F6 labels so the inherited checks apply."""

    def __init__(self, path):
        self.path = path

    def __fspath__(self):
        return str(self.path)

    def exists(self):
        return self.path.exists()

    def stat(self):
        return self.path.stat()

    def read_text(self):
        return self.path.read_text().replace("F7MARK", "F6MARK")


class MarkF7Tests(v2.MarkV2Tests):
    SCRIPT = BASE / "f7-v1.1-src/f7_mark.sh"
    STAGE = "mu1320-f7-daily-v1.1"

    def setUp(self):
        super().setUp()
        self.real_marks = self.stage / "out/f7-marks.txt"
        self.marks = MappedMarks(self.real_marks)

    def run_mark(self, *args, **kw):
        r = super().run_mark(*args, **kw)
        return subprocess.CompletedProcess(r.args, r.returncode, r.stdout.replace("F7_MARK_SAVED", "F6_MARK_SAVED"),
                                           r.stderr)

    def test_differs_from_v1_only_in_touchpad_paths(self):
        pass  # replaced by test_differs_from_f6_v3_only_in_labels_and_f7_lines

    def test_differs_from_f6_v3_only_in_labels_and_f7_lines(self):
        old = (BASE / "f6-v3-src/f6_mark.sh").read_text()
        new = self.SCRIPT.read_text()
        self.assertEqual(old, (BASE / "mu1320-f6-accept-v3/f6_mark.sh").read_text(), "F6 v3 car marker")
        changed = [l for l in new.splitlines() if l not in old.splitlines() and not l.startswith("#")]
        for line in changed:
            self.assertRegex(line, r"f7|F7|strikes", line)
        self.assertNotIn("navhook", new)
        self.assertNotRegex("\n".join(l for l in new.splitlines() if not l.startswith("#")), r"F6|f6_mark|f6-marks")

    def test_f7_lines(self):
        self.logs()
        (self.ram / "mu1320-f7-keeper.log").write_text("KEEP BEGIN why=hello\nKEEP READY rc=0 started=1 ctx80=now\n")
        (self.ram / "mu1320-f7-render-hold").write_text("")
        (self.ram / "mu1320-f7-gate.strikes").write_text("2\n")
        for shell in v2.v1.SHELLS:
            with self.subTest(shell=shell):
                r = super().run_mark("P3", "replug", shell=shell)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn("F7_MARK_SAVED step=P3", r.stdout)
        text = self.real_marks.read_text()
        self.assertIn("F7MARK step=P3 note=replug\n", text)
        self.assertIn("LAST mu1320-f7-keeper.log: KEEP READY rc=0 started=1 ctx80=now", text)
        self.assertIn("SWITCH mu1320-f7-render-hold: PRESENT", text)
        self.assertIn("SWITCH mu1320-f7-native-off: ABSENT", text)
        self.assertIn("GATE_STRIKES: 2", text)
        self.assertTrue(text.rstrip().endswith("F7MARK_END"))
        self.assertFalse((self.stage / "out/f6-marks.txt").exists())

    def test_f7_lines_absent(self):
        self.assertEqual(self.run_mark("P1").returncode, 0)
        text = self.real_marks.read_text()
        self.assertIn("LAST mu1320-f7-keeper.log: ABSENT", text)
        self.assertIn("GATE_STRIKES: ABSENT", text)
        self.assertNotIn("navhook", text)


if __name__ == "__main__":
    unittest.main()
