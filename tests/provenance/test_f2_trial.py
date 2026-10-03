"""Host transaction tests for the F2 shadow-state SD folder.

The F2 scripts are derived from the vehicle-run navjava scripts, so every
navjava transaction test is rerun against the F2 folder, plus F2 evidence.
"""
import re
import unittest

import test_navjava_trial as navjava

BASE = navjava.BASE


class F2TrialTests(navjava.NavjavaTrialTests):
    STAGE = "mu1320-f2-shadow-v1"
    RUNTIME = "mu1320-rgi-f2-v1"
    NEW_JAR = "CarPlayRGI-MU1320-F2ShadowV1.jar"
    PAYLOAD_JAR = "carplay_mu1320_f2_shadow_v1.jar.DISABLED"
    WRAPPER = "f2_trial.sh"
    COLLECTOR = "collect_f2.sh"
    ENV_MARKER = None  # filled from the rendered collector below
    LISTENER = ("[CP/W][NavJava] MU1320-F2-SHADOW-V1 LISTENER_READY shadow-state; "
                "NavActiveIgnore retained; no BAP/renderer\n")

    @classmethod
    def setUpClass(cls):
        collector = (BASE / cls.STAGE / cls.COLLECTOR).read_text()
        cls.ENV_MARKER = re.search(r"^MARKER='([^']+)'", collector, re.M).group(1)

    def write_java_evidence(self):
        (self.tmp / "mu1320-f2-state.log").write_text(
            "F2 MU1320-F2-SHADOW-V1 START mode=SHADOW publishes=none\n"
            "F2 i=1 t=0 ev=SESSION rs=-1 act=0 mc=-1 ord=- sym=INACTIVE\n"
            "F2 i=2 t=40 ev=ACTIVATE+PRIMARY rs=6 act=1 mc=11 ord=0,1 sym=MANEUVER:13/192\n"
            "F2 i=3 t=90 ev=UPDATE rs=6 act=1 mc=11 ord=0,1 sym=MANEUVER:13/192\n"
            "F2 i=4 t=120 ev=ROUTE_END+DEACTIVATE rs=0 act=0 mc=0 ord=- sym=INACTIVE\n")
        (self.tmp / "mu1320-f2-frames.cap").write_text(
            "#F2CAP v1 MU1320-F2-SHADOW-V1\n@1 0 E SESSION\n@2 40 F 1 CAPTURE_BODY_NOT_PRINTED\n")

    def assert_java_evidence(self, stdout):
        self.assertIn("F2_COUNT[F2 i=]=4", stdout)
        self.assertIn("F2_COUNT[ev=REJECT]=0", stdout)
        self.assertIn("F2_COUNT[ROUTE_END]=1", stdout)
        self.assertIn("F2_COUNT[sym=MANEUVER]=2", stdout)
        self.assertIn("ev=ROUTE_END+DEACTIVATE", stdout)
        self.assertNotIn("ev=UPDATE rs=6", stdout, "UPDATE lines are copied, not printed")
        self.assertNotIn("CAPTURE_BODY_NOT_PRINTED", stdout)
        out = self.f.sd / "out"
        armed = [p for p in out.iterdir() if p.name.startswith("armed-")]
        self.assertEqual(len(armed), 1)
        self.assertIn("CAPTURE_BODY_NOT_PRINTED", (armed[0] / "mu1320-f2-frames.cap").read_text())
        self.assertIn("ev=UPDATE rs=6", (armed[0] / "mu1320-f2-state.log").read_text())

    def test_navjava_listener_marker_does_not_arm_f2(self):
        self.ok("install")
        self.propagate()
        (self.tmp / "carplay_java.log").write_text(
            "[CP/W][NavJava] MU1320-NAVJAVA-INGRESS-V1 LISTENER_READY receive-only\n")
        result = self.run_action("arm", mode="no_dio")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("listener marker absent", result.stdout + result.stderr)
        self.assertFalse((self.tmp / "mu1320-navhook-v1.arm").exists())

    def test_leftover_navjava_archive_stops_install_before_writes(self):
        (self.jars / "CarPlayRGI-MU1320-IngressV1.jar").write_text("left over")
        result = self.run_action("install")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown HMI archive", result.stdout + result.stderr)
        self.assertFalse(self.root.exists())
        self.assertFalse(self.new.exists())

    def test_collect_without_f2_files_reports_missing(self):
        result = self.ok("collect", "snapshot")
        self.assertIn("MISSING: ", result.stdout)
        self.assertIn("F2_COUNT[F2 i=]=0", result.stdout)

    def test_scripts_keep_vehicle_native_names_and_drop_navjava_names(self):
        for name in ["control.sh", "collect_f2.sh", "f2_trial.sh", "smartphone_integrator.json"]:
            text = (BASE / self.STAGE / name).read_text()
            self.assertNotRegex(text, r"(?i)navjava|ingress", name)
        control = (BASE / self.STAGE / "control.sh").read_text()
        self.assertIn("ARM=/tmp/mu1320-navhook-v1.arm", control)
        self.assertIn("printf 'MU1320-NAVHOOK-ONE-SHOT-V1\\n'", control)
        self.assertIn("ROOT=/mnt/app/root/mu1320-rgi-f2-v1", control)
        collector = (BASE / self.STAGE / "collect_f2.sh").read_text()
        self.assertIn("/tmp/mu1320-navhook-v1-gate-", collector)
        for native in ["libcarplay_hook.so", "loader_check", "mount_state", "trial_gate.c", "ARM-TOKEN",
                       "dio_manager.json"]:
            self.assertEqual((BASE / self.STAGE / native).read_bytes(),
                             (BASE / "navjava-trial" / native).read_bytes(), native)


if __name__ == "__main__":
    unittest.main()
