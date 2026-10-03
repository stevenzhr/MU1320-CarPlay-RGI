"""Host transaction tests for the F3 BAP SD folder.

F3 scripts are the navjava scripts (reused by F2) plus the F1 v2
NavActiveIgnore quarantine, so every navjava transaction test is rerun
against the F3 folder; tests whose expectations change with the quarantine
are overridden, and quarantine-specific cases are added.
"""
import re
import unittest

import test_navjava_trial as navjava

BASE = navjava.BASE


class F3TrialTests(navjava.NavjavaTrialTests):
    STAGE = "mu1320-f3-bap-v1"
    RUNTIME = "mu1320-rgi-f3-v1"
    NEW_JAR = "CarPlayRGI-MU1320-F3BapV1.jar"
    PAYLOAD_JAR = "carplay_mu1320_f3_bap_v1.jar.DISABLED"
    WRAPPER = "f3_trial.sh"
    COLLECTOR = "collect_f3.sh"
    ENV_MARKER = None
    LISTENER = ("[CP/W][NavJava] MU1320-F3-BAP-V1 LISTENER_READY bap-yield; "
                "NavActiveIgnore quarantined; no renderer\n")

    @classmethod
    def setUpClass(cls):
        collector = (BASE / cls.STAGE / cls.COLLECTOR).read_text()
        cls.ENV_MARKER = re.search(r"^MARKER='([^']+)'", collector, re.M).group(1)

    @property
    def quarantine(self):
        return self.root / "quarantine/NavActiveIgnore.jar"

    def write_java_evidence(self):
        (self.tmp / "mu1320-f3-state.log").write_text(
            "F2 MU1320-F3-BAP-V1 START mode=BAP publishes=17,39,23,18,49,55,21\n"
            "F2 i=1 t=0 ev=SESSION rs=-1 act=0 mc=-1 ord=- sym=INACTIVE\n"
            "F2 i=2 t=40 ev=ACTIVATE+PRIMARY rs=6 act=1 mc=11 ord=0,1 sym=MANEUVER:13/192\n"
            "F2 i=3 t=120 ev=ROUTE_END+DEACTIVATE rs=0 act=0 mc=0 ord=- sym=INACTIVE\n")
        (self.tmp / "mu1320-f3-frames.cap").write_text(
            "#F2CAP v1 MU1320-F3-BAP-V1\n@1 0 E SESSION\n@2 40 F 1 CAPTURE_BODY_NOT_PRINTED\n")
        (self.tmp / "mu1320-f3-bap.log").write_text(
            "B i=0 t=0 START_PROBE build=MU1320-F3-BAP-V1 yield=stock_route metric=0 kill=0\n"
            "B i=2 t=40 BIND ok service=AppConnectorNavi refs=1\n"
            "B i=2 t=41 START d=13/192 dm=800 bar=-1 ms=2 dd=5400\n"
            "B i=2 t=41 CALL RG_STATUS 1\n"
            "B i=2 t=41 CALL DESCRIPTOR 13/192\n"
            "B i=3 t=120 TEARDOWN reason=ROUTE_END+DEACTIVATE\n"
            "B i=3 t=120 CALL RG_STATUS 0\n")

    def assert_java_evidence(self, stdout):
        self.assertIn("F3_STATE_COUNT[F2 i=]=3", stdout)
        self.assertIn("F3_STATE_COUNT[ev=REJECT]=0", stdout)
        self.assertIn("F3_BAP_COUNT[ BIND ok]=1", stdout)
        self.assertIn("F3_BAP_COUNT[ START ]=1", stdout)
        self.assertIn("F3_BAP_COUNT[ TEARDOWN ]=1", stdout)
        self.assertIn("F3_BAP_COUNT[ CALL ]=3", stdout)
        self.assertIn("F3_BAP_COUNT[ FAULT ]=0", stdout)
        self.assertIn("TEARDOWN reason=ROUTE_END+DEACTIVATE", stdout)
        self.assertNotIn("CALL RG_STATUS 1", stdout, "CALL lines are copied, not printed")
        self.assertNotIn("CAPTURE_BODY_NOT_PRINTED", stdout)
        self.assertIn("F3_KILL_SWITCH: ABSENT", stdout)
        self.assertIn("SLOGINFO_SAVED", stdout)
        armed = [p for p in (self.f.sd / "out").iterdir() if p.name.startswith("armed-")]
        self.assertEqual(len(armed), 1)
        self.assertIn("CALL RG_STATUS 1", (armed[0] / "mu1320-f3-bap.log").read_text())
        self.assertIn("CAPTURE_BODY_NOT_PRINTED", (armed[0] / "mu1320-f3-frames.cap").read_text())

    def assert_quarantined(self):
        self.assertFalse(self.old.exists())
        self.assertEqual(self.quarantine.read_bytes(), self.old_bytes)
        self.assertEqual((self.root / "backup/NavActiveIgnore.jar").read_bytes(), self.old_bytes)

    # Overrides: the navjava/F2 versions expect NavActiveIgnore to stay in place.
    def test_install_arm_parse_collect_and_rollback(self):
        self.ok("install")
        self.assertTrue(self.new.is_file())
        self.assert_quarantined()
        self.assertEqual((self.root / "phase.txt").read_text(), "SI_COMMITTED\n")
        status = self.ok("status")
        self.assertIn("NAV_ACTIVE_IGNORE: QUARANTINED", status.stdout)
        self.assertIn("JAVA_ARCHIVE: F3_BAP_INSTALLED", status.stdout)
        self.assertNotEqual(self.run_action("arm", mode="no_dio").returncode, 0)

        self.propagate()
        (self.tmp / "carplay_java.log").write_text(self.LISTENER)
        self.ok("arm", mode="no_dio")
        token = self.tmp / "mu1320-navhook-v1.arm"
        token.unlink()
        (self.tmp / "mu1320-navhook-v1-gate-202").write_text(
            "MU1320_NAVHOOK_V1_GATE mode=ACTIVE_TOKEN_CONSUMED pid=202 ppid=101\n")
        (self.tmp / "carplay_hook.log").write_text(
            "Registered module 'routeguidance'\nIdentify patched\nUpdate: state=6\nManeuver: idx=0\n")
        self.write_java_evidence()
        armed = self.ok("collect", "armed")
        self.assertIn("GLOBAL_GATE_RECEIPT_COUNT=1", armed.stdout)
        self.assert_java_evidence(armed.stdout)
        self.assertIn("DIO_ENV_MARKER=1 DIO_ENV_PRELOAD=1", armed.stdout)

        rollback = self.ok("rollback")
        self.assertIn("move quarantined NavActiveIgnore back", rollback.stdout)
        self.assertFalse(self.new.exists())
        self.assertFalse(self.quarantine.exists())
        self.assertEqual(self.old.read_bytes(), self.old_bytes)
        self.assertEqual(self.old.stat().st_mode & 0o777, 0o777)
        self.assertEqual((self.root / "phase.txt").read_text(), "INSTALLATION_BASELINE_RESTORED\n")
        self.propagate()
        for path in list(self.tmp.iterdir()):
            if path.is_file() or path.is_symlink():
                path.unlink()
        restored = self.ok("collect", "restored", dio_pid="303")
        self.assertIn("DIO_ENV_MARKER=0 DIO_ENV_PRELOAD=0", restored.stdout)
        self.assert_mounts()

    # F3-specific quarantine cases.
    def test_arm_refuses_when_navactiveignore_is_back_in_scan_tree(self):
        self.ok("install")
        self.propagate()
        self.quarantine.rename(self.old)
        (self.tmp / "carplay_java.log").write_text(self.LISTENER)
        result = self.run_action("arm", mode="no_dio")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be quarantined before arm", result.stdout + result.stderr)
        self.assertFalse((self.tmp / "mu1320-navhook-v1.arm").exists())

    def test_install_refuses_occupied_quarantine_slot(self):
        self.quarantine.parent.mkdir(parents=True, mode=0o700)
        self.root.chmod(0o700)
        self.quarantine.write_bytes(self.old_bytes)
        result = self.run_action("install")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("quarantine slot occupied", result.stdout + result.stderr)
        self.assertEqual(self.old.read_bytes(), self.old_bytes)
        self.assertFalse(self.new.exists())

    def test_rollback_restores_missing_navactiveignore_from_backup(self):
        self.ok("install")
        self.quarantine.unlink()
        status = self.ok("status")
        self.assertIn("NAV_ACTIVE_IGNORE: MISSING", status.stdout)
        result = self.ok("rollback")
        self.assertIn("restore NavActiveIgnore from verified backup", result.stdout)
        self.assertEqual(self.old.read_bytes(), self.old_bytes)
        self.assertEqual(self.old.stat().st_mode & 0o777, 0o777)
        self.assertFalse(self.new.exists())
        self.assert_mounts()

    def test_rollback_is_not_already_baseline_while_quarantined(self):
        # SI restored and Java removed by hand, NavActiveIgnore still quarantined.
        self.ok("install")
        self.system.write_bytes((navjava.RESOURCE / "smartphone_integrator.json").read_bytes())
        self.system.chmod(0o644)
        self.new.unlink()
        result = self.ok("rollback")
        self.assertNotIn("ROLLBACK_ALREADY_BASELINE", result.stdout)
        self.assertEqual(self.old.read_bytes(), self.old_bytes)
        self.assertFalse(self.quarantine.exists())
        again = self.ok("rollback")
        self.assertIn("ROLLBACK_ALREADY_BASELINE", again.stdout)

    def test_rollback_stops_on_unknown_navactiveignore(self):
        self.ok("install")
        self.old.write_text("foreign")
        result = self.run_action("rollback", direct=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown NavActiveIgnore state", result.stdout + result.stderr)
        self.assertTrue(self.new.exists())
        self.assertEqual(self.quarantine.read_bytes(), self.old_bytes)

    def test_status_reports_kill_switch(self):
        self.assertIn("BAP_KILL_SWITCH: ABSENT", self.ok("status").stdout)
        (self.tmp / "mu1320-f3-bap-off").write_text("")
        self.assertIn("BAP_KILL_SWITCH: PRESENT", self.ok("status").stdout)

    def test_navjava_and_f2_listener_markers_do_not_arm_f3(self):
        self.ok("install")
        self.propagate()
        for marker in ["MU1320-NAVJAVA-INGRESS-V1 LISTENER_READY receive-only",
                       "MU1320-F2-SHADOW-V1 LISTENER_READY shadow-state"]:
            (self.tmp / "carplay_java.log").write_text("[CP/W][NavJava] " + marker + "\n")
            result = self.run_action("arm", mode="no_dio")
            self.assertNotEqual(result.returncode, 0)


class F3V2TrialTests(F3TrialTests):
    """v2: same transaction; new names and the DSI rgActive yield signal (Java only)."""
    STAGE = "mu1320-f3-bap-v2"
    RUNTIME = "mu1320-rgi-f3-v2"
    NEW_JAR = "CarPlayRGI-MU1320-F3BapV2.jar"
    PAYLOAD_JAR = "carplay_mu1320_f3_bap_v2.jar.DISABLED"
    LISTENER = ("[CP/W][NavJava] MU1320-F3-BAP-V2 LISTENER_READY bap-yield; "
                "NavActiveIgnore quarantined; no renderer\n")

    def test_v1_listener_marker_does_not_arm_v2(self):
        self.ok("install")
        self.propagate()
        (self.tmp / "carplay_java.log").write_text(
            "[CP/W][NavJava] MU1320-F3-BAP-V1 LISTENER_READY bap-yield; NavActiveIgnore quarantined; no renderer\n")
        result = self.run_action("arm", mode="no_dio")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("listener marker absent", result.stdout + result.stderr)

    def test_v1_runtime_workspace_is_not_touched(self):
        v1 = self.f.app / "root/mu1320-rgi-f3-v1"
        v1.mkdir(parents=True, mode=0o700)
        (v1 / "phase.txt").write_text("INSTALLATION_BASELINE_RESTORED\n")
        self.ok("install")
        self.ok("rollback", direct=True)
        self.assertEqual((v1 / "phase.txt").read_text(), "INSTALLATION_BASELINE_RESTORED\n")


if __name__ == "__main__":
    unittest.main()
