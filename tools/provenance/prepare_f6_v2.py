#!/usr/bin/env python3
"""Prepare the F6 v2 SD folder (copied to the SD card as is; no ZIP).

F6 v2 = F5 v5 vehicle mechanics + the touchpad->DPAD bridge (Java only; see
scripts/build_f6_v2.py, which must run first and leaves only the JAR in the
stage).  Native hook, renderer, dmdt shim and pinned stock baselines are the
F5 v5 files byte for byte.  The scripts are rendered from the same templates
as F5 v5 (prepare_f5_trial: F3 v2 templates + rename + renderer hunks), then:

- F6 v2 names: runtime root /mnt/app/root/mu1320-rgi-f6-v2 (the path the v2
  StockDisplay pins), JAR names, SI marker, Java listener BUILD_ID; then every
  script-level F5 name (wrapper f6_trial.sh, collector collect_f6.sh, status
  and collect labels F6_*, SI marker key MU1320_F6_TRIAL) becomes F6.  Only
  names the F5 v5 navigation bytecode uses stay F5 (JAVA_BOUND: the
  /tmp/mu1320-f5-* logs/switches and the render/f5_sc.sh + f5_dm.sh helpers).
- status shows the touchpad off switch and log; collect copies and counts
  /tmp/mu1320-f6-touchpad.log (numbers only).

reports/f6-v2-scripts.diff records the result against the F5 v5 scripts that
ran on the car.
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
sys.path.insert(0, str(BASE / "scripts"))
import prepare_f5_trial as p5  # noqa: E402  (VERSION 5 templates and hunks)

f3p = p5.f3p
BUILD_ID = "MU1320-F6-ACCEPT-V2"
REPORT = "f6-v2"
STAGE = BASE / "mu1320-f6-accept-v2"
V5 = BASE / "mu1320-f5-vchud-v5"
SRC = BASE / "f6-v2-src"
JAR_NAME = "carplay_mu1320_f6_accept_v2.jar.DISABLED"
RUNTIME = "/mnt/app/root/mu1320-rgi-f6-v2"
MARKER = "mu1320_f6_v2_" + hashlib.sha256(BUILD_ID.encode()).hexdigest()[:8]
LISTENER = BUILD_ID + " LISTENER_READY"
TOUCH_LOG = "/tmp/mu1320-f6-touchpad.log"
TOUCH_OFF = "/tmp/mu1320-f6-touchpad-off"
# Byte-identical to the F5 v5 folder (which itself pins F3 v2 / F4 run4).
CARRIED = ["libcarplay_hook.so", "loader_check", "loader_check.c", "mount_state", "mount_state.c",
           "trial_gate.c", "trial_gate.h", "dio_manager.json", "ARM-TOKEN",
           "maneuver_render", "flag_atlas.rgba", "f4_unbuf.so", "geom-example.cfg"]

sha = p5.sha
crc = p5.crc
replace_once = p5.replace_once


def rename(text):
    """F5 v5 -> F6 v2 version-specific names (workspace, JAR, marker, BUILD_ID)."""
    for old, new in [
        (p5.MARKER, MARKER),
        (p5.BUILD_ID, BUILD_ID),
        ("MU1320-F5-V5-VERBOSE", "MU1320-F6-V2-VERBOSE"),
        ("CarPlayRGI-MU1320-F5VchudV5.jar", "CarPlayRGI-MU1320-F6AcceptV2.jar"),
        ("carplay_mu1320_f5_vchud_v5", "carplay_mu1320_f6_accept_v2"),
        ("mu1320-rgi-f5-v5", "mu1320-rgi-f6-v2"),
        ("mu1320-f5-v5", "mu1320-f6-v2"),
    ]:
        text = text.replace(old, new)
    assert not re.search(r"f5[-_]v5|F5-?VCHUD|F5Vchud", text, re.I), re.findall(r".*(?:f5[-_]v5|vchud).*", text, re.I)
    return text


# Names the F5 v5 navigation bytecode (or the helpers it runs) uses; they stay F5.
JAVA_BOUND = ["/tmp/mu1320-f5-", "f5_sc.sh", "f5_dm.sh", "F5-V1-CTX-CALLERS"]


def relabel(text):
    """Every other script-level F5 name (labels, wrapper/collector names, SI
    marker key, pending files, messages) becomes F6."""
    text = rename(text)
    for i, name in enumerate(JAVA_BOUND):
        text = text.replace(name, "\0KEEP%d\0" % i)
    for old, new in [("collect_f5.sh", "collect_f6.sh"), ("f5_trial.sh", "f6_trial.sh"),
                     (".mu1320-f5", ".mu1320-f6"), ("F5", "F6")]:
        text = text.replace(old, new)
    for i, name in enumerate(JAVA_BOUND):
        text = text.replace("\0KEEP%d\0" % i, name)
    left = [l for l in text.splitlines() if re.search("f5", l, re.I) and not any(n in l for n in JAVA_BOUND)]
    assert not left, left
    return text


def control_hunks(c):
    c = replace_once(c, """echo "GEOMETRY_OVERRIDE: $(exists /tmp/mu1320-f5-geom.cfg && echo PRESENT || echo ABSENT)"
