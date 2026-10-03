#!/usr/bin/env python3
"""Prepare the F5 VC/HUD trial SD folder (copied to the SD card as is; no ZIP).

Vehicle mechanics = the F3 v2 package that passed on the car (same navhook
v1.2 hook, one-shot token, private DIO config, SI envs transaction, F1 v2
NavActiveIgnore quarantine) + the F4 renderer that passed on the car
(maneuver_render, flag atlas, dmdt stdout shim; byte-identical to the SD
folder of F4 run4).  The scripts are the F3 v2 templates (the ones that
produced the vehicle-run F3 v2 scripts) with an explicit F3->F5 rename table
and renderer hunks; reports/f5-vchud-v1-scripts.diff records the result
against the F3 v2 scripts that ran on the car.

New on the car: arm also starts the renderer from the runtime workspace and
declares context 80 natively (dmdt dc, as F4); disarm/rollback stop it and
put the cluster back on 74 if it was left on 80.  A reboot clears both.

v2: install also puts the context helper (f5_sc.sh + f5_dm.sh + f4_unbuf.so)
into the runtime render directory; the Java presenter runs it to switch the
cluster natively (stock Java rewrote switchContext(80) to 73 in the v1 car
run, reports/F5-V1-CTX-CALLERS.md).  arm proves the helper end to end
(read-only gs) before the token.

v3: dm() stops its watchdog with SIGKILL (helper children of the HMI JVM
ignore SIGTERM); the helper log drops the unsupported date +%s.

v4: Java only (raced takeovers retried, failures retried); scripts as v3.

v5: kdk is the default switch mode (ctx-mode file "native" selects native);
the helper returns at once on a definite read-back; FIGHT_STOP pauses instead
of stopping.
"""
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
import prepare_f3_trial as f3p  # noqa: E402  (VERSION 2: the vehicle-run F3 templates)

VERSION = 5
V = "v%d" % VERSION
BUILD_ID = "MU1320-F5-VCHUD-V%d" % VERSION
REPORT = "f5-vchud-" + V
STAGE = BASE / ("mu1320-f5-vchud-" + V)
JAR_NAME = "carplay_mu1320_f5_vchud_%s.jar.DISABLED" % V
RUNTIME = "/mnt/app/root/mu1320-rgi-f5-" + V
HOOK = RUNTIME + "/libcarplay_hook.so"
CONFIG_DIR = RUNTIME + "/config"
MARKER = "mu1320_f5_%s_" % V + hashlib.sha256(BUILD_ID.encode()).hexdigest()[:8]
LISTENER = BUILD_ID + " LISTENER_READY"
F3_STAGE = BASE / "mu1320-f3-bap-v2"
F4_STAGE = BASE / "mu1320-f4-render-v1"
RENDER_FILES = ["maneuver_render", "flag_atlas.rgba", "f4_unbuf.so"]
JAR_RUNTIME = "carplay_mu1320_f5_vchud_%s.jar" % V

sha = f3p.sha
crc = f3p.crc
replace_once = f3p.replace_once


def rename(text):
    """F3 v2 -> F5 names.  Native token/receipt names (navhook) are kept."""
    for old, new in [
        (f3p.MARKER, MARKER),
        (f3p.BUILD_ID, BUILD_ID),
        ("MU1320-F3-V2-VERBOSE", "MU1320-F5-%s-VERBOSE" % V.upper()),
        ("CarPlayRGI-MU1320-F3BapV2.jar", "CarPlayRGI-MU1320-F5Vchud%s.jar" % V.upper()),
        ("carplay_mu1320_f3_bap_v2", "carplay_mu1320_f5_vchud_" + V),
        ("mu1320-rgi-f3-v2", "mu1320-rgi-f5-" + V),
        ("mu1320-f3-v2", "mu1320-f5-" + V),
        ("/tmp/mu1320-f3-", "/tmp/mu1320-f5-"),
        ("collect_f3.sh", "collect_f5.sh"),
        ("f3_trial.sh", "f5_trial.sh"),
        ("MU1320_F3_TRIAL", "MU1320_F5_TRIAL"),
        (".mu1320-f3", ".mu1320-f5"),
        ("F3_BAP_INSTALLED", "F5_INSTALLED"),
        ("F3 BAP Java archive", "F5 Java archive"),
        ("Java F3 listener", "Java F5 listener"),
        ("F3 BAP", "F5"),
        ("F3_", "F5_"),
        ("F3 evidence", "F5 evidence"),
    ]:
        text = text.replace(old, new)
    assert not re.search(r"f3", text, re.I), re.findall(r".*f3.*", text, re.I)
    return text


