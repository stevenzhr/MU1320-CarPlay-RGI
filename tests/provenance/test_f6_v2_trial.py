"""F6 v2 SD folder: the whole F5 v5 transaction suite rerun against it (F6 v2
names), plus the touchpad status/collect additions, the unarmed T session and
the byte-identity of the native/renderer files carried from F5 v5."""
import hashlib
import unittest

import test_f5_trial as f5

BASE = f5.BASE
STAGE = BASE / "mu1320-f6-accept-v2"
V5 = BASE / "mu1320-f5-vchud-v5"


class F6V2TransactionTests(f5.F5TrialTests):
    STAGE = "mu1320-f6-accept-v2"
    RUNTIME = "mu1320-rgi-f6-v2"
    NEW_JAR = "CarPlayRGI-MU1320-F6AcceptV2.jar"
    PAYLOAD_JAR = "carplay_mu1320_f6_accept_v2.jar.DISABLED"
    WRAPPER = "f6_trial.sh"
    COLLECTOR = "collect_f6.sh"
    LISTENER = ("[CP/W][NavJava] MU1320-F6-ACCEPT-V2 LISTENER_READY bap-yield+render; "
                "NavActiveIgnore quarantined; renderer 98 via ctx 80\n")

    # The inherited F5 suite asserts script labels as F5_*; the v2 scripts print F6_*.
    # Only expected strings are translated; the /tmp/mu1320-f5-* names are lowercase and untouched.
    @staticmethod
    def label(member):
        return member.replace("F5_", "F6_") if isinstance(member, str) else member

    def assertIn(self, member, container, msg=None):
        super().assertIn(self.label(member), container, msg)

    def assertNotIn(self, member, container, msg=None):
        super().assertNotIn(self.label(member), container, msg)
        if isinstance(member, str) and "F5_" in member:
            super().assertNotIn(member, container, msg)

    def test_no_f5_script_labels_in_output(self):
        self.ok("install")
        self.propagate()
        (self.tmp / "carplay_java.log").write_text(self.LISTENER)
        for out in [self.ok("status").stdout, self.ok("arm", mode="no_dio").stdout,
                    self.ok("collect", "snapshot").stdout, self.ok("rollback").stdout]:
            for line in out.splitlines():
                if "F5" in line.replace("MU1320-F5-VCHUD-V5", ""):
                    self.fail("F5 label in v2 output: " + line)
        self.assertIn("F6_install_FILES_PASSED", (sorted((self.f.sd / "out").glob("action-install-*"))[0]).read_text())

    def test_v1_runtime_workspace_is_not_touched(self):
        # F6 v1 ran on the F5 v5 workspace; it must survive a v2 install/rollback.
        others = [self.f.app / "root" / name for name in
                  ["mu1320-rgi-f3-v2", "mu1320-rgi-f5-v1", "mu1320-rgi-f5-v4", "mu1320-rgi-f5-v5"]]
        for other in others:
            other.mkdir(parents=True, mode=0o700)
            (other / "phase.txt").write_text("INSTALLATION_BASELINE_RESTORED\n")
        self.ok("install")
        self.ok("rollback", direct=True)
        for other in others:
            self.assertEqual((other / "phase.txt").read_text(), "INSTALLATION_BASELINE_RESTORED\n")

    def test_f5_v5_listener_does_not_arm_v2(self):
        self.ok("install")
        self.propagate()
        (self.tmp / "carplay_java.log").write_text(
            "[CP/W][NavJava] MU1320-F5-VCHUD-V5 LISTENER_READY bap-yield+render; "
            "NavActiveIgnore quarantined; renderer 98 via ctx 80\n")
        result = self.run_action("arm", mode="no_dio")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("listener marker absent", result.stdout + result.stderr)
        self.assertIsNone(self.renderer_pid())

    def test_status_reports_touchpad_switch_and_log(self):
        status = self.ok("status").stdout
        self.assertIn("TOUCHPAD_OFF_SWITCH: ABSENT", status)
        self.assertIn("TOUCHPAD_LOG: ABSENT", status)
        (self.tmp / "mu1320-f6-touchpad-off").write_text("")
        (self.tmp / "mu1320-f6-touchpad.log").write_text("T t=1 READY build=MU1320-F6-ACCEPT-V2\n")
        status = self.ok("status").stdout
        self.assertIn("TOUCHPAD_OFF_SWITCH: PRESENT", status)
        self.assertIn("TOUCHPAD_LOG: PRESENT", status)

    def test_unarmed_t_session_snapshot_collects_touchpad_log(self):
        """T session: install, reboot, no arm, CarPlay connected, collect snapshot."""
        self.ok("install")
        self.propagate()
        (self.tmp / "carplay_java.log").write_text(self.LISTENER)
        (self.tmp / "mu1320-f6-touchpad.log").write_text(
            "T t=100 READY build=MU1320-F6-ACCEPT-V2\n"
            "T t=200 SESSION g=1\n"
            "T t=300 MODE dpad=1 drain=0\n"
            "T t=310 DPAD key=6\nT t=320 DPAD key=6\nT t=330 DPAD key=8\n"
            "T t=340 GESTURE samples=12 ticks=3\n"
            "T t=400 MULTI count=2\n")
        snap = self.ok("collect", "snapshot", mode="no_dio")
        out = snap.stdout
        self.assertIn("F6_TOUCH_COUNT[ READY ]=1", out)
        self.assertIn("F6_TOUCH_COUNT[ SESSION ]=1", out)
        self.assertIn("F6_TOUCH_COUNT[ MODE dpad=1]=1", out)
        self.assertIn("F6_TOUCH_COUNT[ DPAD key=6]=2", out)
        self.assertIn("F6_TOUCH_COUNT[ DPAD key=8]=1", out)
        self.assertIn("F6_TOUCH_COUNT[ DPAD key=5]=0", out)
        self.assertIn("F6_TOUCH_COUNT[ FAULT ]=0", out)
        self.assertIn("F6_TOUCH_COUNT[ MULTI ]=1", out)
        self.assertIn("GESTURE samples=12 ticks=3", out)
        self.assertNotIn("DPAD key=6\n", out.split("F6_TOUCH_LINES_BEGIN")[1].split("F6_TOUCH_LINES_END")[0],
                         "per-tick lines are copied, not printed")
        self.assertIn("F6_TOUCHPAD_OFF: ABSENT", out)
        self.assertIn("F5_RENDERER: ABSENT", out, "an unarmed session never starts the renderer")
        self.assertFalse((self.tmp / "mu1320-navhook-v1.arm").exists(), "no token without arm")
        snaps = [p for p in (self.f.sd / "out").iterdir() if p.name.startswith("snapshot-")]
        self.assertEqual(len(snaps), 1)
        self.assertIn("DPAD key=8", (snaps[0] / "mu1320-f6-touchpad.log").read_text())
        # Still armable in a later boot (arm is once per boot, the install stays).
        self.ok("arm", mode="no_dio")