""", """echo "GEOMETRY_OVERRIDE: $(exists /tmp/mu1320-f5-geom.cfg && echo PRESENT || echo ABSENT)"
echo "TOUCHPAD_OFF_SWITCH: $(exists %s && echo PRESENT || echo ABSENT)"
echo "TOUCHPAD_LOG: $(exists %s && echo PRESENT || echo ABSENT)"
""" % (TOUCH_OFF, TOUCH_LOG))
    return c


def collector_hunks(col):
    col = replace_once(col, "/tmp/mu1320-f5-sc.log /tmp/mu1320-f5-ctx-mode; do",
                       "/tmp/mu1320-f5-sc.log /tmp/mu1320-f5-ctx-mode %s; do" % TOUCH_LOG)
    col = replace_once(col, """    echo "F5_CALIBRATION: $( [ -e /tmp/mu1320-f5-calib ] && echo PRESENT || echo ABSENT )"
""", """    echo "F5_CALIBRATION: $( [ -e /tmp/mu1320-f5-calib ] && echo PRESENT || echo ABSENT )"
    # Touchpad bridge log: numbers only (key codes, sample/tick counts); no trajectories.
    touch_log=%s
    for label in ' READY ' ' SESSION ' ' MODE dpad=1' ' MODE dpad=0' ' DPAD key=5' ' DPAD key=6' ' DPAD key=7' ' DPAD key=8' ' GESTURE ' ' MULTI ' ' FAULT ' ' DROP ' ' STOP' ' LOG_LIMIT'; do
        n=0; if [ -f "$touch_log" ]; then n=$(grep -c -- "$label" "$touch_log" 2>/dev/null || :); fi
        echo "F6_TOUCH_COUNT[$label]=${n:-0}"
    done
    echo F6_TOUCH_LINES_BEGIN
    if [ -f "$touch_log" ]; then grep -v ' DPAD key=' "$touch_log" | head -200 || :; fi
    echo F6_TOUCH_LINES_END
    echo "F6_TOUCHPAD_OFF: $( [ -e %s ] && echo PRESENT || echo ABSENT )"