def control_hunks(c):
    c = replace_once(c, """check @COLLECT_CRC@ @COLLECT_SIZE@ "$stage_dir/collect_f5.sh" || fail 'collector checksum'
""", """check @COLLECT_CRC@ @COLLECT_SIZE@ "$stage_dir/collect_f5.sh" || fail 'collector checksum'
check @DMH_CRC@ @DMH_SIZE@ "$stage_dir/f5_dm.sh" || fail 'displaymanager helper checksum'
check @UNBUF_CRC@ @UNBUF_SIZE@ "$stage_dir/f4_unbuf.so" || fail 'dmdt stdout shim checksum'
check 2992755173 34464 /mnt/app/eso/bin/apps/dmdt || fail 'dmdt baseline'
UNBUF=$stage_dir/f4_unbuf.so
# Query output goes to /tmp (flat files): the SD may be read-only when control.sh runs directly.
DMP="/tmp/mu1320-f5-dm-$action-$$"
. "$stage_dir/f5_dm.sh"
""")
    c = replace_once(c, """echo "BAP_KILL_SWITCH: $(exists /tmp/mu1320-f5-bap-off && echo PRESENT || echo ABSENT)"
""", """echo "BAP_KILL_SWITCH: $(exists /tmp/mu1320-f5-bap-off && echo PRESENT || echo ABSENT)"
echo "RENDER_OFF_SWITCH: $(exists /tmp/mu1320-f5-render-off && echo PRESENT || echo ABSENT)"
echo "CALIBRATION_SWITCH: $(exists /tmp/mu1320-f5-calib && echo PRESENT || echo ABSENT)"
echo "GEOMETRY_OVERRIDE: $(exists /tmp/mu1320-f5-geom.cfg && echo PRESENT || echo ABSENT)"
ctx_mode=kdk; ctx_word=''
if [ -f /tmp/mu1320-f5-ctx-mode ]; then read -r ctx_word < /tmp/mu1320-f5-ctx-mode || :; fi
case "$ctx_word" in native*) ctx_mode=native ;; esac
echo "CTX_MODE: $ctx_mode"
""")
    c = replace_once(c, """    old_si_ok "$ROOT/backup/smartphone_integrator.json" || fail 'SI backup checksum/attributes'
""", """    old_si_ok "$ROOT/backup/smartphone_integrator.json" || fail 'SI backup checksum/attributes'
    [ -d "$ROOT/render" ] && [ ! -L "$ROOT/render" ] || fail 'runtime render directory'
    check @RENDER_CRC@ @RENDER_SIZE@ "$ROOT/render/maneuver_render" || fail 'runtime renderer checksum'
    check @ATLAS_CRC@ @ATLAS_SIZE@ "$ROOT/render/flag_atlas.rgba" || fail 'runtime flag atlas checksum'
    check @SC_CRC@ @SC_SIZE@ "$ROOT/render/f5_sc.sh" || fail 'runtime context helper checksum'
    check @DMH_CRC@ @DMH_SIZE@ "$ROOT/render/f5_dm.sh" || fail 'runtime displaymanager helper checksum'
    check @UNBUF_CRC@ @UNBUF_SIZE@ "$ROOT/render/f4_unbuf.so" || fail 'runtime dmdt stdout shim checksum'
""")
    c = replace_once(c, """    command -v mv >/dev/null 2>&1 || fail 'missing mv'; disarm
""", """    command -v mv >/dev/null 2>&1 || fail 'missing mv'; disarm
    [ "$DISARM_CLUSTER_OK" = 1 ] || fail 'cluster not confirmed off context 80 (see WARNING); stop the trial and do a normal reboot, which clears context 80'
""")
    c = replace_once(c, """else
    disarm
""", """else
    disarm
    [ "$DISARM_CLUSTER_OK" = 1 ] || echo 'WARNING: cluster not confirmed off context 80; the full restart after rollback clears it'
""")
    c = replace_once(c, """if [ "$action" = status ]; then echo 'FILE_STATE_ONLY""", """if [ "$action" = status ]; then
    renderer_status
    if command -v pidin >/dev/null 2>&1; then dm_query; fi
    echo 'FILE_STATE_ONLY""")
    c = replace_once(c, """process evidence'; exit 0; fi
""", """process evidence'; exit 0
fi
""")
    c = replace_once(c, """        mv "$ARM" "$target" || fail 'disarm token move'
    fi
}
""", """        mv "$ARM" "$target" || fail 'disarm token move'
    fi
    render_disarm
}
""")
    c = replace_once(c, """    [ "$(token_status)" = ABSENT ] || fail 'arm token already exists or is unknown'
    if exists "$VERBOSE"; then fail 'pre-existing verbose marker; preserve it and reboot before this trial'; fi
""", """    [ "$(token_status)" = ABSENT ] || fail 'arm token already exists or is unknown'
    if exists "$VERBOSE"; then fail 'pre-existing verbose marker; preserve it and reboot before this trial'; fi
    # F5: renderer from the runtime workspace + context 80 declared natively.  Runtime only.
    render_arm
""")
    c = replace_once(c, """    echo 'ARMED_ONCE: Java listener was observed; connect USB once and start navigation'; exit 0""",
                     """    echo 'ARMED_ONCE: Java listener and renderer are up; context 80 declared; connect USB once and start navigation'; exit 0""")
    c = replace_once(c, """    for directory in "$ROOT" "$ROOT/backup" "$ROOT/config" "$ROOT/quarantine"; do\n""",
                     """    for directory in "$ROOT" "$ROOT/backup" "$ROOT/config" "$ROOT/quarantine" "$ROOT/render"; do\n""")
    jar = 'put_file "$stage_dir/%s" "$ROOT/%s" 644 @JAVA_CRC@ @JAVA_SIZE@ \'runtime Java payload\' plain\n' % (JAR_NAME, JAR_RUNTIME)
    c = replace_once(c, "    " + jar, "    " + jar + """    put_file "$stage_dir/maneuver_render" "$ROOT/render/maneuver_render" 755 @RENDER_CRC@ @RENDER_SIZE@ 'runtime renderer' plain
    put_file "$stage_dir/flag_atlas.rgba" "$ROOT/render/flag_atlas.rgba" 644 @ATLAS_CRC@ @ATLAS_SIZE@ 'runtime flag atlas' plain
    put_file "$stage_dir/f5_sc.sh" "$ROOT/render/f5_sc.sh" 755 @SC_CRC@ @SC_SIZE@ 'runtime context helper' plain
    put_file "$stage_dir/f5_dm.sh" "$ROOT/render/f5_dm.sh" 644 @DMH_CRC@ @DMH_SIZE@ 'runtime displaymanager helper' plain
    put_file "$stage_dir/f4_unbuf.so" "$ROOT/render/f4_unbuf.so" 644 @UNBUF_CRC@ @UNBUF_SIZE@ 'runtime dmdt stdout shim' plain
""")
    return c


