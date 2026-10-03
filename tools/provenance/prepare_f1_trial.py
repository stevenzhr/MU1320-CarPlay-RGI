#!/usr/bin/env python3
"""Prepare the F1 NavActiveIgnore isolation / narrow NAVI seam vehicle package."""
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
RESOURCE = BASE.parent / "resource"
VERSIONS = {
    "v1": dict(stage="f1-trial", jar="carplay_mu1320_f1_naviseam_v1.jar", build="f1-naviseam-build.json",
               collector="collect_f1.sh.in", archive="CarPlayRGI-MU1320-F1NaviSeam.jar",
               identity="MU1320-F1-NAVISEAM-V1\n", readme="README.md", observations="OBSERVATIONS-TEMPLATE.txt",
               report="f1-trial-prepare.json",
               scope="stock DSICarplayListenerImpl with CarPlay NAVI (ID 2) -> ID 0 seam; bounded /tmp log"),
    "v2": dict(stage="f1-trial-v2", jar="carplay_mu1320_f1_navi_v2.jar", build="f1-v2-build.json",
               collector="collect_f1v2.sh.in", archive="CarPlayRGI-MU1320-F1NaviV2.jar",
               identity="MU1320-F1-NAVI-V2\n", readme="README-v2.md", observations="OBSERVATIONS-TEMPLATE-v2.txt",
               report="f1-v2-prepare.json",
               scope="vehicle-tested Stage2 CarplayDSILifecycleController family (13 classes, byte-identical); CarPlay NAVI (ID 2) -> ID 0"),
}
VERSION = sys.argv[1] if len(sys.argv) > 1 else "v1"
CFG = VERSIONS[VERSION]
STAGE = BASE / CFG["stage"]
JAR = STAGE / (CFG["jar"] + ".DISABLED")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def crc(path):
    return subprocess.check_output(["cksum", str(path)], text=True).split()[:2]


def main():
    build = json.loads((BASE / "reports" / CFG["build"]).read_text())
    assert sha(JAR) == build["jar_sha256"]
    generated = ["IDENTITY", "README.md", "OBSERVATIONS-TEMPLATE.txt", "mount_state", "mount_state.c",
                 "collect_f1.sh", "control.sh", "f1_trial.sh"]
    present = sorted(p.name for p in STAGE.iterdir())
    # The build creates STAGE only for the immutable JAR; re-rendering is allowed.
    assert set(present) <= set(generated) | {JAR.name, "SHA256SUMS"}, present

    (STAGE / "IDENTITY").write_text(CFG["identity"])
    # Reuse the vehicle-proven mount helper byte for byte (navhook v1.2 / navjava v1).
    for name in ["mount_state", "mount_state.c"]:
        shutil.copyfile(BASE / "navjava-trial" / name, STAGE / name)
    (STAGE / "mount_state").chmod(0o755)
    shutil.copyfile(BASE / "f1-src" / CFG["readme"], STAGE / "README.md")
    shutil.copyfile(BASE / "f1-src" / CFG["observations"], STAGE / "OBSERVATIONS-TEMPLATE.txt")

    values = {"VERSION": VERSION, "RUNTIME_ROOT": "/mnt/app/root/mu1320-rgi-f1-" + VERSION,
              "F1_ARCHIVE": CFG["archive"], "PAYLOAD_NAME": CFG["jar"]}

    def pin(label, path):
        values[label + "_CRC"], values[label + "_SIZE"] = crc(path)

    navignore = RESOURCE / "jars/NavActiveIgnore.jar"
    for label, path in [("SI_OLD", RESOURCE / "smartphone_integrator.json"),
                        ("DIO_OLD", RESOURCE / "dio_manager.json"),
                        ("IDENTITY", STAGE / "IDENTITY"), ("MOUNT", STAGE / "mount_state"),
                        ("JAVA", JAR), ("NAVIGNORE", navignore)]:
        pin(label, path)
    values["PAYLOAD_CHECKS"] = "\n    ".join(
        f'check @{label}_CRC@ @{label}_SIZE@ "$stage_dir/{name}" || fail "{name} payload checksum"'
        for label, name in [("IDENTITY", "IDENTITY"), ("JAVA", JAR.name)])

    pinned = {}
    for manifest in ["input-manifest.json", "supplement-manifest.json"]:
        pinned.update(json.loads((BASE / "reports" / manifest).read_text())["files"])
    cases = []
    for path in sorted((RESOURCE / "jars").iterdir()):
        assert path.suffix in [".jar", ".zip"]
        assert sha(path) == pinned["jars/" + path.name]["sha256"]
        if path.name == navignore.name:
            continue  # handled explicitly per scan mode
        checksum, size = crc(path)
        target = "/mnt/app/eso/hmi/lsd/jars/" + path.name
        cases.append(f'            "{target}") check {checksum} {size} "$archive" || fail "archive changed: {path.name}" ;;')
    values["ARCHIVE_CASES"] = "\n".join(cases)

    def render(template, output):
        text = (BASE / "scripts" / template).read_text()
        for _ in range(2):
            for key, value in values.items():
                text = text.replace("@" + key + "@", value)
        assert not re.search(r"@[A-Z_]+@", text), output
        assert not re.search(r"exists [^\n;]*&&\s*fail", text), "QNX ksh exits under set -e on '&& fail'"
        (STAGE / output).write_text(text)
        subprocess.run(["/bin/sh", "-n", str(STAGE / output)], check=True)

    render(CFG["collector"], "collect_f1.sh")
    pin("COLLECT", STAGE / "collect_f1.sh")
    render("f1_control.sh.in", "control.sh")
    pin("CONTROL", STAGE / "control.sh")
    render("f1_sd.sh.in", "f1_trial.sh")

    report = {
        "version": VERSION,
        "runtime_root": values["RUNTIME_ROOT"],
        "java_artifact_sha256": sha(JAR),
        "java_scope": CFG["scope"],
        "nav_active_ignore": "backed up, then renamed out of the recursive jars/ scan tree into the private workspace",
        "android_auto": "stock; not tested (user does not use Android Auto)",
        "native_si_dio_changes": False,
        "system_partition_written": False,
        "vehicle_tested": False,
        "files": {p.name: sha(p) for p in sorted(STAGE.iterdir()) if p.is_file()},
    }
    if VERSION != "v1":
        (BASE / "reports" / CFG["report"]).write_text(json.dumps(report, indent=2) + "\n")
    print(f"Prepared F1 {VERSION} trial; no vehicle writes were performed.")


if __name__ == "__main__":
    main()
