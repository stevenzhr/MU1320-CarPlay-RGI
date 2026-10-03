"""Re-derive the issued F1 JAR and rerun the differential harness."""
import hashlib
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
import build_f1_naviseam as build  # noqa: E402

JDK = PRIVATE / "tools/jxe2jar/jvms/zulu8.78.0.19-ca-jdk8.0.412-macosx_aarch64/zulu-8.jdk/Contents/Home/bin"


class F1SeamTests(unittest.TestCase):
    def setUp(self):
        self.report = json.loads((BASE / "reports/f1-naviseam-build.json").read_text())
        self.stock = PRIVATE / "MU1320-base.jar"
        with zipfile.ZipFile(build.JAR) as archive:
            self.entries = {name: archive.read(name) for name in archive.namelist()}

    def test_jar_holds_only_patched_impl_and_helper(self):
        self.assertEqual(hashlib.sha256(build.JAR.read_bytes()).hexdigest(), self.report["jar_sha256"])
        self.assertEqual(sorted(self.entries), [build.HELPER + ".class", build.IMPL + ".class"])

    def test_patch_is_reproducible_from_stock(self):
        with zipfile.ZipFile(self.stock) as archive:
            stock = archive.read(build.IMPL + ".class")
        patched, info = build.patch_impl(stock)
        self.assertEqual(patched, self.entries[build.IMPL + ".class"])
        self.assertEqual(info["code_length"], info["original_code_length"] + build.INSERTED)
        # Everything outside convertAppState and the appended constants is stock.
        cf_stock, cf_patched = build.ClassFile(stock), build.ClassFile(patched)
        self.assertEqual(cf_patched.cp[:len(cf_stock.cp)], cf_stock.cp)
        self.assertEqual(len(cf_patched.cp) - len(cf_stock.cp), 6)
        for a, b in zip(cf_stock.methods, cf_patched.methods):
            if cf_stock.utf8(a["name"]) != "convertAppState":
                self.assertEqual(stock[a["start"]:a["end"]], patched[b["start"]:b["end"]])

    def test_helper_is_java14_classfile(self):
        major = int.from_bytes(self.entries[build.HELPER + ".class"][6:8], "big")
        self.assertEqual(major, 48)

    @unittest.skipUnless((JDK / "java").exists(), "local JDK not present")
    def test_differential_harness_under_full_verification(self):
        with tempfile.TemporaryDirectory() as work:
            work = Path(work)
            classes, tests, run = work / "classes", work / "tests", work / "run"
            for d in (classes, tests, run):
                d.mkdir()
            for name, data in self.entries.items():
                target = classes / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            subprocess.run([str(JDK / "javac"), "-d", str(tests), str(BASE / "f1-src/NaviSeamHarness.java")],
                           check=True, capture_output=True)
            result = subprocess.run(
                [str(JDK / "java"), "-Xverify:all", "-cp", str(tests), "NaviSeamHarness", str(self.stock),
                 str(classes), str(BASE.parent / "resource/jars/NavActiveIgnore.jar"), str(run)],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("F1_NAVISEAM_DIFFERENTIAL_TESTS_PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
