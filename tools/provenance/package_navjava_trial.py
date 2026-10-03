#!/usr/bin/env python3
"""Audit and package the native-to-Java ingress trial."""
import copy
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
from formats import config

RESOURCE = ROOT / "resource"
STAGE = BASE / "navjava-trial"
ARCHIVE = ROOT / "archive/trial-zips/MU1320-RGI-navjava-ingress-v1.zip"
PREFIX = "mu1320-navjava-ingress-v1/"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    assert not ARCHIVE.exists(), "Never overwrite an issued archive; use a new version."
    build = json.loads((BASE / "reports/navjava-ingress-build.json").read_text())
    audit = json.loads((BASE / "reports/navjava-ingress-audit.json").read_text())
    prepared = json.loads((BASE / "reports/navjava-ingress-prepare.json").read_text())
    vehicle = json.loads((BASE / "reports/navhook-trial-vehicle-v1.json").read_text())
    assert audit["status"] == "PASS"
    assert vehicle["status"] == "NATIVE_RGI_RECEPTION_AND_RUNTIME_ROLLBACK_VERIFIED"
    jar = STAGE / "carplay_mu1320_navjava_ingress_v1.jar.DISABLED"
    assert sha(jar) == build["jar_sha256"] == prepared["java_artifact_sha256"]
    assert sha(STAGE / "libcarplay_hook.so") == prepared["native_artifact_sha256"]
    for name, digest in prepared["files"].items():
        assert sha(STAGE / name) == digest, name

    stock_si = config((RESOURCE / "smartphone_integrator.json").read_text())
    candidate_si = config((STAGE / "smartphone_integrator.json").read_text())
    expected_si = copy.deepcopy(stock_si)
    child = expected_si["children"]["carplay"]
    child["envs"][1] = ("IPL_CONFIG_DIR_DIO_MANAGER="
                         "/mnt/app/root/mu1320-rgi-navjava-v1/config")
    child["envs"] += ["MU1320_NAVJAVA_TRIAL=mu1320_navjava_v1_8b972a0d",
                      "LD_PRELOAD=/mnt/app/root/mu1320-rgi-navjava-v1/libcarplay_hook.so"]
    assert candidate_si == expected_si
    assert child["exec"] == "dio_manager" and child["path"] == "/mnt/app/eso/bin/apps"

    stock_dio = config((RESOURCE / "dio_manager.json").read_text())
    candidate_dio = config((STAGE / "dio_manager.json").read_text())
    expected_dio = copy.deepcopy(stock_dio)
    expected_dio["iap2"]["MessagesSentByAccessory"] += ["0x5200", "0x5203"]
    expected_dio["iap2"]["MessagesReceivedFromDevice"] += ["0x5201", "0x5202", "0x5204"]
    assert candidate_dio == expected_dio

    inputs = sorted(RESOURCE.glob("lib*.so*"))
    inputs += sorted((RESOURCE / "native-libs").rglob("*.so*"))
    inputs += sorted((RESOURCE / "cinemo").glob("*.so"))
    inventory = {str(path.relative_to(RESOURCE)): inspect(path)
                 for path in inputs if path.is_file()}
    native_audits = {
        "libcarplay_hook.so": check_binary(STAGE / "libcarplay_hook.so", inventory,
                                            shared_init_size=4),
        "loader_check": check_binary(STAGE / "loader_check", inventory),
        "mount_state": check_binary(STAGE / "mount_state", inventory),
    }
    assert all(item["status"] == "STATIC_PASS" for item in native_audits.values())

    for name in ["control.sh", "collect_navjava.sh", "navjava_trial.sh"]:
        subprocess.run(["/bin/sh", "-n", str(STAGE / name)], check=True)
    control = (STAGE / "control.sh").read_text()
    collector = (STAGE / "collect_navjava.sh").read_text()
    wrapper = (STAGE / "navjava_trial.sh").read_text()
    readme = (STAGE / "README.md").read_text()
    assert "MU1320-NAVJAVA-INGRESS-V1 LISTENER_READY" in control
    assert "NavActiveIgnore baseline changed" in control
    assert not re.search(r"exists [^\n;]*&&\s*fail", control)
    assert not re.search(r"(?m)^set -f$", collector)
    assert "for f in /tmp/mu1320-navhook-v1-gate-*" in collector
    assert "GLOBAL_GATE_RECEIPT_COUNT" in collector
    assert "CONTROL_EXIT=%s" in wrapper and "OUTER_EXIT:" in wrapper
    for phrase in ["调用 BAP", "NavActiveIgnore.jar", "PARSE_OK", "PARSE_REJECT",
                   "control.sh rollback", "SD_MOUNT_RESTORED", "完整重启"]:
        assert phrase in readme, phrase

    tests = subprocess.run(
        ["python3", "-m", "unittest", "test_navjava_trial.py", "-v"],
        cwd=BASE / "tests", env=dict(os.environ, PYTHONPATH=str(BASE / "tests")),
        capture_output=True, text=True)
    test_log = BASE / "reports/navjava-ingress-host-tests.txt"
    test_log.write_text(tests.stdout + tests.stderr)
    assert tests.returncode == 0, tests.stdout + tests.stderr

    names = sorted(path.name for path in STAGE.iterdir()
                   if path.is_file() and path.name != "SHA256SUMS")
    (STAGE / "SHA256SUMS").write_text(
        "".join(f"{sha(STAGE / name)}  {name}\n" for name in names))
    with zipfile.ZipFile(ARCHIVE, "x", zipfile.ZIP_DEFLATED) as archive:
        for name in names + ["SHA256SUMS"]:
            entry = zipfile.ZipInfo(PREFIX + name, (2026, 9, 24, 0, 0, 0))
            entry.create_system = 3
            entry.compress_type = zipfile.ZIP_DEFLATED
            executable = name in ["loader_check", "mount_state"]
            entry.external_attr = (0o100755 if executable else 0o100644) << 16
            archive.writestr(entry, (STAGE / name).read_bytes())
    with zipfile.ZipFile(ARCHIVE) as archive:
        assert archive.testzip() is None
        assert archive.namelist() == [PREFIX + name for name in names + ["SHA256SUMS"]]
        for name in names + ["SHA256SUMS"]:
            assert archive.read(PREFIX + name) == (STAGE / name).read_bytes()

    report = {
        "package": ARCHIVE.name,
        "sha256": sha(ARCHIVE),
        "size": ARCHIVE.stat().st_size,
        "file_count": len(names) + 1,
        "host_tests": "PASS (6 transaction tests + exact Java parser harness)",
        "java_audit": "PASS (19 classes, 365 references, no NavActiveIgnore overlap)",
        "native_artifact": "byte-identical to vehicle-verified navhook v1.2",
        "native_audit": native_audits,
        "scope": "native RGI to Java receive/parse only; no BAP, renderer or ownership change",
        "nav_active_ignore": "retained and backed up; no class overlap with ingress JAR",
        "collector_global_receipts_fixed": True,
        "control_exit_saved_on_sd": True,
        "final_sd_restore_and_outer_exit_emitted_to_terminal": True,
        "vehicle_tested": False,
        "host_test_log_sha256": sha(test_log),
        "files": {name: sha(STAGE / name) for name in names + ["SHA256SUMS"]},
    }
    (BASE / "reports/navjava-ingress-package.json").write_text(
        json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in
                      ["package", "sha256", "size", "host_tests", "vehicle_tested"]}, indent=2))


if __name__ == "__main__":
    main()