class F6V2FolderTests(unittest.TestCase):
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

    def test_native_and_renderer_files_are_f5_v5(self):
        v5, v2 = self.sums(V5), self.sums(STAGE)
        for name in ["libcarplay_hook.so", "loader_check", "mount_state", "trial_gate.c", "trial_gate.h",
                     "dio_manager.json", "ARM-TOKEN", "maneuver_render", "flag_atlas.rgba", "f4_unbuf.so"]:
            self.assertEqual(v2[name], v5[name], name)
        self.assertNotIn("carplay_mu1320_f5_vchud_v5.jar.DISABLED", v2)
        self.assertEqual((STAGE / "f6_mark.sh").read_bytes(), (BASE / "f6-v2-src/f6_mark.sh").read_bytes())

    def test_scripts_name_only_the_v2_workspace(self):
        for name in ["control.sh", "collect_f6.sh", "f6_trial.sh", "f5_sc.sh", "f5_dm.sh", "smartphone_integrator.json"]:
            text = (STAGE / name).read_text()
            self.assertNotIn("mu1320-rgi-f5-v5", text, name)
            self.assertNotIn("VCHUD", text.upper().replace("F5_", ""), name)
        self.assertIn("MU1320-F6-ACCEPT-V2 LISTENER_READY", (STAGE / "control.sh").read_text())
        self.assertFalse((STAGE / "f5_trial.sh").exists() or (STAGE / "collect_f5.sh").exists())
        self.assertIn("MU1320_F6_TRIAL=", (STAGE / "smartphone_integrator.json").read_text())
        # Only Java-bound names may still say f5.
        for name in ["control.sh", "collect_f6.sh", "f6_trial.sh", "f5_sc.sh", "f5_dm.sh"]:
            for line in (STAGE / name).read_text().splitlines():
                if "f5" in line.lower():
                    self.assertRegex(line, r"/tmp/mu1320-f5-|f5_sc\.sh|f5_dm\.sh|F5-V1-CTX-CALLERS", name)

    def test_readme_has_t_session_and_no_session_a(self):
        text = (STAGE / "README.md").read_text()
        self.assertNotIn("/fs/sda0/mu1320-f6-accept-v1/f5_trial.sh arm", text)
        self.assertIn("/fs/sda0/mu1320-f6-accept-v2/f6_trial.sh install", text)
        self.assertNotIn("mu1320-f6-accept-v2/f5_trial.sh", text)
        self.assertIn("场次 T", text)
        self.assertNotRegex(text, r"\*\*A\d+\*\*", "session A steps are not repeated")
        self.assertNotIn("## 场次 A", text)
        self.assertIn("mu1320-f6-touchpad-off", text)
        self.assertNotRegex(text, r"dmdt ts\b(?!`)")


if __name__ == "__main__":
    unittest.main()
