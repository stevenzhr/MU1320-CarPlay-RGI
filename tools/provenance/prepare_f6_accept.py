#!/usr/bin/env python3
"""Prepare the F6 acceptance SD folder (copied to the SD card as is; no ZIP).

F6 changes no runtime code: the build under acceptance is F5 v5, the version
that passed on the car.  Every F5 v5 payload and script file is copied byte
for byte and checked against mu1320-f5-vchud-v5/SHA256SUMS; only the F5 README
and observation template are replaced by the F6 ones, and the read-only step
marker f6_mark.sh is added.  control.sh pins collect_f5.sh and f5_trial.sh pins
control.sh, so none of them may change: f6_mark.sh writes its own file.
"""
import hashlib
import json
import shutil
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
V5 = BASE / "mu1320-f5-vchud-v5"
SRC = BASE / "f6-src"
STAGE = BASE / "mu1320-f6-accept-v1"
REPORT = BASE / "reports/f6-accept-v1-prepare.json"
REPLACED = {"README.md", "OBSERVATIONS-TEMPLATE.txt", "SHA256SUMS"}
ADDED = {"README.md": "README.md", "OBSERVATIONS-F6.txt": "OBSERVATIONS-F6.txt", "f6_mark.sh": "f6_mark.sh"}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_sums(path):
    sums = {}
    for line in path.read_text().splitlines():
        digest, name = line.split("  ", 1)
        sums[name] = digest
    return sums


def main():
    v5_sums = read_sums(V5 / "SHA256SUMS")
    on_disk = sorted(p.name for p in V5.iterdir() if p.is_file() and p.name != "SHA256SUMS")
    if sorted(v5_sums) != on_disk:
        sys.exit("F5 v5 folder does not match its SHA256SUMS listing")
    if (STAGE / "out").exists():
        sys.exit("refusing to replace a stage folder that holds vehicle results: %s/out" % STAGE)
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir()
    carried = {}
    for name in on_disk:
        if name in REPLACED:
            continue
        src = V5 / name
        digest = sha256(src)
        if digest != v5_sums[name]:
            sys.exit("F5 v5 file changed since its SHA256SUMS: %s" % name)
        shutil.copy2(src, STAGE / name)
        carried[name] = digest
    for dst, src in ADDED.items():
        shutil.copy2(SRC / src, STAGE / dst)
    (STAGE / "f6_mark.sh").chmod(0o755)
    names = sorted(p.name for p in STAGE.iterdir() if p.is_file())
    sums = {n: sha256(STAGE / n) for n in names}
    (STAGE / "SHA256SUMS").write_text("".join("%s  %s\n" % (sums[n], n) for n in names))
    for name, digest in carried.items():
        assert sums[name] == digest == v5_sums[name], name
    report = {
        "stage": STAGE.name,
        "build_under_acceptance": "MU1320-F5-VCHUD-V5",
        "carried_from_f5_v5_byte_identical": sorted(carried),
        "replaced": sorted(REPLACED - {"SHA256SUMS"}),
        "added": sorted(ADDED),
        "sha256": sums,
        "f5_v5_jar_sha256": v5_sums["carplay_mu1320_f5_vchud_v5.jar.DISABLED"],
    }
    REPORT.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    print("F6_STAGE_READY %s files=%d carried=%d" % (STAGE.relative_to(BASE), len(names), len(carried)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
