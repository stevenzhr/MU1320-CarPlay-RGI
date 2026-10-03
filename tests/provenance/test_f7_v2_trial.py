"""F7 v2 SD folder: the whole F7 transaction suite (fake vehicle, real shell
code) rerun with the v2 names, plus the B12 stop order (a fake Java answers
the runtime BAP kill switch the way F5Probe/F5BapOutput do on the car:
"GATE kill=1" in the BAP log, then the presenter releases context 80), the
environment cleanup for green-menu callers, and folder checks."""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zipfile

import test_f7_trial as v1

BASE = v1.BASE
STAGE = BASE / "mu1320-f7-daily-v2"
V11 = BASE / "mu1320-f7-daily-v1.1"
RUNTIME = "mu1320-rgi-f7-v2"
BUILD_ID = "MU1320-F7-DAILY-V2"
JAR = "carplay_mu1320_f7_daily_v2.jar.DISABLED"
sys.path.insert(0, str(BASE / "scripts"))


class FakeJava(threading.Thread):
    """Waits for the BAP kill switch; then logs GATE kill=1 and (optionally later) releases 80."""

    def __init__(self, test, ack_after=1.0, release_after=0.5, release_to="74", answer=True):
        super().__init__(daemon=True)
        self.t, self.ack_after, self.release_after, self.release_to, self.answer = \
            test, ack_after, release_after, release_to, answer
        self.renderer_alive_at_kill = None
        self.seen = False

    def run(self):
        kill = self.t.tmp / "mu1320-f5-bap-off"
        end = time.time() + 30
        while not kill.exists():
            if time.time() > end:
                return
            time.sleep(0.05)
        self.seen = True
        pid = self.t.renderer_pid()
        self.renderer_alive_at_kill = bool(pid and self.t.alive(pid))
        if not self.answer:
            return
        time.sleep(self.ack_after)
        with (self.t.tmp / "mu1320-f5-bap.log").open("a") as log:
            log.write("B i=40 t=5000 GATE kill=1\nB i=40 t=5001 TEARDOWN reason=KILL_SWITCH\n")
        time.sleep(self.release_after)
        if self.release_to:
            st = self.t.dm_state()
            st["cluster"] = self.release_to
            self.t.state.write_text(json.dumps(st))


