#!/usr/bin/env python3
"""Prepare the F7 v1.1 SD folder (copied to the SD card as is; no ZIP).

F7 v1.1 = F7 v1 (automatic lifecycle, never on the car) rebased on F6 v3:
navhook v1.3 lane fix in the hook, F6 v3 Java (lane memory, arrival
distance, touchpad x1.25).  scripts/build_f7_v11_native.py and
scripts/build_f7_v11_java.py run first; the JAR is already in the folder.

The scripts are the F7 v1 scripts, renamed (workspace, JAR, marker,
BUILD_ID) with every changed payload checksum re-pinned; no behavioural
hunk.  reports/f7-v1.1-scripts.diff is the full result against F7 v1.
New: f7_mark.sh (the F6 v3 step marker with F7 labels, f7-v1.1-src).
Carried byte for byte from F7 v1: loader_check(.c), mount_state(.c),
dio_manager.json, maneuver_render, flag_atlas.rgba, f4_unbuf.so,
geom-example.cfg, f7_spawn(.c), trial_gate.h.
"""
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
V1 = BASE / "mu1320-f7-daily-v1"
STAGE = BASE / "mu1320-f7-daily-v1.1"
SRC = BASE / "f7-v1.1-src"
BUILD_ID = "MU1320-F7-DAILY-V1.1"
RUNTIME = "mu1320-rgi-f7-v1.1"
JAR_NAME = "carplay_mu1320_f7_daily_v1_1.jar.DISABLED"
NEW_JAR = "CarPlayRGI-MU1320-F7DailyV1_1.jar"
MARKER = "mu1320_f7_v1_1_" + hashlib.sha256(BUILD_ID.encode()).hexdigest()[:8]
V1_MARKER = "mu1320_f7_v1_b71babd1"
CARRIED = ["loader_check", "loader_check.c", "mount_state", "mount_state.c", "dio_manager.json", "maneuver_render",
           "flag_atlas.rgba", "f4_unbuf.so", "geom-example.cfg", "f7_spawn", "f7_spawn.c", "trial_gate.h"]
SCRIPTS = ["control.sh", "collect_f7.sh", "f7.sh", "f7_render.sh", "f5_sc.sh", "f5_dm.sh"]
EXEC = ["loader_check", "mount_state", "maneuver_render", "f7_spawn", "f5_sc.sh", "f7_render.sh"]
TESTS = ["test_f7_gate.py", "test_f7_trial.py", "test_f7_v11_native.py", "test_f7_v11_trial.py", "test_f7_mark.py"]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def crc(path):
    out = subprocess.check_output(["cksum", str(path)], text=True).split()
    return out[0], out[1]


def rename(text):
    text = text.replace(V1_MARKER, MARKER)
    text = text.replace("CarPlayRGI-MU1320-F7DailyV1.jar", NEW_JAR)
    text = text.replace("carplay_mu1320_f7_daily_v1.jar", JAR_NAME.replace(".DISABLED", ""))
    for old, new in [("MU1320-F7-DAILY-V1", BUILD_ID), ("mu1320-rgi-f7-v1", RUNTIME),
                     ("mu1320-f7-daily-v1", "mu1320-f7-daily-v1.1")]:
        text = re.sub(re.escape(old) + r"(?![\w.])", new, text)
    left = re.findall(r"mu1320-rgi-f7-v1(?!\.1)|MU1320-F7-DAILY-V1(?!\.1)|mu1320-f7-daily-v1(?!\.1)|daily_v1(?!_1)"
                      r"|F7DailyV1(?!_1)|" + V1_MARKER, text)
    assert not left, left
    return text


def repin(text, pins):
    for old, new in pins:
        if old != new:
            text = text.replace("%s %s" % old, "%s %s" % new)
            text = text.replace("'%s' ] && [ \"${2:-}\" = '%s'" % old, "'%s' ] && [ \"${2:-}\" = '%s'" % new)
    return text


