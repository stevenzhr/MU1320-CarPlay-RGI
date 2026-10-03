"""Host control-flow tests for the F7 daily gate (f7-src/trial_gate.c):
always active in dio_manager, off switches, crash guard, generation record
and the live-DIO guard used by the bus connector."""
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
HARNESS = r'''#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <sys/wait.h>
#include "trial_gate.h"
int main(int argc, char **argv) {
 int active, status; pid_t child;
 if (argc > 1 && strcmp(argv[1], "now") == 0) {
  struct timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts);
  printf("%ld\n", (long)ts.tv_sec * 1000L + (long)(ts.tv_nsec / 1000000L)); return 0;
 }
 printf("CURRENT_BEFORE=%d\n", trial_gate_is_current());
 active = trial_gate_active();
 printf("ACTIVE=%d AGAIN=%d WAS=%d CURRENT=%d PID=%d\n", active, trial_gate_active(),
        trial_gate_was_active(), trial_gate_is_current(), (int)getpid());
 fflush(stdout);
 child = fork(); if (child < 0) return 3;
 if (child == 0) _exit(trial_gate_active() ? 9 : 0);
 if (waitpid(child, &status, 0) != child || !WIFEXITED(status) || WEXITSTATUS(status) != 0) return 4;
 return 0;
}
'''