def collector_hunks(col):
    col = replace_once(col, """    echo F5_FILES_BEGIN
    # The capture holds sanitized frame diffs (free text replaced by tokens); it is
    # copied for host replay, not printed.  State and BAP logs hold no road text.
    for f in /tmp/mu1320-f5-state.log /tmp/mu1320-f5-frames.cap /tmp/mu1320-f5-bap.log; do""",
                       """    echo F5_FILES_BEGIN
    # The capture holds sanitized frame diffs (free text replaced by tokens); it is
    # copied for host replay, not printed.  State, BAP and render logs hold no road text.
    for f in /tmp/mu1320-f5-state.log /tmp/mu1320-f5-frames.cap /tmp/mu1320-f5-bap.log /tmp/mu1320-f5-render.log /tmp/mu1320-f5-renderer.log /tmp/mu1320-f5-geom.cfg /tmp/mu1320-f5-sc.log /tmp/mu1320-f5-ctx-mode; do""")
    col = replace_once(col, """    for label in ' START ' ' TEARDOWN ' ' RELEASE_SILENT ' ' HOLD_OFF ' ' FAULT ' ' BIND ok' ' BIND fail' ' GATE ' ' CALL ' ' CALL DESCRIPTOR '; do""",
                       """    for label in ' START ' ' RESUME ' ' TEARDOWN ' ' RELEASE_SILENT ' ' HOLD_OFF ' ' FAULT ' ' BIND ok' ' BIND fail' ' GATE ' ' DEBOUNCE ' ' DEBOUNCE_FIRE' ' CALL ' ' CALL DESCRIPTOR ' ' CALL LANES n=' ' CALL ETA src=eta' ' CALL ETA src=rem' ' RCMD MAN ' ' RCMD CLEAR'; do""")
    col = replace_once(col, """    echo F5_BAP_EVENT_LINES_BEGIN
    if [ -f "$bap_log" ]; then grep -v -- ' CALL ' "$bap_log" | head -300 || :; fi
    echo F5_BAP_EVENT_LINES_END
    echo "F5_KILL_SWITCH: $( [ -e /tmp/mu1320-f5-bap-off ] && echo PRESENT || echo ABSENT )"
""", """    echo F5_BAP_EVENT_LINES_BEGIN
    if [ -f "$bap_log" ]; then grep -v -e ' CALL ' -e ' RCMD ' "$bap_log" | head -300 || :; fi
    echo F5_BAP_EVENT_LINES_END
    render_log=/tmp/mu1320-f5-render.log
    for label in ' TAKE ' ' RELEASE ' ' STOCK_RECLAIMED ' ' FIGHT_STOP' ' YIELD_VIEW ' ' WAIT_MAP ' ' GEOM ' ' GEOM_CONFIG' ' RENDERER ' ' RESEND ' ' GRID ' ' DISPLAY fail' ' TAKE_FAILED' ' VERIFY ' ' JAVA_CONFIRMED' ' KDK_REWRITE ' ' UNSTICK_73' ' BACKING_REASSERT' ' RELEASE_STRAY' ' MODE ' ' TAKE_RACED' ' RACE_RETRY' ' WAIT_RETRY' ' FIGHT_RESUME'; do
        n=0; if [ -f "$render_log" ]; then n=$(grep -c -- "$label" "$render_log" 2>/dev/null || :); fi
        echo "F5_RENDER_COUNT[$label]=${n:-0}"
    done
    echo F5_RENDER_LINES_BEGIN
    if [ -f "$render_log" ]; then head -300 "$render_log" || :; fi
    echo F5_RENDER_LINES_END
    echo "F5_KILL_SWITCH: $( [ -e /tmp/mu1320-f5-bap-off ] && echo PRESENT || echo ABSENT )"
    echo "F5_RENDER_OFF: $( [ -e /tmp/mu1320-f5-render-off ] && echo PRESENT || echo ABSENT )"
    echo "F5_CALIBRATION: $( [ -e /tmp/mu1320-f5-calib ] && echo PRESENT || echo ABSENT )"
    echo F5_DISPLAY_BEGIN
    renderer_status
    DMP="$logdir/dm"; dm_query
    echo F5_DISPLAY_END
""")
    col = replace_once(col, """    echo 'INTERPRETATION: F5 evidence = stable active DIO + ACTIVE_TOKEN_CONSUMED + BIND ok + START/TEARDOWN per route with zero FAULT; VC/HUD display is judged from OBSERVATIONS'
""", """    echo 'INTERPRETATION: F5 evidence = stable active DIO + ACTIVE_TOKEN_CONSUMED + BIND ok + START/TEARDOWN per route with zero FAULT + TAKE/RELEASE of context 80 per shown route; VC/HUD display is judged from photos and OBSERVATIONS'
""")
    col = replace_once(col, """umask 077; out="$sd_dir/out"; [ -d "$out" ] || mkdir "$out"; [ ! -L "$out" ] || exit 2
""", """umask 077; out="$sd_dir/out"; [ -d "$out" ] || mkdir "$out"; [ ! -L "$out" ] || exit 2
fail() { echo "STOP: $*"; exit 2; }
exists() { [ -e "$1" ] || [ -L "$1" ]; }
output=$(cksum "$sd_dir/f5_dm.sh"); set -- $output; [ "${1:-}" = '@DMH_CRC@' ] && [ "${2:-}" = '@DMH_SIZE@' ] || fail 'displaymanager helper checksum'
output=$(cksum "$sd_dir/f4_unbuf.so"); set -- $output; [ "${1:-}" = '@UNBUF_CRC@' ] && [ "${2:-}" = '@UNBUF_SIZE@' ] || fail 'dmdt stdout shim checksum'
UNBUF=$sd_dir/f4_unbuf.so; DMP=/tmp/mu1320-f5-dm-collect-$$
. "$sd_dir/f5_dm.sh"
""")
    return col


