"""F6 acceptance SD folder: the F5 v5 transaction suite rerun against it, plus
the byte-identity of every carried F5 v5 file (F6 changes no runtime code)."""
import hashlib
import unittest
from pathlib import Path

import test_f5_trial as f5

BASE = f5.BASE
STAGE = BASE / "mu1320-f6-accept-v1"
V5 = BASE / "mu1320-f5-vchud-v5"


class F6AcceptTransactionTests(f5.F5TrialTests):
    STAGE = "mu1320-f6-accept-v1"


class F6FolderTests(unittest.TestCase):
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

    def test_every_f5_v5_file_is_carried_unchanged(self):
        v5, f6 = self.sums(V5), self.sums(STAGE)
        carried = set(v5) - {"README.md", "OBSERVATIONS-TEMPLATE.txt"}
        for name in carried:
            self.assertEqual(f6.get(name), v5[name], name)
        self.assertEqual(set(f6) - carried, {"README.md", "OBSERVATIONS-F6.txt", "f6_mark.sh"})
        self.assertEqual((STAGE / "f6_mark.sh").read_bytes(), (BASE / "f6-src/f6_mark.sh").read_bytes())

    def test_readme_uses_the_f6_folder_and_never_screenshots(self):
        text = (STAGE / "README.md").read_text()
        self.assertNotIn("/fs/sda0/mu1320-f5-vchud-v5", text)
        self.assertIn("/fs/sda0/mu1320-f6-accept-v1/f5_trial.sh arm", text)
        self.assertNotRegex(text, r"dmdt ts\b(?!`)")


if __name__ == "__main__":
    unittest.main()
