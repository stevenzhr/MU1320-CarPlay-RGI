"""F7 v1.1 SD folder: the whole F7 v1 transaction suite (fake vehicle, real
shell code) rerun with the v1.1 names, plus folder checks: navhook v1.3 lane
fix in the hook, F6 v3 Java, everything else carried from F7 v1, scripts
equal to F7 v1 apart from version names and pins, one workspace path across
hook, Java and scripts."""
import hashlib
import json
import re
import unittest
import zipfile

import test_f7_trial as v1

BASE = v1.BASE
STAGE = BASE / "mu1320-f7-daily-v1.1"
V1 = BASE / "mu1320-f7-daily-v1"
RUNTIME = "mu1320-rgi-f7-v1.1"
BUILD_ID = "MU1320-F7-DAILY-V1.1"


class F7V11TrialTests(v1.F7TrialTests):
    STAGE = "mu1320-f7-daily-v1.1"
    RUNTIME = RUNTIME
    NEW_JAR = "CarPlayRGI-MU1320-F7DailyV1_1.jar"
    PAYLOAD_JAR = "carplay_mu1320_f7_daily_v1_1.jar.DISABLED"
    LISTENER = ("[CP/W][NavJava] MU1320-F7-DAILY-V1.1 LISTENER_READY bap-yield+render; "
                "NavActiveIgnore quarantined; renderer 98 via ctx 80; keeper auto\n")

    def test_v1_runtime_workspace_is_not_touched(self):
        others = [self.f.app / "root" / n for n in
                  ["mu1320-rgi-f5-v5", "mu1320-rgi-f6-v2", "mu1320-rgi-f6-v3", "mu1320-rgi-f7-v1"]]
        for other in others:
            other.mkdir(parents=True, mode=0o700)
            (other / "phase.txt").write_text("INSTALLATION_BASELINE_RESTORED\n")
        self.ok("install")
        self.ok("rollback", direct=True)
        for other in others:
            self.assertEqual((other / "phase.txt").read_text(), "INSTALLATION_BASELINE_RESTORED\n")

    def test_f7_v1_listener_is_not_v11(self):
        self.ok("install")
        self.propagate()
        (self.tmp / "carplay_java.log").write_text(
            "[CP/W][NavJava] MU1320-F7-DAILY-V1 LISTENER_READY bap-yield+render; "
            "NavActiveIgnore quarantined; renderer 98 via ctx 80; keeper auto\n")
        self.assertIn("JAVA_LISTENER: ABSENT", self.ok("status").stdout)
        (self.tmp / "carplay_java.log").write_text(self.LISTENER)
        self.assertIn("JAVA_LISTENER: F7_READY", self.ok("status").stdout)


