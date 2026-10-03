"""navhook v1.3 (BACKLOG B8): host build of the real rgd_hook.c with bus stubs.

The same lane-cache scenario (F6 v2 Apple order) is run against the untouched
v1.2 tree and the v1.3 tree: v1.2 must lose the lane events the car lost,
v1.3 must keep them, and both must still clear on map reset and evict LRU.
Also pins the v1.3 artifact to reports/navhook-v13-build.json.
"""
import hashlib
import json
import subprocess
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
BUILD = BASE.parent / "private-data/mu1320-rgi/navhook-v13-build"
TEST = BASE / "navhook-src/host-test"


def run(tree):
    exe = BUILD / ("lane_test_" + tree)
    hook = BUILD / tree / "hook"
    subprocess.run(["cc", "-std=gnu99", "-w", "-I" + str(hook), str(TEST / "lane_cache_test.c"),
                    str(TEST / "stubs.c"), str(hook / "routeguidance/rgd_tlv.c"), "-o", str(exe)], check=True)
    return subprocess.run([str(exe)], capture_output=True, text=True).stdout


@unittest.skipUnless(BUILD.exists(), "private navhook v1.3 build not present")
class NavhookV13Tests(unittest.TestCase):
    def test_v13_keeps_every_lane_event(self):
        out = run("src")
        self.assertIn("LANE_CACHE_TEST_PASS", out, out)
        self.assertNotIn("FAIL", out)

    def test_v12_reproduces_the_car_loss(self):
        out = run("repro-v1.2")
        self.assertIn("FAIL maneuver 14: lane event 3 (sent at start) still present", out)
        self.assertIn("FAIL maneuver 14: lane event 6 (sent mid-route) present", out)
        self.assertIn("ok   route start: lane event 0 active and present", out)
        self.assertIn("ok   after map reset: no lane event left", out)

    def test_artifact_and_scope(self):
        report = json.loads((BASE / "reports/navhook-v13-build.json").read_text())
        so = BUILD / "src/build/libcarplay_hook.so"
        self.assertEqual(hashlib.sha256(so.read_bytes()).hexdigest(), report["artifact"]["sha256"])
        self.assertTrue(report["base"]["reproduced_bit_for_bit"])
        real = {k for k in report["symbol_size_changes"] if ".part." not in k and "initialized." not in k}
        self.assertEqual(real, {"write_bus_snapshot_from_cache"})
        diff = (BASE / "reports/navhook-v13-rgd.diff").read_text()
        self.assertEqual(diff.count("\n@@ "), 1, "one hunk only")
        self.assertIn("\n static bool rgd_prune_stale_lane_cache(void) {\n", diff)
        added = [l[1:] for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++")]
        self.assertEqual([l for l in added if not l.startswith((" *", "/*"))], ["    return false;"])
        self.assertIn("-    return pruned;", diff)


if __name__ == "__main__":
    unittest.main()