class F7V2TrialTests(v1.F7TrialTests):
    STAGE = "mu1320-f7-daily-v2"
    RUNTIME = RUNTIME
    NEW_JAR = "CarPlayRGI-MU1320-F7DailyV2.jar"
    PAYLOAD_JAR = JAR
    LISTENER = ("[CP/W][NavJava] MU1320-F7-DAILY-V2 LISTENER_READY bap-yield+render; "
                "NavActiveIgnore quarantined; renderer 98 via ctx 80; keeper auto\n")

    def presenting(self):
        """arm_ready + a route shown: the cluster is on 80 and BAP has published before."""
        self.arm_ready()
        st = self.dm_state()
        st["cluster"] = "80"
        self.state.write_text(json.dumps(st))
        # an earlier off/on bap in the same boot already logged one kill edge
        (self.tmp / "mu1320-f5-bap.log").write_text("B i=1 t=10 GATE kill=1\nB i=2 t=20 GATE kill=0\nB i=3 t=30 START x\n")
        return self.renderer_pid()

    def test_v1_runtime_workspace_is_not_touched(self):
        others = [self.f.app / "root" / n for n in
                  ["mu1320-rgi-f5-v5", "mu1320-rgi-f6-v2", "mu1320-rgi-f6-v3", "mu1320-rgi-f7-v1", "mu1320-rgi-f7-v1.1"]]
        for other in others:
            other.mkdir(parents=True, mode=0o700)
            (other / "phase.txt").write_text("INSTALLATION_BASELINE_RESTORED\n")
        self.ok("install")
        self.ok("rollback", direct=True)
        for other in others:
            self.assertEqual((other / "phase.txt").read_text(), "INSTALLATION_BASELINE_RESTORED\n")

    def test_f7_v11_listener_is_not_v2(self):
        self.ok("install")
        self.propagate()
        (self.tmp / "carplay_java.log").write_text(
            "[CP/W][NavJava] MU1320-F7-DAILY-V1.1 LISTENER_READY bap-yield+render; "
            "NavActiveIgnore quarantined; renderer 98 via ctx 80; keeper auto\n")
        self.assertIn("JAVA_LISTENER: ABSENT", self.ok("status").stdout)
        (self.tmp / "carplay_java.log").write_text(self.LISTENER)
        self.assertIn("JAVA_LISTENER: F7_READY", self.ok("status").stdout)

    # ---- B12 --------------------------------------------------------------------
    def test_stop_switches_bap_off_through_java_before_the_renderer(self):
        pid = self.presenting()
        java = FakeJava(self, ack_after=1.0, release_after=1.5)
        java.start()
        result = self.ok("stop")
        java.join(5)
        out = result.stdout
        self.assertTrue(java.seen and java.renderer_alive_at_kill, "BAP kill came while the renderer still ran")
        self.assertIn("JAVA_RELEASE: BAP_OFF", out)
        self.assertRegex(out, r"JAVA_CLUSTER_CONTEXT: 74 waited=[1-8]s")
        self.assertNotIn("CLUSTER_ON_80", out, "Java released 80; no native switch needed")
        self.assertIn("RENDERER_STOP: pid=%d" % pid, out)
        self.assertLess(out.index("JAVA_RELEASE: BAP_OFF"), out.index("RENDERER_STOP"))
        self.assertIn("DISARM_CLUSTER_CONTEXT: 74 restored=1", out)
        self.assertIn("F7_STOPPED: BAP off (VC/HUD stock), renderer stopped and held", out)
        self.assertNotIn("an already-active DIO stays active", out)
        for name in ["mu1320-f5-bap-off", "mu1320-f7-render-hold", "mu1320-f7-native-off"]:
            self.assertTrue((self.tmp / name).exists(), name)
        self.assertEqual([a for a in self.dm_state()["log"] if a[:1] == ["sc"]], [], "no native sc at all")
        self.assertEqual(self.keep().returncode, 10)
        status = self.ok("status").stdout
        self.assertIn("BAP_KILL_SWITCH: PRESENT", status)
        self.assertEqual(list(self.tmp.glob("mu1320-f5-dm-stop-*count*")), [], "count scratch removed")

    def test_stop_falls_back_to_native_when_java_does_not_answer(self):
        pid = self.presenting()
        java = FakeJava(self, answer=False)
        java.start()
        started = time.time()
        result = self.ok("stop")
        self.assertTrue(java.seen)
        self.assertGreaterEqual(time.time() - started, 10, "waited for Java")
        self.assertIn("JAVA_RELEASE: NO_ACK", result.stdout)
        self.assertNotIn("JAVA_CLUSTER_CONTEXT", result.stdout)
        self.assertIn("RENDERER_STOP: pid=%d" % pid, result.stdout)
        self.assertIn("CLUSTER_ON_80: switching to 74", result.stdout)
        self.assertEqual(self.dm_state()["cluster"], "74")

    def test_stop_without_a_java_listener_does_not_wait(self):
        self.ok("install")
        self.propagate()
        started = time.time()
        result = self.ok("stop")
        self.assertLess(time.time() - started, 8)
        self.assertIn("JAVA_RELEASE: NO_JAVA", result.stdout)
        self.assertTrue((self.tmp / "mu1320-f5-bap-off").exists())

    def test_a_java_kill_older_than_the_stop_is_not_an_answer(self):
        self.presenting()
        # only the old edge from presenting(): no new GATE kill=1 -> NO_ACK, not BAP_OFF
        result = self.ok("stop")
        self.assertIn("JAVA_RELEASE: NO_ACK", result.stdout)

    def test_second_stop_and_rollback_after_stop_report_already_off(self):
        self.presenting()
        java = FakeJava(self)
        java.start()
        self.ok("stop")
        java.join(5)
        again = self.ok("stop")
        self.assertIn("JAVA_RELEASE: ALREADY_OFF", again.stdout)
        self.assertIn("JAVA_CLUSTER_CONTEXT: 74 waited=0s", again.stdout)
        rollback = self.ok("rollback")
        self.assertIn("JAVA_RELEASE: ALREADY_OFF", rollback.stdout)
        self.assertFalse(self.new.exists())

    def test_rollback_releases_through_java_too(self):
        pid = self.presenting()
        java = FakeJava(self, ack_after=0.5, release_after=0.2)
        java.start()
        result = self.ok("rollback")
        java.join(5)
        self.assertTrue(java.renderer_alive_at_kill)
        self.assertIn("JAVA_RELEASE: BAP_OFF", result.stdout)
        self.assertNotIn("CLUSTER_ON_80", result.stdout)
        self.assertIn("RENDERER_STOP: pid=%d" % pid, result.stdout)
        self.assertIn("F7_ACTION_PASSED", result.stdout)
        self.assertFalse(self.new.exists())

    def test_java_ack_but_cluster_stays_on_80_uses_the_native_fallback(self):
        self.presenting()
        java = FakeJava(self, ack_after=0.2, release_to=None)
        java.start()
        started = time.time()
        result = self.ok("stop")
        self.assertIn("JAVA_RELEASE: BAP_OFF", result.stdout)
        self.assertIn("JAVA_CLUSTER_CONTEXT: 80 waited=8s", result.stdout)
        self.assertIn("CLUSTER_ON_80: switching to 74", result.stdout)
        self.assertLess(time.time() - started, 25)

    # ---- environment of green-menu callers -----------------------------------------
    def test_menu_environment_is_cleaned(self):
        cwd = tempfile.mkdtemp(prefix="f7cwd")
        self.addCleanup(os.rmdir, cwd)
        env = dict(os.environ, MOUNT_FLAG=str(self.f.flag), SYSTEM_FLAG=str(self.env.s3.sysflag),
                   SD_FLAG=str(self.sdflag), MOUNT_CALLS=str(self.f.calls), FAIL="", ACTIVE_FILE=str(self.active),
                   PID_MODE="", DIO_PID="202", RUNTIME_ROOT=str(self.root), ENV_MARKER=self.ENV_MARKER,
                   LD_LIBRARY_PATH=".:/opt/lib:lib-rel::/root/lib-target:/opt/other")
        result = subprocess.run(["/bin/sh", "-c", 'umask 000; cd "$1" && exec /bin/sh "$2" status', "sh",
                                 cwd, str(self.f.sd / "f7.sh")], capture_output=True, text=True, timeout=25, env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("RUN_ENV: cwd=/ umask=0022 ld=/opt/lib:/root/lib-target:/opt/other", result.stdout)
        self.assertIn("F7_ACTION_PASSED", result.stdout)
        env["LD_LIBRARY_PATH"] = ".:lib"
        result = subprocess.run(["/bin/sh", str(self.f.sd / "control.sh"), "status"], capture_output=True,
                                text=True, timeout=25, env=env, cwd=cwd)
        self.assertIn("ld=unset", result.stdout)


class F7V2FolderTests(unittest.TestCase):
    def sums(self, folder):
        return dict(reversed(line.split("  ", 1)) for line in (folder / "SHA256SUMS").read_text().splitlines())

    def test_sums_match_files(self):
        sums = self.sums(STAGE)
        self.assertEqual(sorted(sums), sorted(p.name for p in STAGE.iterdir() if p.is_file() and p.name != "SHA256SUMS"))
        for name, digest in sums.items():
            self.assertEqual(hashlib.sha256((STAGE / name).read_bytes()).hexdigest(), digest, name)

    def test_f7_v11_folder_is_untouched(self):
        issued = json.loads((BASE / "reports/f7-v1.1-prepare.json").read_text())["files"]
        self.assertEqual(sorted(issued), sorted(p.name for p in V11.iterdir() if p.is_file()))
        for name, digest in issued.items():
            if name == "OBSERVATIONS-F7.txt":  # the sheet is filled in place by the user
                continue
            self.assertEqual(hashlib.sha256((V11 / name).read_bytes()).hexdigest(), digest, name)

    def test_native_is_v11_plus_b11_and_the_rest_is_carried(self):
        old, new = self.sums(V11), self.sums(STAGE)
        native = json.loads((BASE / "reports/f7-v2-native-build.json").read_text())
        self.assertEqual(new["libcarplay_hook.so"], native["artifacts"]["libcarplay_hook.so"]["sha256"])
        self.assertEqual(native["base"]["f7_v1_1_hook_sha256"], old["libcarplay_hook.so"])
        for name in ["loader_check", "loader_check.c", "mount_state", "mount_state.c", "dio_manager.json",
                     "maneuver_render", "flag_atlas.rgba", "f4_unbuf.so", "geom-example.cfg", "f7_spawn",
                     "f7_spawn.c", "trial_gate.h"]:
            self.assertEqual(new[name], old[name], name)
        self.assertEqual((STAGE / "trial_gate.c").read_bytes(), (BASE / "f7-v2-src/trial_gate.c").read_bytes())

    def test_java_is_v11_with_version_names_only(self):
        build = json.loads((BASE / "reports/f7-v2-build.json").read_text())
        self.assertEqual(self.sums(STAGE)[JAR], build["jar_sha256"])
        self.assertFalse(build["logic_changed"])
        self.assertEqual(json.loads((BASE / "reports/f7-v2-audit.json").read_text())["status"], "PASS")
        self.assertEqual(len(build["version_names_only"]), 7)
        self.assertEqual(len(build["f7_v1_1_byte_identical"]) + 7, build["class_count"])

    def test_scripts_equal_v11_apart_from_versions_pins_and_reviewed_hunks(self):
        def norm(text, version):
            names = {"1.1": ("mu1320-rgi-f7-v1.1", "MU1320-F7-DAILY-V1.1", "carplay_mu1320_f7_daily_v1_1.",
                             "CarPlayRGI-MU1320-F7DailyV1_1.", r"mu1320_f7_v1_1_[0-9a-f]{8}"),
                     "2": ("mu1320-rgi-f7-v2", "MU1320-F7-DAILY-V2", "carplay_mu1320_f7_daily_v2.",
                           "CarPlayRGI-MU1320-F7DailyV2.", r"mu1320_f7_v2_[0-9a-f]{8}")}[version]
            for token, name in zip(("RT", "BID", "JAR.", "AJAR."), names[:4]):
                text = text.replace(name, token)
            text = re.sub(names[4], "MARK", text)
            text = re.sub(r"'\d{6,10}' \] && \[ \"\$\{2:-\}\" = '\d+'", "PIN", text)
            return re.sub(r"\b\d{6,10} \d{1,7}\b", "CRC SIZE", text)
        import prepare_f7_v2_daily as prep
        for name in ["control.sh", "collect_f7.sh", "f7.sh", "f7_render.sh", "f5_sc.sh", "f5_dm.sh", "f7_mark.sh",
                     "smartphone_integrator.json"]:
            old = norm((V11 / name).read_text(), "1.1")
            for a, b in prep.HUNKS.get(name, []):
                old = old.replace(norm(a, "2"), norm(b, "2"))
            self.assertEqual(old, norm((STAGE / name).read_text(), "2"), name)
        control = (STAGE / "control.sh").read_text()
        self.assertIn("java_release\n    render_disarm", control)
        self.assertIn("grep 'MU1320-F7-DAILY-V2 LISTENER_READY' \"$JAVA_LOG\"", control)

    def test_one_workspace_across_hook_java_and_scripts(self):
        for name in ["control.sh", "collect_f7.sh", "f7_render.sh", "f5_sc.sh", "f5_dm.sh", "smartphone_integrator.json"]:
            roots = set(re.findall(r"/mnt/app/root/(mu1320[\w.-]*)", (STAGE / name).read_text()))
            self.assertEqual(roots, {RUNTIME}, name)
        hook = (STAGE / "libcarplay_hook.so").read_bytes()
        self.assertIn(("/mnt/app/root/%s/off-native\0" % RUNTIME).encode(), hook)
        self.assertNotIn(b"mu1320-rgi-f7-v1", hook)
        with zipfile.ZipFile(STAGE / JAR) as z:
            joined = b"".join(z.read(n) for n in z.namelist())
        for path in ["/mnt/app/root/%s/render/f5_sc.sh" % RUNTIME, "/mnt/app/root/%s/render/f7_render.sh" % RUNTIME,
                     "/mnt/app/root/%s/off-bap" % RUNTIME, "/mnt/app/root/%s/off-touchpad" % RUNTIME]:
            self.assertIn(path.encode(), joined, path)
        self.assertIsNone(re.search(rb"mu1320-rgi-f[67]-v1|F6-ACCEPT|MU1320-F7-DAILY-V1", joined))
        self.assertEqual((STAGE / "IDENTITY").read_text(), BUILD_ID + "\n")

    def test_toolbox_entry(self):
        lines = (STAGE / "TOOLBOX-ENTRY").read_text().splitlines()
        self.assertEqual(lines, ["MU1320_F7_TOOLBOX_ENTRY 1", "build=" + BUILD_ID, "wrapper=f7.sh"])
        for old in ["mu1320-f7-daily-v1", "mu1320-f7-daily-v1.1"]:
            self.assertFalse((BASE / old / "TOOLBOX-ENTRY").exists(), "older folders must not answer the menu")

    def test_readme_and_sheet(self):
        readme = (STAGE / "README.md").read_text()
        for word in ["/fs/sda0/mu1320-f7-daily-v2/f7.sh status", "Customization > MU1320 RGI", "TOOLBOX-ENTRY",
                     "1 Status", "2 Install", "3 Uninstall", "4 Collect", "5 EMERGENCY STOP", "B11", "B12",
                     "场次 Q", "场次 D", "场次 R", "f7.sh purge", "mu1320-toolbox-v1", "JAVA_RELEASE: BAP_OFF"]:
            self.assertIn(word, readme)
        self.assertNotRegex(readme, r"dmdt ts\b(?!`)")
        sheet = (STAGE / "OBSERVATIONS-F7.txt").read_text()
        self.assertIn("Apple  Google  项目\n[  ]   [  ]    ", sheet)
        for step in ["T1", "I1", "Q2", "Q3", "D1", "R1", "R3", "E1"]:
            self.assertRegex(sheet, r"(?m)^%s(  |$)" % step)
        self.assertNotRegex(sheet, r"[A-Za-z]{4,} [a-z]{3,} [a-z]{3,}", "sheet is Chinese")


if __name__ == "__main__":
    unittest.main()