class F7V11FolderTests(unittest.TestCase):
    def sums(self, folder):
        return dict(reversed(line.split("  ", 1)) for line in (folder / "SHA256SUMS").read_text().splitlines())

    def test_sums_match_files(self):
        sums = self.sums(STAGE)
        self.assertEqual(sorted(sums), sorted(p.name for p in STAGE.iterdir() if p.is_file() and p.name != "SHA256SUMS"))
        for name, digest in sums.items():
            if name == "OBSERVATIONS-F7.txt":  # filled in place by the user after the car run
                continue
            self.assertEqual(hashlib.sha256((STAGE / name).read_bytes()).hexdigest(), digest, name)

    def test_f7_v1_folder_is_untouched(self):
        issued = json.loads((BASE / "reports/f7-v1-prepare.json").read_text())["files"]
        self.assertEqual(sorted(issued), sorted(p.name for p in V1.iterdir() if p.is_file()))
        for name, digest in issued.items():
            self.assertEqual(hashlib.sha256((V1 / name).read_bytes()).hexdigest(), digest, name)

    def test_native_is_f7_v1_plus_0004_and_the_rest_is_carried(self):
        old, new = self.sums(V1), self.sums(STAGE)
        native = json.loads((BASE / "reports/f7-v1.1-native-build.json").read_text())
        self.assertEqual(new["libcarplay_hook.so"], native["artifacts"]["libcarplay_hook.so"]["sha256"])
        self.assertEqual(native["base"]["f7_v1_hook_sha256"], old["libcarplay_hook.so"])
        for name in ["loader_check", "loader_check.c", "mount_state", "mount_state.c", "dio_manager.json",
                     "maneuver_render", "flag_atlas.rgba", "f4_unbuf.so", "geom-example.cfg", "f7_spawn",
                     "f7_spawn.c", "trial_gate.h"]:
            self.assertEqual(new[name], old[name], name)
        self.assertEqual((STAGE / "trial_gate.c").read_bytes(), (BASE / "f7-v1.1-src/trial_gate.c").read_bytes())
        self.assertFalse((STAGE / "ARM-TOKEN").exists())

    def test_java_is_the_v11_build(self):
        build = json.loads((BASE / "reports/f7-v1.1-build.json").read_text())
        self.assertEqual(self.sums(STAGE)["carplay_mu1320_f7_daily_v1_1.jar.DISABLED"], build["jar_sha256"])
        self.assertEqual(json.loads((BASE / "reports/f7-v1.1-audit.json").read_text())["status"], "PASS")
        v3 = json.loads((BASE / "reports/f6-v3-build.json").read_text())
        for n in ["com/luka/carplay/rgd/TripPlanner$LaneMemory.class", "com/luka/carplay/rgd/BapPlanner.class",
                  "com/luka/carplay/input/TouchpadGesture.class", "com/luka/carplay/rgd/F5BapOutput.class"]:
            self.assertIn(n, build["f6_v3_byte_identical"])
        self.assertEqual(build["merge"]["com/luka/carplay/input/TouchpadBridge"], "F7 v1 only")
        self.assertTrue(v3["jar_sha256"] == build["f6_v3_jar_sha256"])

    def test_scripts_equal_f7_v1_apart_from_versions_and_pins(self):
        def norm(text, version):
            names = {"1": ("mu1320-rgi-f7-v1", "MU1320-F7-DAILY-V1", "carplay_mu1320_f7_daily_v1.",
                           "CarPlayRGI-MU1320-F7DailyV1.", r"mu1320_f7_v1_[0-9a-f]{8}"),
                     "1.1": ("mu1320-rgi-f7-v1.1", "MU1320-F7-DAILY-V1.1", "carplay_mu1320_f7_daily_v1_1.",
                             "CarPlayRGI-MU1320-F7DailyV1_1.", r"mu1320_f7_v1_1_[0-9a-f]{8}")}[version]
            for token, name in zip(("RT", "BID", "JAR.", "AJAR."), names[:4]):
                text = text.replace(name, token)
            text = re.sub(names[4], "MARK", text)
            text = re.sub(r"'\d{6,10}' \] && \[ \"\$\{2:-\}\" = '\d+'", "PIN", text)
            return re.sub(r"\b\d{6,10} \d{1,7}\b", "CRC SIZE", text)
        for name in ["control.sh", "collect_f7.sh", "f7.sh", "f7_render.sh", "f5_sc.sh", "f5_dm.sh",
                     "smartphone_integrator.json"]:
            self.assertEqual(norm((V1 / name).read_text(), "1"), norm((STAGE / name).read_text(), "1.1"), name)

    def test_one_workspace_across_hook_java_and_scripts(self):
        for name in ["control.sh", "collect_f7.sh", "f7_render.sh", "f5_sc.sh", "f5_dm.sh", "smartphone_integrator.json"]:
            roots = set(re.findall(r"/mnt/app/root/(mu1320[\w.-]*)", (STAGE / name).read_text()))
            self.assertEqual(roots, {RUNTIME}, name)
        hook = (STAGE / "libcarplay_hook.so").read_bytes()
        self.assertIn(("/mnt/app/root/%s/off-native\0" % RUNTIME).encode(), hook)
        self.assertNotIn(b"mu1320-rgi-f7-v1/", hook)
        with zipfile.ZipFile(STAGE / "carplay_mu1320_f7_daily_v1_1.jar.DISABLED") as z:
            blobs = {n: z.read(n) for n in z.namelist()}
        joined = b"".join(blobs.values())
        for path in ["/mnt/app/root/%s/render/f5_sc.sh" % RUNTIME, "/mnt/app/root/%s/render/f7_render.sh" % RUNTIME,
                     "/mnt/app/root/%s/off-bap" % RUNTIME, "/mnt/app/root/%s/off-touchpad" % RUNTIME]:
            self.assertIn(path.encode(), joined, path)
        self.assertIsNone(re.search(rb"mu1320-rgi-f[67]-v[0-9](?!\.1)|F6-ACCEPT|MU1320-F7-DAILY-V1(?!\.1)", joined))
        control = (STAGE / "control.sh").read_text()
        self.assertIn("'%s LISTENER_READY'" % BUILD_ID, control)
        self.assertEqual((STAGE / "IDENTITY").read_text(), BUILD_ID + "\n")

    def test_marker_script(self):
        self.assertEqual((STAGE / "f7_mark.sh").read_bytes(), (BASE / "f7-v1.1-src/f7_mark.sh").read_bytes())

    def test_readme_and_sheet(self):
        readme = (STAGE / "README.md").read_text()
        for word in ["/fs/sda0/mu1320-f7-daily-v1.1/f7.sh install", "f7.sh rollback", "f7.sh stop", "f7.sh off native",
                     "f7.sh purge", "collect live", "不需要 arm", "f7_mark.sh", "B9", "v1.1", "MU1320-F5-VCHUD-V5",
                     "F7 v2 已经预留给 Toolbox"]:
            self.assertIn(word, readme)
        self.assertNotIn("mu1320-f7-daily-v1/f7.sh", readme)
        self.assertNotRegex(readme, r"dmdt ts\b(?!`)")
        sheet = (STAGE / "OBSERVATIONS-F7.txt").read_text()
        self.assertIn("Apple  Google  项目\n[  ]   [  ]    ", sheet)
        self.assertIn("f7_mark.sh", sheet)
        self.assertIn("A1", sheet)
        self.assertNotRegex(sheet, r"照片|时间\s*[|｜]|\|\s*时间")
        self.assertNotRegex(sheet, r"[A-Za-z]{4,} [a-z]{3,} [a-z]{3,}", "sheet is Chinese")


if __name__ == "__main__":
    unittest.main()
