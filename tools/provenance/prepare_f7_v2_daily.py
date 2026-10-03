#!/usr/bin/env python3
"""Prepare the F7 v2 SD folder (copied to the SD card as is; no ZIP).

F7 v2 = F7 v1.1 (car session P passed, closed 2026-09-27) + two fixes + the
green-menu entry:

  B11  native: the gate writes gate.last / gate.strikes in place (no rename on
       /dev/shmem); scripts/build_f7_v2_native.py.
  B12  scripts: stop / rollback switch BAP off through the running Java first
       (the car-proven runtime kill switch /tmp/mu1320-f5-bap-off: BAP teardown
       -> VC/HUD stock, presenter releases context 80 and gives the KDK back),
       wait for Java's "GATE kill=1" and for displaymanager to leave 80, then
       stop the renderer.  v1.1 stopped only the renderer, so the still-active
       BAP output kept the arrow on VC/HUD until USB was unplugged (P7).
  ENV  f7.sh / control.sh drop relative LD_LIBRARY_PATH entries, cd / and
       umask 022: green-menu scripts start with "." first in PATH and
       LD_LIBRARY_PATH, umask 000, cwd /mnt/app/eso (Toolbox v0 on the car).
  MENU TOOLBOX-ENTRY marks this folder for the Toolbox v1 dispatcher.

Java is the v1.1 bytecode with version names only (scripts/build_f7_v2_java.py
runs first; the JAR is already in the folder).  Everything else is renamed
from the v1.1 folder and re-pinned; reports/f7-v2-scripts.diff is the full
result against v1.1.  Carried byte for byte from v1.1: loader_check(.c),
mount_state(.c), dio_manager.json, maneuver_render, flag_atlas.rgba,
f4_unbuf.so, geom-example.cfg, f7_spawn(.c), trial_gate.h.
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
V11 = BASE / "mu1320-f7-daily-v1.1"
STAGE = BASE / "mu1320-f7-daily-v2"
SRC = BASE / "f7-v2-src"
BUILD_ID = "MU1320-F7-DAILY-V2"
RUNTIME = "mu1320-rgi-f7-v2"
JAR_NAME = "carplay_mu1320_f7_daily_v2.jar.DISABLED"
NEW_JAR = "CarPlayRGI-MU1320-F7DailyV2.jar"
MARKER = "mu1320_f7_v2_" + hashlib.sha256(BUILD_ID.encode()).hexdigest()[:8]
V11_MARKER = "mu1320_f7_v1_1_30175784"
CARRIED = ["loader_check", "loader_check.c", "mount_state", "mount_state.c", "dio_manager.json", "maneuver_render",
           "flag_atlas.rgba", "f4_unbuf.so", "geom-example.cfg", "f7_spawn", "f7_spawn.c", "trial_gate.h"]
SCRIPTS = ["control.sh", "collect_f7.sh", "f7.sh", "f7_render.sh", "f5_sc.sh", "f5_dm.sh", "f7_mark.sh"]
EXEC = ["loader_check", "mount_state", "maneuver_render", "f7_spawn", "f5_sc.sh", "f7_render.sh", "f7_mark.sh"]
TESTS = ["test_f7_gate.py", "test_f7_trial.py", "test_f7_v11_native.py", "test_f7_v11_trial.py", "test_f7_mark.py",
         "test_f7_v2_native.py", "test_f7_v2_trial.py", "test_toolbox_v1.py"]
USER_FILLED = {"OBSERVATIONS-F7.txt"}
ENTRY = "MU1320_F7_TOOLBOX_ENTRY 1\nbuild=%s\nwrapper=f7.sh\n" % BUILD_ID

# ---- behavioural hunks (applied to the renamed v1.1 text; each must match once) ----
ENV_ANCHOR = 'stage_dir=$(CDPATH= cd "$stage_dir" && pwd -P)\n'
ENV_BLOCK = ENV_ANCHOR + '''# F7 v2: green-menu scripts start with "." first in PATH and LD_LIBRARY_PATH, umask 000 and
# cwd /mnt/app/eso (Toolbox v0 on the car).  PATH is fixed above; relative library
# directories are dropped; the stage directory is resolved before leaving the cwd.
cd / || exit 2
umask 022
ld_keep=''; ld_ifs=$IFS; IFS=:; set -f
for ld_dir in ${LD_LIBRARY_PATH:-}; do case "$ld_dir" in /*) ld_keep=${ld_keep:+$ld_keep:}$ld_dir ;; esac; done
set +f; IFS=$ld_ifs
if [ -n "$ld_keep" ]; then LD_LIBRARY_PATH=$ld_keep; export LD_LIBRARY_PATH; else unset LD_LIBRARY_PATH || :; fi
'''
STATUS_ANCHOR = 'echo "MOUNTS: app=$app_state system=$system_state"\n'
STATUS_BLOCK = STATUS_ANCHOR + 'echo "RUN_ENV: cwd=$(pwd) umask=$(umask) ld=${LD_LIBRARY_PATH:-unset}"\n'
STOP_OLD = '''# stop and rollback: hold the renderer (the Java keeper answers HELD, no restart)
# and keep the next DIO passive, both until the next reboot; then stop the
# renderer and put a cluster left on context 80 back on 74.
stop_runtime() {
    : > "$HOLD" || fail 'render hold create'
    : > "$NATIVE_OFF" || fail 'native runtime off create'
    render_disarm
}
'''
STOP_NEW = '''# stop and rollback: hold the renderer (the Java keeper answers HELD, no restart)
# and keep the next DIO passive, both until the next reboot.  F7 v2 (BACKLOG B12,
# v1.1 car session P7: VC/HUD kept the arrow after stop until USB was unplugged,
# because BAP output went on): first switch BAP off through the running Java with
# the runtime kill switch (BAP teardown puts VC/HUD back to stock and the
# presenter releases context 80 and gives the KDK back), wait until Java logged
# it and displaymanager left 80, and only then stop the renderer.  A cluster
# still on 80 is put back on 74 natively, as before.
BAP_KILL=/tmp/mu1320-f5-bap-off
BAP_LOG=/tmp/mu1320-f5-bap.log
count_matches() {
    cm_n=0
    if [ -f "$2" ]; then
        grep "$1" "$2" > "$DMP-count.txt" 2>/dev/null || :
        while read -r cm_line || [ -n "$cm_line" ]; do cm_n=$((cm_n + 1)); done < "$DMP-count.txt"
        rm -f "$DMP-count.txt" || :
    fi
    echo "$cm_n"
}
java_release() {
    JAVA_RELEASE=NO_JAVA
    kills_before=$(count_matches 'GATE kill=1' "$BAP_LOG")
    kill_was=0; if exists "$BAP_KILL"; then kill_was=1; fi
    : > "$BAP_KILL" || fail 'BAP runtime kill switch create'
    if [ "$kill_was" = 1 ]; then JAVA_RELEASE=ALREADY_OFF
    elif [ -f "$JAVA_LOG" ] && grep 'MU1320-F7-DAILY-V2 LISTENER_READY' "$JAVA_LOG" >/dev/null 2>&1; then
        JAVA_RELEASE=NO_ACK; n=0
        while [ "$n" -lt 10 ]; do
            sleep 1; n=$((n + 1))
            if [ "$(count_matches 'GATE kill=1' "$BAP_LOG")" -gt "$kills_before" ]; then JAVA_RELEASE=BAP_OFF; break; fi
        done
    fi
    echo "JAVA_RELEASE: $JAVA_RELEASE"
    case "$JAVA_RELEASE" in BAP_OFF|ALREADY_OFF) ;; *) return 0 ;; esac
    n=0
    while :; do
        dm "$DMP-gs-release.txt" gs || :; parse_gs "$DMP-gs-release.txt"
        if [ "$CL_CTX" != "$CTX" ] || [ "$n" -ge 8 ]; then break; fi
        sleep 1; n=$((n + 1))
    done
    echo "JAVA_CLUSTER_CONTEXT: ${CL_CTX:-UNKNOWN} waited=${n}s"
    sleep 1
}
stop_runtime() {
    : > "$HOLD" || fail 'render hold create'
    : > "$NATIVE_OFF" || fail 'native runtime off create'
    java_release
    render_disarm
}
'''
STOPPED_OLD = ("echo 'F7_STOPPED: renderer stopped and held, next DIO passive, until the next reboot; "
               "an already-active DIO stays active until USB is disconnected'; exit 0")
STOPPED_NEW = ("echo 'F7_STOPPED: BAP off (VC/HUD stock), renderer stopped and held, next DIO passive, "
               "until the next reboot; touchpad unchanged'; exit 0")
HUNKS = {
    "control.sh": [(ENV_ANCHOR, ENV_BLOCK), (STATUS_ANCHOR, STATUS_BLOCK), (STOP_OLD, STOP_NEW),
                   (STOPPED_OLD, STOPPED_NEW)],
    "f7.sh": [(ENV_ANCHOR, ENV_BLOCK)],
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def crc(path):
    out = subprocess.check_output(["cksum", str(path)], text=True).split()
    return out[0], out[1]


def rename(text):
    text = text.replace(V11_MARKER, MARKER)
    text = text.replace("CarPlayRGI-MU1320-F7DailyV1_1.jar", NEW_JAR)
    text = text.replace("carplay_mu1320_f7_daily_v1_1.jar", JAR_NAME.replace(".DISABLED", ""))
    for old, new in [("MU1320-F7-DAILY-V1.1", BUILD_ID), ("mu1320-rgi-f7-v1.1", RUNTIME),
                     ("mu1320-f7-daily-v1.1", "mu1320-f7-daily-v2")]:
        text = re.sub(re.escape(old) + r"(?![\w.])", new, text)
    left = re.findall(r"mu1320-rgi-f7-v1|MU1320-F7-DAILY-V1|mu1320-f7-daily-v1|daily_v1|F7DailyV1|" + V11_MARKER, text)
    assert not left, left
    return text


def patch(name, text):
    for old, new in HUNKS.get(name, []):
        assert text.count(old) == 1, (name, old[:60])
        text = text.replace(old, new, 1)
    return text


def repin(text, pins):
    for old, new in pins:
        if old != new:
            text = text.replace("%s %s" % old, "%s %s" % new)
            text = text.replace("'%s' ] && [ \"${2:-}\" = '%s'" % old, "'%s' ] && [ \"${2:-}\" = '%s'" % new)
    return text


def main():
    java = json.loads((BASE / "reports/f7-v2-build.json").read_text())
    audit = json.loads((BASE / "reports/f7-v2-audit.json").read_text())
    native = json.loads((BASE / "reports/f7-v2-native-build.json").read_text())
    v11prep = json.loads((BASE / "reports/f7-v1.1-prepare.json").read_text())
    assert audit["status"] == "PASS"
    jar = STAGE / JAR_NAME
    assert sha(jar) == java["jar_sha256"]
    for name, digest in v11prep["files"].items():  # the car-run v1.1 folder is untouched
        if name in USER_FILLED:  # the observation sheet is filled in by the user in place
            continue
        assert sha(V11 / name) == digest, "F7 v1.1 folder changed: " + name
    present = sorted(p.name for p in STAGE.iterdir())
    if present != [jar.name]:
        assert not (STAGE / "out").exists(), "refusing to touch a stage folder that holds vehicle results"
        for p in STAGE.iterdir():
            if p.name != jar.name:
                p.unlink()

    for name in CARRIED:
        shutil.copyfile(V11 / name, STAGE / name)
    nat = BASE.parent / "private-data/mu1320-rgi/f7-daily-v2-native"
    shutil.copyfile(nat / "libcarplay_hook.so", STAGE / "libcarplay_hook.so")
    assert sha(STAGE / "libcarplay_hook.so") == native["artifacts"]["libcarplay_hook.so"]["sha256"]
    assert sha(STAGE / "f7_spawn") == native["artifacts"]["f7_spawn"]["sha256"]
    for name in ["trial_gate.c", "README.md", "OBSERVATIONS-F7.txt"]:
        shutil.copyfile(SRC / name, STAGE / name)
    (STAGE / "IDENTITY").write_text(BUILD_ID + "\n")
    (STAGE / "TOOLBOX-ENTRY").write_text(ENTRY)
    si = rename((V11 / "smartphone_integrator.json").read_text())
    assert si.count(RUNTIME) == 2 and si.count(MARKER) == 1 and "MU1320_F7_TRIAL=" + MARKER in si, "SI rename"
    (STAGE / "smartphone_integrator.json").write_text(si)

    # Pins: payloads first, then each script in the order it is pinned by the next.
    changed = [(crc(V11 / a), crc(STAGE / b)) for a, b in [
        ("IDENTITY", "IDENTITY"), ("libcarplay_hook.so", "libcarplay_hook.so"),
        ("carplay_mu1320_f7_daily_v1_1.jar.DISABLED", JAR_NAME), ("smartphone_integrator.json", "smartphone_integrator.json"),
        ("trial_gate.c", "trial_gate.c")]]
    for name in ["f5_sc.sh", "f5_dm.sh", "f7_render.sh", "collect_f7.sh", "control.sh", "f7.sh", "f7_mark.sh"]:
        (STAGE / name).write_text(repin(patch(name, rename((V11 / name).read_text())), changed))
        changed.append((crc(V11 / name), crc(STAGE / name)))
    for name in EXEC:
        (STAGE / name).chmod(0o755)

    # The keeper equals a fresh rendering of its template with the v2 values.
    keeper = (BASE / "f7-src/f7_render.sh.in").read_text()
    values = {"RUNTIME": "/mnt/app/root/" + RUNTIME, "JAR": NEW_JAR}
    for label, name in [("RENDER", "maneuver_render"), ("ATLAS", "flag_atlas.rgba"), ("DMH", "f5_dm.sh"),
                        ("UNBUF", "f4_unbuf.so"), ("SPAWN", "f7_spawn")]:
        values[label + "_CRC"], values[label + "_SIZE"] = crc(STAGE / name)
    for key, value in values.items():
        keeper = keeper.replace("@" + key + "@", value)
    assert keeper == (STAGE / "f7_render.sh").read_text(), "keeper differs from its template"

    stale = {"%s %s" % old for old, new in changed if old != new}
    for name in SCRIPTS:
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

    # Only the reviewed hunks differ from a plain rename of v1.1.
    for name in SCRIPTS:
        plain = repin(rename((V11 / name).read_text()), changed)
        expect = repin(patch(name, rename((V11 / name).read_text())), changed)
        assert (STAGE / name).read_text() == expect
        assert (plain != expect) == (name in HUNKS), name

    diffs = []
    for name in SCRIPTS + ["smartphone_integrator.json", "IDENTITY", "trial_gate.c", "README.md", "OBSERVATIONS-F7.txt"]:
        diffs += difflib.unified_diff((V11 / name).read_text().splitlines(True), (STAGE / name).read_text().splitlines(True),
                                      fromfile=V11.name + "/" + name, tofile=STAGE.name + "/" + name)
    (BASE / "reports/f7-v2-scripts.diff").write_text("".join(diffs))

    names = sorted(p.name for p in STAGE.iterdir() if p.is_file() and p.name != "SHA256SUMS")
    (STAGE / "SHA256SUMS").write_text("".join("%s  %s\n" % (sha(STAGE / n), n) for n in names))

    tests = subprocess.run([sys.executable, "-m", "unittest"] + TESTS + ["-v"],
                           cwd=BASE / "tests", env=dict(os.environ, PYTHONPATH=str(BASE / "tests")),
                           capture_output=True, text=True)
    log = BASE / "reports/f7-v2-host-tests.txt"
    log.write_text(tests.stdout + tests.stderr)
    assert tests.returncode == 0, tests.stdout[-4000:] + tests.stderr[-8000:]

    report = {
        "sd_folder": STAGE.name, "delivery": "copy the folder to the SD root; no ZIP is produced",
        "build_id": BUILD_ID, "runtime_root": "/mnt/app/root/" + RUNTIME, "marker": "MU1320_F7_TRIAL=" + MARKER,
        "java_artifact_sha256": sha(jar), "hook_sha256": sha(STAGE / "libcarplay_hook.so"),
        "carried_from_f7_v1_1": CARRIED,
        "behavioural_hunks": {k: len(v) for k, v in HUNKS.items()},
        "scripts_derived_from": "F7 v1.1 scripts renamed, patched (B12, env) and re-pinned; see reports/f7-v2-scripts.diff",
        "toolbox_entry": ENTRY,
        "host_tests": TESTS, "host_test_log_sha256": sha(log), "vehicle_tested": False,
        "files": {n: sha(STAGE / n) for n in names + ["SHA256SUMS"]},
    }
    (BASE / "reports/f7-v2-prepare.json").write_text(json.dumps(report, indent=2) + "\n")
    print("Prepared", STAGE.name, "with", len(names) + 1, "files; no vehicle writes were performed.")


if __name__ == "__main__":
    main()
