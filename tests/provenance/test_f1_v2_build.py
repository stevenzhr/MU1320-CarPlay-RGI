"""The issued F1 v2 JAR is exactly the vehicle-tested Stage2 lifecycle family."""
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
PRIVATE = BASE.parent / "private-data" / "mu1320-rgi"
sys.path.insert(0, str(BASE / "scripts"))
import build_f1_v2 as build  # noqa: E402

JDK = build.JDK


class F1V2BuildTests(unittest.TestCase):
    def setUp(self):
        self.report = json.loads((BASE / "reports/f1-v2-build.json").read_text())
        with zipfile.ZipFile(build.JAR) as archive:
            self.entries = {n: archive.read(n) for n in archive.namelist()}

    def test_jar_matches_report(self):
        self.assertEqual(hashlib.sha256(build.JAR.read_bytes()).hexdigest(), self.report["jar_sha256"])
        self.assertEqual(sorted(self.entries), self.report["classes"])
        self.assertEqual(len(self.entries), 13)

    def test_entries_come_from_vehicle_tested_stage2_archive(self):
        with zipfile.ZipFile(build.STAGE2_ZIP) as outer:
            stage2 = outer.read(build.STAGE2_JAR_ENTRY)
        self.assertEqual(hashlib.sha256(stage2).hexdigest(), build.STAGE2_JAR_SHA256)
        with zipfile.ZipFile(io.BytesIO(stage2)) as archive:
            for name, data in self.entries.items():
                self.assertEqual(archive.read(name), data, name)

    @unittest.skipUnless((JDK / "java").exists(), "local JDK not present")
    def test_equivalence_harness_on_issued_bytes(self):
        with tempfile.TemporaryDirectory() as work:
            work = Path(work)
            classes, tests = work / "classes", work / "tests"
            tests.mkdir()
            for name, data in self.entries.items():
                target = classes / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            subprocess.run([str(JDK / "javac"), "-nowarn", "-d", str(tests), str(BASE / "f1-src/F1V2Harness.java")],
                           check=True, capture_output=True)
            result = subprocess.run(
                [str(JDK / "java"), "-Xverify:all", "-cp", str(tests), "F1V2Harness",
                 str(PRIVATE / "MU1320-base.jar"), str(classes),
                 str(BASE.parent / "resource/jars/NavActiveIgnore.jar")], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("F1_V2_EQUIVALENCE_TESTS_PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
