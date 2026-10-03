"""F7 v2 native (B11): the gate records must be written without rename().

On the car /tmp is /dev/shmem, which has no rename(); F7 v1.1's write_small()
(temp + rename) therefore never produced gate.last / gate.strikes and the
crash guard never fired (car session P4).  Here rename() is replaced by a
stub that always fails: v1.1 reproduces the car (no records, every DIO
active), v2 keeps the records and trips the crash guard on the fourth quick
generation, exactly the P4 expectation.  The full v1 gate suite is rerun on
the v2 source, and the v2 hook build report is checked.
"""
import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import test_f7_gate

BASE = Path(__file__).resolve().parents[1]
NO_RENAME = r'''#include <errno.h>
int f7_no_rename(const char *from, const char *to) { (void)from; (void)to; errno = ENOSYS; return -1; }
'''


class F7V2GateTests(test_f7_gate.F7GateTests):
    SRC = BASE / "f7-v2-src"


@unittest.skipUnless(shutil.which("cc"), "host C compiler required")
class NoRenameTests(unittest.TestCase):
    """Both gate versions against a filesystem without rename()."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        cls.dir = root / "tmp"
        cls.dir.mkdir()
        (root / "harness.c").write_text(test_f7_gate.HARNESS)
        (root / "no_rename.c").write_text(NO_RENAME)
        cls.bins = {}
        for tag in ("f7-v1.1-src", "f7-v2-src"):
            out = root / tag
            defs = {"F7_OFF_PERSIST": str(root / "off-native"), "F7_OFF_RUNTIME": str(cls.dir / "native-off"),
                    "F7_LAST": str(cls.dir / "gate.last"), "F7_STRIKES": str(cls.dir / "gate.strikes"),
                    "F7_RECEIPT_PREFIX": str(cls.dir / "gate-")}
            cmd = ["cc", "-std=gnu99", "-Wall", "-Wextra", "-Werror", "-pthread", "-DTRIAL_ASSUME_DIO=1",
                   "-Drename=f7_no_rename"]
            cmd += ["-D%s=%s" % (k, json.dumps(v)) for k, v in defs.items()]
            cmd += ["-I" + str(BASE / tag), str(root / "harness.c"), str(BASE / tag / "trial_gate.c"),
                    str(root / "no_rename.c"), "-o", str(out)]
            subprocess.run(cmd, check=True, capture_output=True)
            cls.bins[tag] = out

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        for p in self.dir.iterdir():
            p.unlink()

    def generations(self, tag, n):
        """n quick DIO generations, each exiting at once (a hook fault in a restart loop)."""
        receipts = []
        for _ in range(n):
            r = subprocess.run([str(self.bins[tag])], capture_output=True, text=True, timeout=5)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            pid = r.stdout.split("PID=")[1].split()[0]
            receipts.append((r.stdout, (self.dir / ("gate-" + pid)).read_text()))
        return receipts

    def test_v11_reproduces_the_car_no_records_no_guard(self):
        runs = self.generations("f7-v1.1-src", 4)
        for out, receipt in runs:
            self.assertIn("ACTIVE=1", out)
            self.assertIn("strikes=0 prev=0", receipt)  # what the car's four P4 receipts showed
        self.assertFalse((self.dir / "gate.last").exists())
        self.assertFalse((self.dir / "gate.strikes").exists())
        self.assertEqual(sorted(p.name for p in self.dir.iterdir() if not p.name.startswith("gate-")), [])

    def test_v2_writes_records_and_the_fourth_quick_generation_is_passive(self):
        runs = self.generations("f7-v2-src", 4)
        for i, (out, receipt) in enumerate(runs[:3]):
            self.assertIn("ACTIVE=1", out)
            self.assertIn("strikes=%d " % i, receipt)
        self.assertIn("ACTIVE=0", runs[3][0])
        self.assertIn("mode=PASSIVE reason=CRASH_GUARD", runs[3][1])
        self.assertEqual((self.dir / "gate.strikes").read_text(), "3\n")
        # the passive generation leaves LAST on the last active one
        last_pid = runs[2][0].split("PID=")[1].split()[0]
        self.assertEqual((self.dir / "gate.last").read_text().split()[0], last_pid)
        # no temporaries left behind
        self.assertEqual(sorted(p.name for p in self.dir.iterdir() if not p.name.startswith("gate-")),
                         ["gate.last", "gate.strikes"])
        # rm strikes re-enables (the documented reset)
        (self.dir / "gate.strikes").unlink()
        self.assertIn("ACTIVE=1", self.generations("f7-v2-src", 1)[0][0])

    def test_v2_shorter_record_overwrites_a_longer_one(self):
        # a long-dead generation (started at 1 ms) in a record longer than the new one
        (self.dir / "gate.last").write_text("1234567890 000000000000000001\n")
        (self.dir / "gate.strikes").write_text("0000000000\n")
        out, receipt = self.generations("f7-v2-src", 1)[0]
        self.assertIn("ACTIVE=1", out)
        pid = out.split("PID=")[1].split()[0]
        text = (self.dir / "gate.last").read_text()
        self.assertEqual(text.split()[0], pid)
        self.assertEqual(len(text.split()), 2)
        self.assertEqual((self.dir / "gate.strikes").read_text(), "0\n")


class F7V2NativeReportTests(unittest.TestCase):
    def test_source_differs_from_v11_only_in_the_gate_writer_and_workspace(self):
        old = (BASE / "f7-v1.1-src/trial_gate.c").read_text()
        new = (BASE / "f7-v2-src/trial_gate.c").read_text()
        self.assertEqual((BASE / "f7-v1.1-src/trial_gate.h").read_bytes(), (BASE / "f7-v2-src/trial_gate.h").read_bytes())
        self.assertIn('"/mnt/app/root/mu1320-rgi-f7-v2/off-native"', new)
        code = new.split("*/", 1)[1]
        self.assertNotIn("rename(", code)
        self.assertIn("O_WRONLY | O_CREAT | O_TRUNC", code)
        # outside write_small and the header comment nothing changed
        def strip(text):
            head, body = text.split("*/", 1)
            start = body.index('/* Write "text" to path')
            end = body.index("static int process_alive")
            return body[:start] + body[end:]
        self.assertEqual(strip(old).replace("mu1320-rgi-f7-v1.1", "mu1320-rgi-f7-v2"), strip(new))

    def test_build_report(self):
        report = json.loads((BASE / "reports/f7-v2-native-build.json").read_text())
        old = json.loads((BASE / "reports/f7-v1.1-native-build.json").read_text())
        self.assertTrue(report["base"]["reproduced_bit_for_bit"])
        self.assertEqual(report["base"]["f7_v1_1_hook_sha256"], old["artifacts"]["libcarplay_hook.so"]["sha256"])
        self.assertEqual(report["emutls"], 0)
        self.assertEqual(report["init_array"], "000004")
        self.assertEqual(report["missing_in_vehicle_libs"], [])
        self.assertEqual(set(report["symbol_size_changes_vs_f7_v1_1"]), {"write_small"})
        self.assertLessEqual(set(report["dynamic_imports"]["libcarplay_hook.so"]["undefined"]),
                             set(old["dynamic_imports"]["libcarplay_hook.so"]["undefined"]))
        self.assertEqual(report["sources"]["trial_gate.c"],
                         hashlib.sha256((BASE / "f7-v2-src/trial_gate.c").read_bytes()).hexdigest())
        stage = BASE / "mu1320-f7-daily-v2/libcarplay_hook.so"
        if stage.exists():
            self.assertEqual(hashlib.sha256(stage.read_bytes()).hexdigest(),
                             report["artifacts"]["libcarplay_hook.so"]["sha256"])


if __name__ == "__main__":
    unittest.main()
