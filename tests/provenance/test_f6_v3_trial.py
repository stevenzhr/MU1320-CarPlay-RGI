"""F6 v3 SD folder: the whole F6 v2 transaction suite (itself the F5 v5 suite
with F6 labels) rerun with v3 names, plus the folder contents: navhook v1.3
instead of v1.2, everything else native carried from F5 v5, scripts equal to
the F6 v2 ones apart from version names."""
import hashlib
import json
import re
import unittest

import test_f6_v2_trial as v2

BASE = v2.BASE
STAGE = BASE / "mu1320-f6-accept-v3"
V2 = BASE / "mu1320-f6-accept-v2"
V5 = BASE / "mu1320-f5-vchud-v5"


class F6V3TransactionTests(v2.F6V2TransactionTests):
    STAGE = "mu1320-f6-accept-v3"
    RUNTIME = "mu1320-rgi-f6-v3"
    NEW_JAR = "CarPlayRGI-MU1320-F6AcceptV3.jar"
    PAYLOAD_JAR = "carplay_mu1320_f6_accept_v3.jar.DISABLED"
    LISTENER = ("[CP/W][NavJava] MU1320-F6-ACCEPT-V3 LISTENER_READY bap-yield+render; "
                "NavActiveIgnore quarantined; renderer 98 via ctx 80\n")

    def test_v1_runtime_workspace_is_not_touched(self):
        others = [self.f.app / "root" / name for name in
                  ["mu1320-rgi-f5-v5", "mu1320-rgi-f6-v2"]]
        for other in others:
            other.mkdir(parents=True, mode=0o700)
            (other / "phase.txt").write_text("INSTALLATION_BASELINE_RESTORED\n")
        self.ok("install")
        self.ok("rollback", direct=True)
        for other in others:
            self.assertEqual((other / "phase.txt").read_text(), "INSTALLATION_BASELINE_RESTORED\n")

    def test_v2_listener_does_not_arm_v3(self):
        self.ok("install")
        self.propagate()
        (self.tmp / "carplay_java.log").write_text(
            "[CP/W][NavJava] MU1320-F6-ACCEPT-V2 LISTENER_READY bap-yield+render; "
            "NavActiveIgnore quarantined; renderer 98 via ctx 80\n")
        result = self.run_action("arm", mode="no_dio")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("listener marker absent", result.stdout + result.stderr)


class F6V3FolderTests(unittest.TestCase):
    def sums(self, folder):
        out = {}
        for line in (folder / "SHA256SUMS").read_text().splitlines():
            digest, name = line.split("  ", 1)
            out[name] = digest
        return out

    def test_sums_match_files(self):
        sums = self.sums(STAGE)
        self.assertEqual(sorted(sums), sorted(p.name for p in STAGE.iterdir() if p.is_file() and p.name != "SHA256SUMS"))
        for name, digest in sums.items():
            self.assertEqual(hashlib.sha256((STAGE / name).read_bytes()).hexdigest(), digest, name)

    def test_hook_is_navhook_v13_and_the_rest_is_carried(self):
        v5, v3 = self.sums(V5), self.sums(STAGE)
        report = json.loads((BASE / "reports/navhook-v13-build.json").read_text())
        self.assertEqual(v3["libcarplay_hook.so"], report["artifact"]["sha256"])
        self.assertNotEqual(v3["libcarplay_hook.so"], v5["libcarplay_hook.so"])
        self.assertEqual(report["base"]["navhook_v1_2_sha256"], v5["libcarplay_hook.so"])
        for name in ["loader_check", "mount_state", "trial_gate.c", "trial_gate.h", "dio_manager.json",
                     "ARM-TOKEN", "maneuver_render", "flag_atlas.rgba", "f4_unbuf.so"]:
            self.assertEqual(v3[name], v5[name], name)
        self.assertEqual((STAGE / "f6_mark.sh").read_bytes(), (V2 / "f6_mark.sh").read_bytes())
        build = json.loads((BASE / "reports/f6-v3-build.json").read_text())
        self.assertEqual(v3["carplay_mu1320_f6_accept_v3.jar.DISABLED"], build["jar_sha256"])

    def test_scripts_equal_v2_apart_from_versions_and_pins(self):
        norm = lambda t: re.sub(r"\b\d{6,10} \d{1,7}\b", "CRC SIZE", re.sub(r"'\d{6,10}' \] && \[ \"\$\{2:-\}\" = '\d+'", "PIN", t))
        for name in ["control.sh", "collect_f6.sh", "f6_trial.sh", "f5_sc.sh", "f5_dm.sh", "smartphone_integrator.json"]:
            old = (V2 / name).read_text()
            new = (STAGE / name).read_text()
            old = old.replace("mu1320-rgi-f6-v2", "RT").replace("MU1320-F6-ACCEPT-V2", "BID").replace(
                "carplay_mu1320_f6_accept_v2", "JAR").replace("CarPlayRGI-MU1320-F6AcceptV2", "AJAR").replace(
                "MU1320-F6-V2-VERBOSE", "VERB").replace("mu1320-f6-v2", "SHORT")
            new = new.replace("mu1320-rgi-f6-v3", "RT").replace("MU1320-F6-ACCEPT-V3", "BID").replace(
                "carplay_mu1320_f6_accept_v3", "JAR").replace("CarPlayRGI-MU1320-F6AcceptV3", "AJAR").replace(
                "MU1320-F6-V3-VERBOSE", "VERB").replace("mu1320-f6-v3", "SHORT")
            old = re.sub(r"mu1320_f6_v2_[0-9a-f]{8}", "MARK", old)
            new = re.sub(r"mu1320_f6_v3_[0-9a-f]{8}", "MARK", new)
            self.assertEqual(norm(old), norm(new), name)

    def test_readme_is_v3_session_d(self):
        text = (STAGE / "README.md").read_text()
        self.assertIn("/fs/sda0/mu1320-f6-accept-v3/f6_trial.sh install", text)
        self.assertNotIn("mu1320-f6-accept-v2/f6_trial.sh", text)
        self.assertIn("场次 D", text)
        self.assertIn("hook v1.3", text)
        self.assertNotRegex(text, r"dmdt ts\b(?!`)")


if __name__ == "__main__":
    unittest.main()