def main():
    build = json.loads((BASE / "reports" / (REPORT + "-build.json")).read_text())
    audit = json.loads((BASE / "reports" / (REPORT + "-audit.json")).read_text())
    f3_prepare = json.loads((BASE / "reports/f3-bap-v2-prepare.json").read_text())
    assert audit["status"] == "PASS"
    jar = STAGE / JAR_NAME
    assert sha(jar) == build["jar_sha256"]
    assert sorted(path.name for path in STAGE.iterdir()) == [jar.name], "stage must hold only the new JAR"

    # SI/DIO: the F3 v2 transformation with the F5 runtime path and marker.
    f3_si = (F3_STAGE / "smartphone_integrator.json").read_text()
    si = f3_si.replace("mu1320-rgi-f3-v2", "mu1320-rgi-f5-" + V).replace(
        "MU1320_F3_TRIAL=" + f3p.MARKER, "MU1320_F5_TRIAL=" + MARKER)
    assert si.count(RUNTIME) == 2 and si.count(MARKER) == 1
    assert "mu1320-rgi-f3" not in si and "MU1320_F3_TRIAL" not in si
    (STAGE / "smartphone_integrator.json").write_text(si)
    shutil.copyfile(F3_STAGE / "dio_manager.json", STAGE / "dio_manager.json")
    (STAGE / "IDENTITY").write_text(BUILD_ID + "\n")
    shutil.copyfile(F3_STAGE / "ARM-TOKEN", STAGE / "ARM-TOKEN")

    # Native pieces: byte-identical to the vehicle-run F3 v2 and F4 run4 folders.
    for name in ["libcarplay_hook.so", "loader_check", "loader_check.c", "mount_state",
                 "mount_state.c", "trial_gate.c", "trial_gate.h", "dio_manager.json", "ARM-TOKEN"]:
        if not (STAGE / name).exists():
            shutil.copyfile(F3_STAGE / name, STAGE / name)
        assert sha(STAGE / name) == f3_prepare["files"][name], name
    f4_sums = dict(reversed(line.split("  ", 1)) for line in (F4_STAGE / "SHA256SUMS").read_text().splitlines())
    for name in RENDER_FILES:
        shutil.copyfile(F4_STAGE / name, STAGE / name)
        assert sha(STAGE / name) == f4_sums[name] == sha(F4_STAGE / name), name
    assert sha(STAGE / "mount_state") == f4_sums["mount_state"], "mount helper shared with F4"
    for name in ["loader_check", "mount_state", "maneuver_render"]:
        (STAGE / name).chmod(0o755)
    shutil.copyfile(BASE / "f5-src/README.md", STAGE / "README.md")
    shutil.copyfile(BASE / "f5-src/OBSERVATIONS-TEMPLATE.txt", STAGE / "OBSERVATIONS-TEMPLATE.txt")
    shutil.copyfile(BASE / "f5-src/geom-example.cfg", STAGE / "geom-example.cfg")

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

    # The same pinned stock baselines the F3 v2 control checks (read from its rendered script).
    f3_control = (F3_STAGE / "control.sh").read_text()
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

    control_t, collector_t, sd_t = f3p.derive_templates()
    control_t = control_hunks(rename(control_t))
    collector_t = collector_hunks(rename(collector_t))
    sd_t = rename(sd_t)
    helper_t = (BASE / "scripts/f5_dm.sh.in").read_text()

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
    render((BASE / "scripts/f5_sc.sh.in").read_text(), "f5_sc.sh")
    pin("SC", STAGE / "f5_sc.sh")
    (STAGE / "f5_sc.sh").chmod(0o755)
    render(collector_t, "collect_f5.sh")
    pin("COLLECT", STAGE / "collect_f5.sh")
    control = render(control_t, "control.sh")
    pin("CONTROL", STAGE / "control.sh")
    render(sd_t, "f5_trial.sh")
    for name in ["control.sh", "collect_f5.sh", "f5_trial.sh", "f5_dm.sh", "f5_sc.sh"]:
        text = (STAGE / name).read_text()
        assert not re.search(r"exists [^\n;]*&&\s*fail", text), name
        assert "dmdt ts" not in text.replace('"dmdt ts"', ""), name
        assert not re.search(r'\bdm [^\n]*\bts\b', text), name
    assert LISTENER in control and RUNTIME in control

    # Audit trail: rendered F5 scripts versus the F3 v2 scripts that ran on the car.
    import difflib
    diffs = []
    for old, new in [("control.sh", "control.sh"), ("collect_f3.sh", "collect_f5.sh"), ("f3_trial.sh", "f5_trial.sh")]:
        diffs += difflib.unified_diff(
            (F3_STAGE / old).read_text().splitlines(True), (STAGE / new).read_text().splitlines(True),
            fromfile=F3_STAGE.name + "/" + old, tofile=STAGE.name + "/" + new)
    (BASE / "reports" / (REPORT + "-scripts.diff")).write_text("".join(diffs))

    tests = subprocess.run(
        [sys.executable, "-m", "unittest", "test_navjava_trial.py", "test_f2_trial.py", "test_f3_trial.py",
         "test_f4_trial.py", "test_f5_trial.py", "-v"],
        cwd=BASE / "tests", env=dict(os.environ, PYTHONPATH=str(BASE / "tests")),
        capture_output=True, text=True)
    test_log = BASE / "reports" / (REPORT + "-host-tests.txt")
    test_log.write_text(tests.stdout + tests.stderr)
    assert tests.returncode == 0, tests.stdout[-4000:] + tests.stderr[-8000:]

    names = sorted(path.name for path in STAGE.iterdir() if path.is_file() and path.name != "SHA256SUMS")
    (STAGE / "SHA256SUMS").write_text("".join(f"{sha(STAGE / name)}  {name}\n" for name in names))
    report = {
        "version": VERSION,
        "sd_folder": STAGE.name,
        "delivery": "copy the folder to the SD root; no ZIP is produced",
        "runtime_root": RUNTIME,
        "marker": "MU1320_F5_TRIAL=" + MARKER,
        "native_hook_sha256": sha(STAGE / "libcarplay_hook.so"),
        "native_hook_is_vehicle_verified_v1_2": True,
        "renderer_sha256": sha(STAGE / "maneuver_render"),
        "renderer_is_f4_run4_binary": True,
        "java_artifact_sha256": sha(jar),
        "java_scope": build["cluster"],
        "bap_fctids": build["bap_fctids"],
        "nav_active_ignore": "quarantined to the private workspace on install (F1 v2), restored on rollback",
        "arm_runtime_changes": "starts maneuver_render from the runtime workspace; dmdt dc 80 98 102 101 33; checks the installed context helper with a read-only gs",
        "context_helper": "render/f5_sc.sh (+ f5_dm.sh, f4_unbuf.so) in the runtime workspace, run by Java",
        "scripts_derived_from": "F3 v2 templates + rename + renderer hunks; see reports/" + REPORT + "-scripts.diff",
        "host_test_log_sha256": sha(test_log),
        "vehicle_tested": False,
        "files": {name: sha(STAGE / name) for name in names + ["SHA256SUMS"]},
    }
    (BASE / "reports" / (REPORT + "-prepare.json")).write_text(json.dumps(report, indent=2) + "\n")
    print("Prepared", STAGE.name, "with", len(names) + 1, "files; no vehicle writes were performed.")


if __name__ == "__main__":
    main()