@unittest.skipUnless(shutil.which("cc"), "host C compiler required")
class F7GateTests(unittest.TestCase):
    SRC = BASE / "f7-src"  # F7 v1.1 reruns the class against f7-v1.1-src

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        cls.dir = root / "tmp"
        cls.dir.mkdir()
        cls.persist = root / "off-native"
        source = root / "harness.c"
        source.write_text(HARNESS)
        cls.bins = {}
        for dio in (1, 0):
            out = root / ("gate%d" % dio)
            defs = {"F7_OFF_PERSIST": str(cls.persist), "F7_OFF_RUNTIME": str(cls.dir / "native-off"),
                    "F7_LAST": str(cls.dir / "gate.last"), "F7_STRIKES": str(cls.dir / "gate.strikes"),
                    "F7_RECEIPT_PREFIX": str(cls.dir / "gate-")}
            cmd = ["cc", "-std=gnu99", "-Wall", "-Wextra", "-Werror", "-pthread", "-DTRIAL_ASSUME_DIO=%d" % dio]
            cmd += ["-D%s=%s" % (k, json.dumps(v)) for k, v in defs.items()]
            cmd += ["-I" + str(cls.SRC), str(source), str(cls.SRC / "trial_gate.c"), "-o", str(out)]
            subprocess.run(cmd, check=True, capture_output=True)
            cls.bins[dio] = out

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        for p in self.dir.iterdir():
            p.unlink()
        if self.persist.exists():
            self.persist.unlink()

    def gate(self, dio=1):
        result = subprocess.run([str(self.bins[dio])], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        pid = result.stdout.split("PID=")[1].split()[0]
        receipt = self.dir / ("gate-" + pid)
        return result.stdout, receipt.read_text() if receipt.exists() else None, int(pid)

    def now(self):
        return int(subprocess.check_output([str(self.bins[1]), "now"], text=True))

    def dead_pid(self):
        p = subprocess.Popen(["true"])
        p.wait()
        return p.pid

    def last(self, pid, start):
        (self.dir / "gate.last").write_text("%d %d\n" % (pid, start))

    def strikes(self):
        return int((self.dir / "gate.strikes").read_text())

    def test_dio_is_active_without_any_token_and_fork_is_passive(self):
        out, receipt, pid = self.gate()
        self.assertIn("ACTIVE=1 AGAIN=1 WAS=1 CURRENT=1", out)
        self.assertIn("mode=ACTIVE reason=ON", receipt)
        self.assertEqual((self.dir / "gate.last").read_text().split()[0], str(pid))
        self.assertEqual(self.strikes(), 0)

    def test_replacement_dio_is_active_too(self):
        first = self.gate()[2]
        out, receipt, pid = self.gate()
        self.assertIn("ACTIVE=1", out)
        self.assertIn("prev=%d prev_alive=0" % first, receipt)
        self.assertEqual((self.dir / "gate.last").read_text().split()[0], str(pid))

    def test_non_dio_process_is_passive_and_writes_nothing(self):
        out, receipt, _ = self.gate(dio=0)
        self.assertIn("ACTIVE=0", out)
        self.assertIsNone(receipt)
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_persistent_and_runtime_off_switches(self):
        self.persist.write_text("")
        out, receipt, _ = self.gate()
        self.assertIn("ACTIVE=0 AGAIN=0 WAS=0", out)
        self.assertIn("mode=PASSIVE reason=OFF_PERSIST", receipt)
        self.assertFalse((self.dir / "gate.last").exists())
        self.persist.unlink()
        (self.dir / "native-off").write_text("off\n")
        out, receipt, _ = self.gate()
        self.assertIn("ACTIVE=0", out)
        self.assertIn("mode=PASSIVE reason=OFF_RUNTIME", receipt)

    def test_three_short_dead_generations_trip_the_crash_guard_for_the_boot(self):
        for expected in (1, 2):
            self.last(self.dead_pid(), self.now() - 1000)
            out, receipt, _ = self.gate()
            self.assertIn("ACTIVE=1", out)
            self.assertEqual(self.strikes(), expected)
        self.last(self.dead_pid(), self.now() - 1000)
        out, receipt, _ = self.gate()
        self.assertIn("ACTIVE=0", out)
        self.assertIn("mode=PASSIVE reason=CRASH_GUARD", receipt)
        self.assertEqual(self.strikes(), 3)
        # Sticky: even a long-lived previous generation does not re-enable it.
        self.last(self.dead_pid(), self.now() - 600000)
        out, receipt, _ = self.gate()
        self.assertIn("ACTIVE=0", out)
        self.assertIn("reason=CRASH_GUARD", receipt)
        # Removing the strikes file re-enables the next DIO.
        (self.dir / "gate.strikes").unlink()
        out, _, _ = self.gate()
        self.assertIn("ACTIVE=1", out)

    def test_long_lived_generation_resets_strikes(self):
        (self.dir / "gate.strikes").write_text("2\n")
        self.last(self.dead_pid(), self.now() - 20000)
        out, _, _ = self.gate()
        self.assertIn("ACTIVE=1", out)
        self.assertEqual(self.strikes(), 0)

    def test_live_previous_generation_is_superseded_not_counted(self):
        (self.dir / "gate.strikes").write_text("2\n")
        self.last(os.getpid(), self.now() - 100)
        out, receipt, pid = self.gate()
        self.assertIn("ACTIVE=1", out)
        self.assertIn("reason=PREV_ALIVE", receipt)
        self.assertIn("prev=%d prev_alive=1" % os.getpid(), receipt)
        self.assertEqual(self.strikes(), 0)
        self.assertEqual((self.dir / "gate.last").read_text().split()[0], str(pid))

    def test_is_current_follows_the_generation_record(self):
        out, _, _ = self.gate()
        self.assertIn("CURRENT_BEFORE=1", out)  # no record yet: fail-open
        self.last(os.getpid(), self.now())
        (self.dir / "native-off").write_text("")
        out, _, _ = self.gate()
        self.assertIn("CURRENT_BEFORE=0", out)  # another generation is newest
        self.assertIn("ACTIVE=0", out)
        self.assertIn("CURRENT=0", out)

    def test_garbage_records_fail_safe(self):
        (self.dir / "gate.last").write_text("garbage\n")
        (self.dir / "gate.strikes").write_text("x\n")
        out, receipt, _ = self.gate()
        self.assertIn("ACTIVE=1", out)
        self.assertIn("strikes=0", receipt)


if __name__ == "__main__":
    unittest.main()