""" % (TOUCH_LOG, TOUCH_OFF))
    return col


def main():
    build = json.loads((BASE / "reports/f6-v2-build.json").read_text())
    audit = json.loads((BASE / "reports/f6-v2-audit.json").read_text())
    assert audit["status"] == "PASS"
    jar = STAGE / JAR_NAME
    assert sha(jar) == build["jar_sha256"]
    present = sorted(p.name for p in STAGE.iterdir())
    if present != [jar.name]:
        # Re-preparing: only files this script writes may exist; never vehicle results.
        assert not (STAGE / "out").exists(), "refusing to touch a stage folder that holds vehicle results"
        for p in STAGE.iterdir():
            if p.name != jar.name:
                p.unlink()
    v5_sums = dict(reversed(line.split("  ", 1)) for line in (V5 / "SHA256SUMS").read_text().splitlines())

    for name in CARRIED:
        shutil.copyfile(V5 / name, STAGE / name)
        assert sha(STAGE / name) == v5_sums[name], name
    for name in ["loader_check", "mount_state", "maneuver_render"]:
        (STAGE / name).chmod(0o755)
    si = relabel((V5 / "smartphone_integrator.json").read_text())
    assert si.count(RUNTIME) == 2 and si.count(MARKER) == 1, "SI rename"
    (STAGE / "smartphone_integrator.json").write_text(si)
    (STAGE / "IDENTITY").write_text(BUILD_ID + "\n")
    shutil.copyfile(SRC / "README.md", STAGE / "README.md")
    shutil.copyfile(SRC / "OBSERVATIONS-F6V2.txt", STAGE / "OBSERVATIONS-F6V2.txt")
    shutil.copyfile(SRC / "f6_mark.sh", STAGE / "f6_mark.sh")
    (STAGE / "f6_mark.sh").chmod(0o755)
    subprocess.run(["/bin/sh", "-n", str(STAGE / "f6_mark.sh")], check=True)

    values = {"MARKER": MARKER, "RUNTIME": RUNTIME}

    def pin(label, path):
        checksum, size = crc(path)
        values[label + "_CRC"], values[label + "_SIZE"] = checksum, size

    resource = f3p.RESOURCE
    for label, path in [
        ("SI_OLD", resource / "smartphone_integrator.json"), ("SI_NEW", STAGE / "smartphone_integrator.json"),
        ("DIO_OLD", resource / "dio_manager.json"), ("DIO_NEW", STAGE / "dio_manager.json"),
        ("IDENTITY", STAGE / "IDENTITY"), ("ARM", STAGE / "ARM-TOKEN"),
        ("HOOK", STAGE / "libcarplay_hook.so"), ("MOUNT", STAGE / "mount_state"),
        ("LOADER", STAGE / "loader_check"), ("JAVA", jar), ("NAVIGNORE", resource / "jars/NavActiveIgnore.jar"),
        ("RENDER", STAGE / "maneuver_render"), ("ATLAS", STAGE / "flag_atlas.rgba"), ("UNBUF", STAGE / "f4_unbuf.so"),
    ]:
        pin(label, path)

    # Pinned stock baselines: exactly the ones the F5 v5 control checks (from F3 v2).
    f3_control = (p5.F3_STAGE / "control.sh").read_text()
    native = re.findall(r'^    check \d+ \d+ /\S+ \|\| fail "[^"]+ baseline"$', f3_control, re.M)
    assert len(native) == 8, native
    values["NATIVE_CHECKS"] = "\n".join(native).strip()
    baseline = re.findall(r'^    check \d+ \d+ /mnt/app/eso/hmi/lsd/jars/\S+ \|\| fail "baseline archive differs: [^"]+"$', f3_control, re.M)
    cases = re.findall(r'^            "/mnt/app/eso/hmi/lsd/jars/[^"]+"\) check .*;;$', f3_control, re.M)
    assert len(baseline) == len(cases) == 18, (len(baseline), len(cases))
    values["BASELINE_ARCHIVE_CHECKS"] = "\n".join(baseline).strip()
    values["ARCHIVE_CASES"] = "\n".join(cases)
    payloads = [("SI_NEW", "smartphone_integrator.json"), ("DIO_NEW", "dio_manager.json"),
                ("IDENTITY", "IDENTITY"), ("ARM", "ARM-TOKEN"), ("HOOK", "libcarplay_hook.so"),
                ("LOADER", "loader_check"), ("JAVA", jar.name), ("RENDER", "maneuver_render"),
                ("ATLAS", "flag_atlas.rgba"), ("SC", "f5_sc.sh")]
    values["PAYLOAD_CHECKS"] = "\n    ".join(
        f'check @{label}_CRC@ @{label}_SIZE@ "$stage_dir/{name}" || fail "{name} payload checksum"'
        for label, name in payloads)

    # Same template chain as F5 v5 (with the v5 module constants), then F6 v2 names/hunks.
    control_t, collector_t, sd_t = f3p.derive_templates()
    control_t = relabel(control_hunks(p5.control_hunks(p5.rename(control_t))))
    collector_t = relabel(collector_hunks(p5.collector_hunks(p5.rename(collector_t))))
    sd_t = relabel(p5.rename(sd_t))
    # The helpers keep their file names (Java runs render/f5_sc.sh) but their labels become F6.
    helper_t = relabel((BASE / "scripts/f5_dm.sh.in").read_text())
    sc_t = relabel((BASE / "scripts/f5_sc.sh.in").read_text())

    def render(template, output):
        text = template
        for _ in range(2):
            for key, value in values.items():
                text = text.replace("@" + key + "@", value)
        assert not re.search(r"@[A-Z_]+@", text), (output, re.findall(r"@[A-Z_]+@", text))
        (STAGE / output).write_text(text)
        subprocess.run(["/bin/sh", "-n", str(STAGE / output)], check=True)
        return text

    render(helper_t, "f5_dm.sh")
    pin("DMH", STAGE / "f5_dm.sh")
    render(sc_t, "f5_sc.sh")
    pin("SC", STAGE / "f5_sc.sh")
    (STAGE / "f5_sc.sh").chmod(0o755)
    render(collector_t, "collect_f6.sh")
    pin("COLLECT", STAGE / "collect_f6.sh")
    control = render(control_t, "control.sh")
    pin("CONTROL", STAGE / "control.sh")
    render(sd_t, "f6_trial.sh")
    for name in ["control.sh", "collect_f6.sh", "f6_trial.sh", "f5_dm.sh", "f5_sc.sh", "f6_mark.sh"]:
        text = (STAGE / name).read_text()
        assert not re.search(r"exists [^\n;]*&&\s*fail", text), name
        assert "dmdt ts" not in text.replace('"dmdt ts"', ""), name
        assert not re.search(r'\bdm [^\n]*\bts\b', text), name
    assert LISTENER in control and RUNTIME in control
    # Helpers equal F5 v5 apart from the runtime root and F6 labels.
    for name in ["f5_dm.sh", "f5_sc.sh"]:
        assert (STAGE / name).read_text() == relabel((V5 / name).read_text()), name

    diffs = []
    for old, name in [("control.sh", "control.sh"), ("collect_f5.sh", "collect_f6.sh"),
                      ("f5_trial.sh", "f6_trial.sh"), ("smartphone_integrator.json", "smartphone_integrator.json")]:
        diffs += difflib.unified_diff(
            (V5 / old).read_text().splitlines(True), (STAGE / name).read_text().splitlines(True),
            fromfile=V5.name + "/" + old, tofile=STAGE.name + "/" + name)
    (BASE / "reports" / (REPORT + "-scripts.diff")).write_text("".join(diffs))

    names = sorted(p.name for p in STAGE.iterdir() if p.is_file() and p.name != "SHA256SUMS")
    (STAGE / "SHA256SUMS").write_text("".join(f"{sha(STAGE / name)}  {name}\n" for name in names))

    tests = subprocess.run(
        [sys.executable, "-m", "unittest", "test_f6_v2_trial.py", "test_f6_v2_mark.py", "-v"],
        cwd=BASE / "tests", env=dict(os.environ, PYTHONPATH=str(BASE / "tests")),
        capture_output=True, text=True)
    test_log = BASE / "reports" / (REPORT + "-host-tests.txt")
    test_log.write_text(tests.stdout + tests.stderr)
    assert tests.returncode == 0, tests.stdout[-4000:] + tests.stderr[-8000:]

    report = {
        "sd_folder": STAGE.name,
        "delivery": "copy the folder to the SD root; no ZIP is produced",
        "build_id": BUILD_ID,
        "runtime_root": RUNTIME,
        "marker": "MU1320_F6_TRIAL=" + MARKER,
        "java_artifact_sha256": sha(jar),
        "java_changes_vs_f5_v5": "touchpad->DPAD bridge in the CarPlay lifecycle; StockDisplay helper path; CarPlayApp BUILD_ID",
        "native_and_renderer": "F5 v5 byte-identical: " + ", ".join(CARRIED),
        "scripts_derived_from": "F5 v5 templates + F6 v2 rename + touchpad status/collect; see reports/f6-v2-scripts.diff",
        "touchpad": {"log": TOUCH_LOG, "off_switch": TOUCH_OFF, "needs_arm": False},
        "host_test_log_sha256": sha(test_log),
        "vehicle_tested": False,
        "files": {name: sha(STAGE / name) for name in names + ["SHA256SUMS"]},
    }
    (BASE / "reports" / (REPORT + "-prepare.json")).write_text(json.dumps(report, indent=2) + "\n")
    print("Prepared", STAGE.name, "with", len(names) + 1, "files; no vehicle writes were performed.")


if __name__ == "__main__":
    main()