def main():
    java = json.loads((BASE / "reports/f7-v1.1-build.json").read_text())
    audit = json.loads((BASE / "reports/f7-v1.1-audit.json").read_text())
    native = json.loads((BASE / "reports/f7-v1.1-native-build.json").read_text())
    v1prep = json.loads((BASE / "reports/f7-v1-prepare.json").read_text())
    assert audit["status"] == "PASS"
    jar = STAGE / JAR_NAME
    assert sha(jar) == java["jar_sha256"]
    for name, digest in v1prep["files"].items():  # the issued F7 v1 folder is untouched
        assert sha(V1 / name) == digest, "F7 v1 folder changed: " + name
    present = sorted(p.name for p in STAGE.iterdir())
    if present != [jar.name]:
        assert not (STAGE / "out").exists(), "refusing to touch a stage folder that holds vehicle results"
        for p in STAGE.iterdir():
            if p.name != jar.name:
                p.unlink()

    for name in CARRIED:
        shutil.copyfile(V1 / name, STAGE / name)
    nat = BASE.parent / "private-data/mu1320-rgi/f7-daily-v1.1-native"
    shutil.copyfile(nat / "src/build/libcarplay_hook.so", STAGE / "libcarplay_hook.so")
    assert sha(STAGE / "libcarplay_hook.so") == native["artifacts"]["libcarplay_hook.so"]["sha256"]
    assert sha(STAGE / "f7_spawn") == native["artifacts"]["f7_spawn"]["sha256"]
    for name in ["trial_gate.c", "f7_mark.sh", "README.md", "OBSERVATIONS-F7.txt"]:
        shutil.copyfile(SRC / name, STAGE / name)
    (STAGE / "IDENTITY").write_text(BUILD_ID + "\n")
    si = rename((V1 / "smartphone_integrator.json").read_text())
    assert si.count(RUNTIME) == 2 and si.count(MARKER) == 1 and "MU1320_F7_TRIAL=" + MARKER in si, "SI rename"
    (STAGE / "smartphone_integrator.json").write_text(si)

    # Pins: payloads first, then each script in the order it is pinned by the next.
    changed = [(crc(V1 / a), crc(STAGE / b)) for a, b in [
        ("IDENTITY", "IDENTITY"), ("libcarplay_hook.so", "libcarplay_hook.so"),
        ("carplay_mu1320_f7_daily_v1.jar.DISABLED", JAR_NAME), ("smartphone_integrator.json", "smartphone_integrator.json"),
        ("trial_gate.c", "trial_gate.c")]]
    for name in ["f5_sc.sh", "f5_dm.sh", "f7_render.sh", "collect_f7.sh", "control.sh", "f7.sh"]:
        (STAGE / name).write_text(repin(rename((V1 / name).read_text()), changed))
        changed.append((crc(V1 / name), crc(STAGE / name)))
    for name in EXEC + ["f7_mark.sh"]:
        (STAGE / name).chmod(0o755)

    # The keeper equals a fresh rendering of its template with the v1.1 values.
    keeper = (BASE / "f7-src/f7_render.sh.in").read_text()
    values = {"RUNTIME": "/mnt/app/root/" + RUNTIME, "JAR": NEW_JAR}
    for label, name in [("RENDER", "maneuver_render"), ("ATLAS", "flag_atlas.rgba"), ("DMH", "f5_dm.sh"),
                        ("UNBUF", "f4_unbuf.so"), ("SPAWN", "f7_spawn")]:
        values[label + "_CRC"], values[label + "_SIZE"] = crc(STAGE / name)
    for key, value in values.items():
        keeper = keeper.replace("@" + key + "@", value)
    assert keeper == (STAGE / "f7_render.sh").read_text(), "keeper differs from its template"

    stale = {"%s %s" % old for old, new in changed if old != new}
    for name in SCRIPTS + ["f7_mark.sh"]:
        text = (STAGE / name).read_text()
        for shell in ["/bin/sh", "/bin/ksh"]:
            if Path(shell).exists():
                subprocess.run([shell, "-n", str(STAGE / name)], check=True)
        for pair in stale:
            assert pair not in text, (name, pair)
        assert "3278904515" not in text and "navhook-v1" not in text, name
        assert not re.search(r"exists [^\n;]*&&\s*fail", text), name
        code = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
        assert not re.search(r"\bdm [^\n]*\bts\b|dmdt ts\b", code), name
        assert not re.search(r"tr -c '[^']*[A-Za-z0-9]-[A-Za-z0-9]", text), name
    for name in SCRIPTS + ["smartphone_integrator.json"]:
        roots = set(re.findall(r"/mnt/app/root/(mu1320[\w.-]*)", (STAGE / name).read_text()))
        assert roots <= {RUNTIME}, (name, roots)

    diffs = []
    for name in SCRIPTS + ["smartphone_integrator.json", "IDENTITY", "trial_gate.c", "README.md", "OBSERVATIONS-F7.txt"]:
        diffs += difflib.unified_diff((V1 / name).read_text().splitlines(True), (STAGE / name).read_text().splitlines(True),
                                      fromfile=V1.name + "/" + name, tofile=STAGE.name + "/" + name)
    diffs += difflib.unified_diff((BASE / "f6-v3-src/f6_mark.sh").read_text().splitlines(True),
                                  (STAGE / "f7_mark.sh").read_text().splitlines(True),
                                  fromfile="mu1320-f6-accept-v3/f6_mark.sh", tofile=STAGE.name + "/f7_mark.sh")
    (BASE / "reports/f7-v1.1-scripts.diff").write_text("".join(diffs))

    names = sorted(p.name for p in STAGE.iterdir() if p.is_file() and p.name != "SHA256SUMS")
    (STAGE / "SHA256SUMS").write_text("".join("%s  %s\n" % (sha(STAGE / n), n) for n in names))

    tests = subprocess.run([sys.executable, "-m", "unittest"] + TESTS + ["-v"],
                           cwd=BASE / "tests", env=dict(os.environ, PYTHONPATH=str(BASE / "tests")),
                           capture_output=True, text=True)
    log = BASE / "reports/f7-v1.1-host-tests.txt"
    log.write_text(tests.stdout + tests.stderr)
    assert tests.returncode == 0, tests.stdout[-4000:] + tests.stderr[-8000:]

    report = {
        "sd_folder": STAGE.name, "delivery": "copy the folder to the SD root; no ZIP is produced",
        "build_id": BUILD_ID, "runtime_root": "/mnt/app/root/" + RUNTIME, "marker": "MU1320_F7_TRIAL=" + MARKER,
        "java_artifact_sha256": sha(jar), "hook_sha256": sha(STAGE / "libcarplay_hook.so"),
        "carried_from_f7_v1": CARRIED,
        "scripts_derived_from": "F7 v1 scripts renamed and re-pinned; see reports/f7-v1.1-scripts.diff",
        "host_tests": TESTS, "host_test_log_sha256": sha(log), "vehicle_tested": False,
        "files": {n: sha(STAGE / n) for n in names + ["SHA256SUMS"]},
    }
    (BASE / "reports/f7-v1.1-prepare.json").write_text(json.dumps(report, indent=2) + "\n")
    print("Prepared", STAGE.name, "with", len(names) + 1, "files; no vehicle writes were performed.")


if __name__ == "__main__":
    main()
