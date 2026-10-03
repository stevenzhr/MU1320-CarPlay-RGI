"""Host tests for f6-v2-src/f6_mark.sh: the F6 v1 marker suite rerun on the v2
marker, plus the touchpad log line and switch it adds."""
import unittest

import test_f6_mark as v1

BASE = v1.BASE


class MarkV2Tests(v1.MarkTests):
    SCRIPT = BASE / "f6-v2-src/f6_mark.sh"
    STAGE = "mu1320-f6-accept-v2"

    def test_touchpad_line_and_switch(self):
        self.logs()
        (self.ram / "mu1320-f6-touchpad.log").write_text("T t=1 READY build=MU1320-F6-ACCEPT-V2\nT t=9 DPAD key=6\n")
        (self.ram / "mu1320-f6-touchpad-off").write_text("")
        r = self.run_mark("T3", "right")
        self.assertEqual(r.returncode, 0, r.stderr)
        text = self.marks.read_text()
        self.assertIn("LAST mu1320-f6-touchpad.log: T t=9 DPAD key=6", text)
        self.assertIn("SWITCH mu1320-f6-touchpad-off: PRESENT", text)

    def test_touchpad_log_absent(self):
        self.assertEqual(self.run_mark("T1").returncode, 0)
        text = self.marks.read_text()
        self.assertIn("LAST mu1320-f6-touchpad.log: ABSENT", text)
        self.assertIn("SWITCH mu1320-f6-touchpad-off: ABSENT", text)

    def test_differs_from_v1_only_in_touchpad_paths(self):
        old = (BASE / "f6-src/f6_mark.sh").read_text().splitlines()
        new = self.SCRIPT.read_text().splitlines()
        changed = [l for l in new if l not in old]
        self.assertTrue(all("touchpad" in l or l.startswith("#") for l in changed), changed)


if __name__ == "__main__":
    unittest.main()
