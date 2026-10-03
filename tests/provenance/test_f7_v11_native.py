"""F7 v1.1 native: the F7 v1 hook + navhook v1.3 lane fix (patch 0004).

- The F7 gate suite reruns against f7-v1.1-src (only the persistent off path
  differs from f7-src).
- The real rgd_hook.c of the shipped tree runs the navhook v1.3 lane-cache
  scenario (F6 v2 Apple order): lanes kept, map reset clears, full cache
  evicts LRU and protects the active entry.  The reproduced F7 v1 tree must
  show the loss seen on the car.
- The artifact matches reports/f7-v1.1-native-build.json.
"""
import hashlib
import json
import subprocess
import unittest
from pathlib import Path

import test_f7_gate as gate

BASE = gate.BASE
BUILD = BASE.parent / "private-data/mu1320-rgi/f7-daily-v1.1-native"
TEST = BASE / "navhook-src/host-test"
RGD = "hook/routeguidance/rgd_hook.c"


class F7V11GateTests(gate.F7GateTests):
    SRC = BASE / "f7-v1.1-src"

    def test_source_differs_from_f7_v1_only_in_the_workspace_path(self):
        old = (BASE / "f7-src/trial_gate.c").read_text().splitlines()
        new = (self.SRC / "trial_gate.c").read_text().splitlines()
        diff = [(a, b) for a, b in zip(old, new) if a != b]
        self.assertEqual(len(old), len(new))
        self.assertEqual(diff, [('#define F7_OFF_PERSIST "/mnt/app/root/mu1320-rgi-f7-v1/off-native"',
                                 '#define F7_OFF_PERSIST "/mnt/app/root/mu1320-rgi-f7-v1.1/off-native"')])
        self.assertEqual((BASE / "f7-src/trial_gate.h").read_bytes(), (self.SRC / "trial_gate.h").read_bytes())


def lane_run(tree):
    exe = BUILD / ("lane_test_" + tree.replace("+", "_"))
    hook = BUILD / tree / "hook"
    subprocess.run(["cc", "-std=gnu99", "-w", "-I" + str(hook), str(TEST / "lane_cache_test.c"),
                    str(TEST / "stubs.c"), str(hook / "routeguidance/rgd_tlv.c"), "-o", str(exe)], check=True)
    return subprocess.run([str(exe)], capture_output=True, text=True).stdout


@unittest.skipUnless(BUILD.exists(), "private F7 v1.1 native build not present")
class F7V11LaneCacheTests(unittest.TestCase):
    def test_shipped_tree_keeps_lanes_resets_and_evicts_lru(self):
        out = lane_run("src")
        for line in ["ok   maneuver 14: lane event 3 (sent at start) still present",
                     "ok   maneuver 14: lane event 6 (sent mid-route) present",
                     "ok   after map reset: no lane event left",
                     "ok   40 events: least recently used 1..8 evicted",
                     "ok   40 events: event 0 (active while filling) protected",
                     "LANE_CACHE_TEST_PASS"]:
            self.assertIn(line, out, out)
        self.assertNotIn("FAIL", out)

    def test_0004_only_tree_passes_too(self):
        self.assertIn("LANE_CACHE_TEST_PASS", lane_run("f7-v1+0004"))

    def test_reproduced_f7_v1_tree_shows_the_car_loss(self):
        out = lane_run("repro-f7-v1")
        self.assertIn("FAIL maneuver 14: lane event 3 (sent at start) still present", out)
        self.assertIn("FAIL maneuver 14: lane event 6 (sent mid-route) present", out)
        self.assertIn("ok   after map reset: no lane event left", out)

    def test_rgd_hook_is_navhook_v13(self):
        v13 = BASE.parent / "private-data/mu1320-rgi/navhook-v13-build/src" / RGD
        self.assertEqual((BUILD / "src" / RGD).read_bytes(), v13.read_bytes())

    def test_artifact_and_scope(self):
        report = json.loads((BASE / "reports/f7-v1.1-native-build.json").read_text())
        v1 = json.loads((BASE / "reports/f7-v1-native-build.json").read_text())
        so = BUILD / "src/build/libcarplay_hook.so"
        self.assertEqual(hashlib.sha256(so.read_bytes()).hexdigest(), report["artifacts"]["libcarplay_hook.so"]["sha256"])
        self.assertTrue(report["base"]["reproduced_bit_for_bit"])
        self.assertEqual(report["base"]["f7_v1_hook_sha256"], v1["artifacts"]["libcarplay_hook.so"]["sha256"])
        self.assertEqual(report["artifacts"]["f7_spawn"]["sha256"], v1["artifacts"]["f7_spawn"]["sha256"])
        real = {k for k in report["symbol_size_changes_vs_f7_v1"] if ".part." not in k and "initialized." not in k}
        self.assertEqual(real, {"write_bus_snapshot_from_cache"})
        self.assertEqual(report["symbol_size_changes_vs_0004_only"], {})
        self.assertEqual((report["emutls"], report["init_array"], report["constructor_added"]), (0, "000004", False))
        self.assertEqual(report["missing_in_vehicle_libs"], [])
        # Shipped vs 0004-only: the only differing bytes are inside the off-switch path string.
        mid = (BUILD / "f7-v1+0004/build/libcarplay_hook.so").read_bytes()
        new = so.read_bytes()
        self.assertEqual(len(mid), len(new))
        path = b"/mnt/app/root/mu1320-rgi-f7-v1.1/off-native\0"
        start = new.find(path)
        self.assertGreater(start, 0)
        self.assertEqual(new.count(b"mu1320-rgi-f7-v1/"), 0)
        changed = [i for i in range(len(new)) if new[i] != mid[i]]
        self.assertTrue(changed and all(start <= i < start + len(path) for i in changed), changed[:5])
        diff = (BASE / "reports/f7-v1.1-native.diff").read_text()
        self.assertEqual(diff.count("\n@@ ") + diff.startswith("@@ "), 2, "0004 hunk + gate path hunk")
        self.assertIn("-    return pruned;", diff)
        self.assertIn('+#define F7_OFF_PERSIST "/mnt/app/root/mu1320-rgi-f7-v1.1/off-native"', diff)


if __name__ == "__main__":
    unittest.main()
