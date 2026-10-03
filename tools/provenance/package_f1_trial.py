#!/usr/bin/env python3
"""Audit and package the F1 NavActiveIgnore isolation / narrow NAVI seam trial."""
import hashlib
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
PRIVATE = BASE.parent / "private-data" / "mu1320-rgi"
ROOT = BASE.parent
sys.path.insert(0, str(PRIVATE / "python"))
sys.path.insert(0, str(BASE / "scripts"))

from audit_native import inspect
from audit_native_probe import check_binary

RESOURCE = ROOT / "resource"
VERSIONS = {
    "v1": dict(stage="f1-trial", archive="MU1320-RGI-f1-naviseam-v1.zip", prefix="mu1320-f1-naviseam-v1/",
               build="f1-naviseam-build.json", prepared="f1-trial-prepare.json", jar="carplay_mu1320_f1_naviseam_v1.jar.DISABLED",
               tests=["test_f1_trial.py", "test_f1_seam.py"], log="f1-trial-host-tests.txt", report="f1-trial-package.json",
               phrases=["stock_appstate_getters=1", "F1_SUPPRESS_NAVI"],
               scope="NavActiveIgnore.jar isolated out of jars/; stock DSICarplayListenerImpl + CarPlay NAVI-only seam"),
    "v2": dict(stage="f1-trial-v2", archive="MU1320-RGI-f1-navi-v2.zip", prefix="mu1320-f1-navi-v2/",
               build="f1-v2-build.json", prepared="f1-v2-prepare.json", jar="carplay_mu1320_f1_navi_v2.jar.DISABLED",
               tests=["test_f1_trial.py", "test_f1_v2_build.py"], log="f1-v2-host-tests.txt", report="f1-v2-package.json",
               phrases=["Stage2", "install-witness", "collect snapshot", "HMI_J9"],
               scope="NavActiveIgnore.jar isolated out of jars/; vehicle-tested Stage2 CarplayDSILifecycleController family (byte-identical)"),
}
VERSION = sys.argv[1] if len(sys.argv) > 1 else "v1"
CFG = VERSIONS[VERSION]
STAGE = BASE / CFG["stage"]
ARCHIVE = ROOT / "archive/trial-zips" / CFG["archive"]
PREFIX = CFG["prefix"]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    assert not ARCHIVE.exists(), "Never overwrite an issued archive; use a new version."
    build = json.loads((BASE / "reports" / CFG["build"]).read_text())
    prepared = json.loads((BASE / "reports" / CFG["prepared"]).read_text())
    jar = STAGE / CFG["jar"]
    assert sha(jar) == build["jar_sha256"] == prepared["java_artifact_sha256"]
    for name, digest in prepared["files"].items():
        assert sha(STAGE / name) == digest, name
    assert sha(STAGE / "mount_state") == sha(BASE / "navjava-trial/mount_state")

    inputs = sorted(RESOURCE.glob("lib*.so*")) + sorted((RESOURCE / "native-libs").rglob("*.so*"))
    inventory = {str(p.relative_to(RESOURCE)): inspect(p) for p in inputs if p.is_file()}
    mount_audit = check_binary(STAGE / "mount_state", inventory)
    assert mount_audit["status"] == "STATIC_PASS"

    for name in ["control.sh", "collect_f1.sh", "f1_trial.sh"]:
        subprocess.run(["/bin/sh", "-n", str(STAGE / name)], check=True)
        assert not re.search(r"exists [^\n;]*&&\s*fail", (STAGE / name).read_text()), name
    control = (STAGE / "control.sh").read_text()
    assert "/mnt/system" not in control.replace("SYSTEM=/mnt/system/etc/eso/production/smartphone_integrator.json", "") \
        .replace("/mnt/system/etc/eso/production/dio_manager.json", ""), "F1 must not touch /mnt/system"
    assert "mount -uw /mnt/system" not in control
    readme = (STAGE / "README.md").read_text()
    for phrase in ["NavActiveIgnore.jar", "control.sh rollback", "完整重启"] + CFG["phrases"]:
        assert phrase in readme, phrase

    tests = subprocess.run(
        ["python3", "-m", "unittest", *CFG["tests"], "-v"],
        cwd=BASE / "tests", env=dict(os.environ, PYTHONPATH=str(BASE / "tests")),
        capture_output=True, text=True)
    test_log = BASE / "reports" / CFG["log"]
    test_log.write_text(tests.stdout + tests.stderr)
    assert tests.returncode == 0, tests.stdout + tests.stderr

    names = sorted(p.name for p in STAGE.iterdir() if p.is_file() and p.name != "SHA256SUMS")
    (STAGE / "SHA256SUMS").write_text("".join(f"{sha(STAGE / n)}  {n}\n" for n in names))
    with zipfile.ZipFile(ARCHIVE, "x", zipfile.ZIP_DEFLATED) as archive:
        for name in names + ["SHA256SUMS"]:
            entry = zipfile.ZipInfo(PREFIX + name, (2026, 9, 24 if VERSION == "v1" else 25, 0, 0, 0))
            entry.create_system = 3
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = (0o100755 if name == "mount_state" else 0o100644) << 16
            archive.writestr(entry, (STAGE / name).read_bytes())
    with zipfile.ZipFile(ARCHIVE) as archive:
        assert archive.testzip() is None
        assert archive.namelist() == [PREFIX + n for n in names + ["SHA256SUMS"]]
        for name in names + ["SHA256SUMS"]:
            assert archive.read(PREFIX + name) == (STAGE / name).read_bytes()

    report = {
        "package": ARCHIVE.name,
        "sha256": sha(ARCHIVE),
        "size": ARCHIVE.stat().st_size,
        "file_count": len(names) + 1,
        "host_tests": "PASS (" + tests.stderr.strip().splitlines()[-3].strip() + "; includes -Xverify:all differential harness)",
        "java_artifact_sha256": build["jar_sha256"],
        "mount_helper": "byte-identical to vehicle-verified navjava v1 / navhook v1.2",
        "mount_helper_audit": mount_audit,
        "scope": CFG["scope"],
        "native_si_dio_changes": False,
        "system_partition_written": False,
        "android_auto": "stock; untested by design",
        "vehicle_tested": False,
        "host_test_log_sha256": sha(test_log),
        "files": {n: sha(STAGE / n) for n in names + ["SHA256SUMS"]},
    }
    (BASE / "reports" / CFG["report"]).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ["package", "sha256", "size", "host_tests"]}, indent=2))


if __name__ == "__main__":
    main()
