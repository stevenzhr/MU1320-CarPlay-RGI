#!/usr/bin/env python3
"""Prepare the F7 v1 SD folder (copied to the SD card as is; no ZIP).

F7 v1 = F6 v2 (car-run) with the manual "arm" replaced by an automatic
lifecycle.  scripts/build_f7_java.py and scripts/build_f7_native.py run
first; this script adds everything else to mu1320-f7-daily-v1/.

Scripts are derived from the F6 v2 files that ran on the car, not rewritten:
the text is renamed (workspace, JAR, marker, F6 -> F7 labels), every changed
payload checksum is re-pinned, and each behavioural change is one explicit
hunk below.  reports/f7-v1-scripts.diff is the full result against F6 v2.

- control.sh: arm/disarm/token removed; new "stop" (runtime hold until
  reboot), "off|on <native|render|bap|touchpad>" (persistent switch files in
  the workspace), "purge" (remove a rolled-back workspace after the reboot);
  rollback holds the renderer before stopping it; install adds f7_spawn and
  f7_render.sh to the workspace; status shows the switches and gate state.
- collect_f7.sh: phases live|restored|snapshot, F7 gate receipts and records,
  keeper log and counts, switch states.
- f7.sh: SD wrapper for the new action set.
- f5_dm.sh / f5_sc.sh: F6 v2 helpers with the F7 workspace path.
- f7_render.sh: new keeper script (f7-src/f7_render.sh.in).
Native hook, loader_check, mount_state, renderer, atlas, dmdt shim and
dio_manager.json are carried; only the hook is new (F7 gate).
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
ROOT = BASE.parent
PRIVATE = ROOT / "private-data/mu1320-rgi"
RESOURCE = ROOT / "resource"
F6 = BASE / "mu1320-f6-accept-v2"
STAGE = BASE / "mu1320-f7-daily-v1"
SRC = BASE / "f7-src"
BUILD_ID = "MU1320-F7-DAILY-V1"
RUNTIME = "/mnt/app/root/mu1320-rgi-f7-v1"
JAR_NAME = "carplay_mu1320_f7_daily_v1.jar.DISABLED"
NEW_JAR = "CarPlayRGI-MU1320-F7DailyV1.jar"
MARKER = "mu1320_f7_v1_" + hashlib.sha256(BUILD_ID.encode()).hexdigest()[:8]
F6_MARKER = "mu1320_f6_v2_cb925ff9"
CARRIED = ["loader_check", "loader_check.c", "mount_state", "mount_state.c", "dio_manager.json",
           "maneuver_render", "flag_atlas.rgba", "f4_unbuf.so", "geom-example.cfg"]
# Names the navigation/touchpad bytecode uses (unchanged since F5 v5 / F6 v2).
JAVA_BOUND = ["/tmp/mu1320-f5-", "/tmp/mu1320-f6-touchpad", "f5_sc.sh", "f5_dm.sh", "F5-V1-CTX-CALLERS",
              "MU1320-F5-VCHUD-V5"]
COMPONENTS = ["native", "render", "bap", "touchpad"]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def crc(path):
    out = subprocess.check_output(["cksum", str(path)], text=True).split()
    return out[0], out[1]


def once(text, old, new):
    assert text.count(old) == 1, (text.count(old), old)
    return text.replace(old, new, 1)


def rename(text):
    for old, new in [
        (F6_MARKER, MARKER),
        ("MU1320-F6-ACCEPT-V2", BUILD_ID),
        ("CarPlayRGI-MU1320-F6AcceptV2.jar", NEW_JAR),
        ("carplay_mu1320_f6_accept_v2", "carplay_mu1320_f7_daily_v1"),
        ("mu1320-rgi-f6-v2", "mu1320-rgi-f7-v1"),
        ("mu1320-f6-v2", "mu1320-f7-v1"),
    ]:
        text = text.replace(old, new)
    keep = {}
    for i, name in enumerate(JAVA_BOUND):
        token = "\0KEEP%d\0" % i
        keep[token] = name
        text = text.replace(name, token)
    for old, new in [("collect_f6.sh", "collect_f7.sh"), ("f6_trial.sh", "f7.sh"), (".mu1320-f6", ".mu1320-f7"),
                     ("F6_TRIAL_ACTION_PASSED", "F7_ACTION_PASSED"), ("F6", "F7")]:
        text = text.replace(old, new)
    for token, name in keep.items():
        text = text.replace(token, name)
    left = [l for l in text.splitlines() if re.search(r"f6|accept[-_]?v2", l, re.I) and not any(n in l for n in JAVA_BOUND)]
    assert not left, left
    return text


def repin(text, pins):
    for old, new in pins:
        if old != new:
            text = text.replace("%s %s" % old, "%s %s" % new)
            text = text.replace("'%s' ] && [ \"${2:-}\" = '%s'" % old, "'%s' ] && [ \"${2:-}\" = '%s'" % new)
    return text


def control_hunks(c, pins):
    c = once(c, """case "$action:$#" in status:1|install:1|arm:1|disarm:1|rollback:1|collect:2) ;; *) exit 2 ;; esac
case "$phase" in armed|restored|snapshot) ;; *) exit 2 ;; esac
""", """component=''
case "$action:$#" in status:1|install:1|stop:1|rollback:1|purge:1|collect:2) ;; off:2|on:2) component=$2; phase=snapshot ;; *) exit 2 ;; esac
case "$phase" in live|restored|snapshot) ;; *) exit 2 ;; esac
case "$component" in ''|native|render|bap|touchpad) ;; *) exit 2 ;; esac
""")
    c = once(c, "ARM=/tmp/mu1320-navhook-v1.arm\nVERBOSE=/tmp/carplay_verbose\n",
             "# F7: no arm token.  Runtime holds (until reboot) written by stop/rollback:\n"
             "HOLD=/tmp/mu1320-f7-render-hold\nNATIVE_OFF=/tmp/mu1320-f7-native-off\n")
    c = re.sub(r"token_status\(\) \{[^\n]*\n", "", c, count=1)
    c = once(c, 'echo "TOKEN: $(token_status)"; echo "MOUNTS: app=$app_state system=$system_state"\n',
             'echo "MOUNTS: app=$app_state system=$system_state"\n'
             '# Persistent component switches (files in the workspace; control.sh off|on <component>).\n'
             'for component_name in native render bap touchpad; do\n'
             '    if exists "$ROOT/off-$component_name"; then echo "SWITCH_$component_name: OFF_PERSISTENT"; else echo "SWITCH_$component_name: on"; fi\n'
             'done\n'
             'echo "NATIVE_RUNTIME_OFF: $(exists "$NATIVE_OFF" && echo PRESENT || echo ABSENT)"\n'
             'echo "RENDER_HOLD: $(exists "$HOLD" && echo PRESENT || echo ABSENT)"\n'
             'gate_word() { word=ABSENT; if [ -f "$1" ]; then word=; read -r word < "$1" || :; fi; echo "${word:-EMPTY}"; }\n'
             'echo "GATE_LAST: $(gate_word /tmp/mu1320-f7-gate.last)"; echo "GATE_STRIKES: $(gate_word /tmp/mu1320-f7-gate.strikes)"\n'
             'if [ -f "$JAVA_LOG" ] && grep \'MU1320-F7-DAILY-V1 LISTENER_READY\' "$JAVA_LOG" >/dev/null 2>&1; then echo \'JAVA_LISTENER: F7_READY\'; else echo \'JAVA_LISTENER: ABSENT\'; fi\n'
             'keeper_last=NONE; if [ -f /tmp/mu1320-f7-keeper.log ]; then while read -r keeper_line; do case "$keeper_line" in \'KEEP \'*) keeper_last=$keeper_line ;; esac; done < /tmp/mu1320-f7-keeper.log; fi\n'
             'echo "KEEPER_LAST: $keeper_last"\n')
    spawn, render = pins["SPAWN"], pins["KEEPER"]
    c = once(c, """    check 1988489462 5403 "$ROOT/render/f4_unbuf.so" || fail 'runtime dmdt stdout shim checksum'
""", """    check 1988489462 5403 "$ROOT/render/f4_unbuf.so" || fail 'runtime dmdt stdout shim checksum'
    check %s %s "$ROOT/render/f7_spawn" || fail 'runtime renderer launcher checksum'
    check %s %s "$ROOT/render/f7_render.sh" || fail 'runtime renderer keeper checksum'
""" % (spawn + render))
    start = c.index("disarm() {\n")
    end = c.index("for utility in cp cmp mv chmod mkdir sync mount find rm; do")
    c = c[:start] + """# stop and rollback: hold the renderer (the Java keeper answers HELD, no restart)
# and keep the next DIO passive, both until the next reboot; then stop the
# renderer and put a cluster left on context 80 back on 74.
stop_runtime() {
    : > "$HOLD" || fail 'render hold create'
    : > "$NATIVE_OFF" || fail 'native runtime off create'
    render_disarm
}
if [ "$action" = stop ]; then
    stop_runtime
    [ "$DISARM_CLUSTER_OK" = 1 ] || fail 'cluster not confirmed off context 80 (see WARNING); do a normal reboot, which clears context 80'
    echo 'F7_STOPPED: renderer stopped and held, next DIO passive, until the next reboot; an already-active DIO stays active until USB is disconnected'; exit 0
fi
switch_note() { case "$1" in native) echo 'from the next DIO start (USB connect)' ;; *) echo 'within 2 s, no restart' ;; esac; }
""" + c[end:]
    c = once(c, "    [ \"$(token_status)\" = ABSENT ] || fail 'arm token must be absent'\n", "")
    c = re.sub(r'    check \d+ \d+ "\$stage_dir/ARM-TOKEN" \|\| fail "ARM-TOKEN payload checksum"\n', "", c, count=1)
    c = once(c, '    check %s %s "$stage_dir/f5_sc.sh" || fail "f5_sc.sh payload checksum"\n' % pins["SC"],
             '    check %s %s "$stage_dir/f5_sc.sh" || fail "f5_sc.sh payload checksum"\n'
             '    check %s %s "$stage_dir/f7_spawn" || fail "f7_spawn payload checksum"\n'
             '    check %s %s "$stage_dir/f7_render.sh" || fail "f7_render.sh payload checksum"\n'
             % (pins["SC"] + spawn + render))
    c = once(c, "else\n    disarm\n    [ \"$DISARM_CLUSTER_OK\" = 1 ] || echo",
             """elif [ "$action" = off ] || [ "$action" = on ]; then
    runtime_ok
    java_ok "$NEW" || fail 'F7 is not installed; switches belong to an installation'
elif [ "$action" = purge ]; then
    [ -d "$ROOT" ] && [ ! -L "$ROOT" ] || fail 'no runtime workspace to purge'
    [ "$(dir_attrs "$ROOT")" = 'drwx------ 0 0' ] || fail 'runtime root attributes; preserve it'
    install_phase=''; if [ -f "$ROOT/phase.txt" ]; then read -r install_phase < "$ROOT/phase.txt" || :; fi
    [ "$install_phase" = INSTALLATION_BASELINE_RESTORED ] || fail "purge needs a completed rollback (phase=${install_phase:-none})"
    old_si_ok "$SYSTEM" && old_si_ok "$ACTIVE" || fail 'baseline SI required at both paths: reboot after rollback, then purge'
    navignore_ok "$OLD" || fail 'NavActiveIgnore must be back in the scan tree'
    ! exists "$NEW" || fail 'F7 Java archive still installed'
    ! renderer_alive || fail 'renderer still running; reboot first'
    cmp "$OLD" "$ROOT/backup/NavActiveIgnore.jar" >/dev/null || fail 'NavActiveIgnore differs from its backup; preserve the workspace'
    cmp "$SYSTEM" "$ROOT/backup/smartphone_integrator.json" >/dev/null || fail 'SI differs from its backup; preserve the workspace'
else
    stop_runtime
    [ "$DISARM_CLUSTER_OK" = 1 ] || echo""")
    c = once(c, "if [ \"$action\" = install ]; then\n    echo 'install_STEP: prepare private runtime workspace'\n",
             """if [ "$action" = off ] || [ "$action" = on ]; then
    target="$ROOT/off-$component"
    if [ "$action" = off ]; then
        if ! exists "$target"; then (umask 077; : > "$target") || fail "switch write $component"; fi
        [ -f "$target" ] && [ ! -L "$target" ] || fail "switch state $component"
    elif exists "$target"; then
        [ -f "$target" ] && [ ! -L "$target" ] || fail "unexpected $target; preserve it"
        rm "$target" || fail "switch remove $component"
    fi
    sync || fail 'switch sync'; completed=1
    if [ "$action" = off ]; then word=OFF; else word=ON; fi
    echo "F7_SWITCH: $component=$word persistent, effective $(switch_note "$component")"
    exit 0
fi
if [ "$action" = purge ]; then
    echo 'purge_STEP: remove the rolled-back runtime workspace (stock files were compared with its backups)'
    rm -rf "$ROOT" || fail 'purge remove'
    ! exists "$ROOT" || fail 'workspace still present'
    sync || fail 'purge sync'; completed=1
    echo 'F7_PURGED: runtime workspace removed'
    exit 0
fi
if [ "$action" = install ]; then
    echo 'install_STEP: prepare private runtime workspace'
""")
    c = once(c, """    put_file "$stage_dir/f4_unbuf.so" "$ROOT/render/f4_unbuf.so" 644 1988489462 5403 'runtime dmdt stdout shim' plain
""", """    put_file "$stage_dir/f4_unbuf.so" "$ROOT/render/f4_unbuf.so" 644 1988489462 5403 'runtime dmdt stdout shim' plain
    put_file "$stage_dir/f7_spawn" "$ROOT/render/f7_spawn" 755 %s %s 'runtime renderer launcher' plain
    put_file "$stage_dir/f7_render.sh" "$ROOT/render/f7_render.sh" 755 %s %s 'runtime renderer keeper' plain
""" % (spawn + render))
    armless = lambda l: l.replace("WARNING", "").replace("ARCHIVE", "").replace("DISARM_", "")
    assert "token_status" not in c and "ARM" not in armless(c), [l for l in c.splitlines() if "ARM" in armless(l)]
    assert "disarm" not in c.replace("render_disarm", "").replace("DISARM_", ""), \
        [l for l in c.splitlines() if "disarm" in l.replace("render_disarm", "").replace("DISARM_", "")]
    return c


def collector_hunks(col):
    col = once(col, "phase=${1:-snapshot}; case \"$phase\" in armed|restored|snapshot) ;; *) exit 2 ;; esac",
               "phase=${1:-snapshot}; case \"$phase\" in live|restored|snapshot) ;; *) exit 2 ;; esac")
    col = once(col, 'receipt="/tmp/mu1320-navhook-v1-gate-$p"', 'receipt="/tmp/mu1320-f7-gate-$p"')
    col = once(col, "    echo RAM_MARKERS; for f in /tmp/mu1320-navhook-v1.arm /tmp/carplay_verbose; do",
               "    echo RAM_MARKERS; for f in /tmp/carplay_verbose /tmp/mu1320-f7-render-hold /tmp/mu1320-f7-native-off; do")
    col = once(col, "    for f in /tmp/mu1320-navhook-v1-gate-*; do\n",
               "    for f in /tmp/mu1320-f7-gate-*; do\n")
    col = once(col, """    echo "GLOBAL_GATE_RECEIPT_COUNT=$receipt_count"; echo ALL_GATE_RECEIPTS_END
""", """    echo "GLOBAL_GATE_RECEIPT_COUNT=$receipt_count"; echo ALL_GATE_RECEIPTS_END
    for f in /tmp/mu1320-f7-gate.last /tmp/mu1320-f7-gate.strikes; do
        if [ -f "$f" ] && [ ! -L "$f" ]; then echo "GATE_RECORD: $f $(cat "$f")"; else echo "GATE_RECORD: $f ABSENT"; fi
    done
    for component_name in native render bap touchpad; do
        if [ -e "/mnt/app/root/mu1320-rgi-f7-v1/off-$component_name" ]; then echo "F7_SWITCH[$component_name]=OFF_PERSISTENT"; else echo "F7_SWITCH[$component_name]=on"; fi
    done
""")
    col = once(col, "/tmp/mu1320-f5-ctx-mode /tmp/mu1320-f6-touchpad.log; do",
               "/tmp/mu1320-f5-ctx-mode /tmp/mu1320-f6-touchpad.log /tmp/mu1320-f7-keeper.log; do")
    col = once(col, "' FIGHT_RESUME'; do", "' FIGHT_RESUME' ' KEEPER_UP' ' KEEPER_READY' ' KEEPER_HELD' ' KEEPER_FAIL' ' KEEPER_LOST' ' KEEPER_GIVE_UP' ' LOG_TRUNCATED'; do")
    col = once(col, "    echo F7_RENDER_LINES_END\n", """    echo F7_RENDER_LINES_END
    keeper_log=/tmp/mu1320-f7-keeper.log
    for label in 'KEEP BEGIN' 'KEEP READY' 'KEEP ALIVE' 'KEEP SPAWNED' 'KEEP HELD' 'KEEP FAIL' 'KEEP LOG_TRUNCATED'; do
        n=0; if [ -f "$keeper_log" ]; then n=$(grep -c -- "$label" "$keeper_log" 2>/dev/null || :); fi
        echo "F7_KEEPER_COUNT[$label]=${n:-0}"
    done
    echo F7_KEEPER_LINES_BEGIN
    if [ -f "$keeper_log" ]; then grep 'KEEP ' "$keeper_log" | head -100 || :; fi
    echo F7_KEEPER_LINES_END
""")
    col = once(col, "    echo 'INTERPRETATION: F7 evidence = stable active DIO + ACTIVE_TOKEN_CONSUMED + BIND ok",
               "    echo 'INTERPRETATION: F7 evidence = every DIO gate ACTIVE (reason ON/PREV_ALIVE) without arm + KEEP READY once per boot + BIND ok")
    return col


def wrapper_hunks(w):
    return once(w, "  'status: 1'|'install: 1'|'arm: 1'|'disarm: 1'|'rollback: 1'|'collect armed: 2'|'collect restored: 2'|'collect snapshot: 2') ;;\n"
                   "  *) echo 'usage: f7.sh status|install|arm|disarm|rollback|collect armed|restored|snapshot'; exit 2 ;;\n",
                "  'status: 1'|'install: 1'|'stop: 1'|'rollback: 1'|'purge: 1'|'collect live: 2'|'collect restored: 2'|'collect snapshot: 2') ;;\n"
                "  'off native: 2'|'off render: 2'|'off bap: 2'|'off touchpad: 2'|'on native: 2'|'on render: 2'|'on bap: 2'|'on touchpad: 2') ;;\n"
                "  *) echo 'usage: f7.sh status|install|stop|rollback|purge|collect live|restored|snapshot|off|on native|render|bap|touchpad'; exit 2 ;;\n")


def main():
    java = json.loads((BASE / "reports/f7-v1-build.json").read_text())
    audit = json.loads((BASE / "reports/f7-v1-audit.json").read_text())
    native = json.loads((BASE / "reports/f7-v1-native-build.json").read_text())
    assert audit["status"] == "PASS"
    jar = STAGE / JAR_NAME
    assert sha(jar) == java["jar_sha256"]
    present = sorted(p.name for p in STAGE.iterdir())
    if present != [jar.name]:
        assert not (STAGE / "out").exists(), "refusing to touch a stage folder that holds vehicle results"
        for p in STAGE.iterdir():
            if p.name != jar.name:
                p.unlink()
    f6_sums = dict(reversed(line.split("  ", 1)) for line in (F6 / "SHA256SUMS").read_text().splitlines())
    for name in CARRIED:
        shutil.copyfile(F6 / name, STAGE / name)
        assert sha(STAGE / name) == f6_sums[name], name
    nat = PRIVATE / "f7-daily-v1-native"
    for name, source in [("libcarplay_hook.so", nat / "src/build/libcarplay_hook.so"),
                         ("f7_spawn", nat / "spawn/f7_spawn")]:
        shutil.copyfile(source, STAGE / name)
        assert sha(STAGE / name) == native["artifacts"][name]["sha256"], name
    for name in ["trial_gate.c", "trial_gate.h", "f7_spawn.c"]:
        shutil.copyfile(SRC / name, STAGE / name)
    for name in ["loader_check", "mount_state", "maneuver_render", "f7_spawn"]:
        (STAGE / name).chmod(0o755)

    si = rename((F6 / "smartphone_integrator.json").read_text())
    assert si.count(RUNTIME) == 2 and si.count(MARKER) == 1 and "MU1320_F7_TRIAL=" in si, "SI rename"
    (STAGE / "smartphone_integrator.json").write_text(si)
    (STAGE / "IDENTITY").write_text(BUILD_ID + "\n")

    # Helpers: F6 v2 text with the F7 workspace and labels.
    for name in ["f5_dm.sh", "f5_sc.sh"]:
        (STAGE / name).write_text(rename((F6 / name).read_text()))
    (STAGE / "f5_sc.sh").chmod(0o755)

    def pin(path):
        return crc(STAGE / path)

    pins = {"SC": pin("f5_sc.sh"), "DMH": pin("f5_dm.sh"), "SPAWN": pin("f7_spawn")}
    keeper = (SRC / "f7_render.sh.in").read_text()
    values = {"RUNTIME": RUNTIME, "JAR": NEW_JAR}
    for label, name in [("RENDER", "maneuver_render"), ("ATLAS", "flag_atlas.rgba"), ("DMH", "f5_dm.sh"),
                        ("UNBUF", "f4_unbuf.so"), ("SPAWN", "f7_spawn")]:
        values[label + "_CRC"], values[label + "_SIZE"] = pin(name)
    for key, value in values.items():
        keeper = keeper.replace("@" + key + "@", value)
    assert not re.search(r"@[A-Z_]+@", keeper)
    (STAGE / "f7_render.sh").write_text(keeper)
    (STAGE / "f7_render.sh").chmod(0o755)
    pins["KEEPER"] = pin("f7_render.sh")

    # Checksums that change from F6 v2 to F7 v1 (old pair -> new pair).
    changed = [(crc(F6 / a), crc(STAGE / b)) for a, b in [
        ("IDENTITY", "IDENTITY"), ("libcarplay_hook.so", "libcarplay_hook.so"),
        ("carplay_mu1320_f6_accept_v2.jar.DISABLED", JAR_NAME), ("smartphone_integrator.json", "smartphone_integrator.json"),
        ("f5_sc.sh", "f5_sc.sh"), ("f5_dm.sh", "f5_dm.sh")]]
    collector = collector_hunks(rename((F6 / "collect_f6.sh").read_text()))
    collector = repin(collector, changed)
    (STAGE / "collect_f7.sh").write_text(collector)
    changed.append((crc(F6 / "collect_f6.sh"), pin("collect_f7.sh")))
    control = control_hunks(repin(rename((F6 / "control.sh").read_text()), changed), pins)
    (STAGE / "control.sh").write_text(control)
    changed.append((crc(F6 / "control.sh"), pin("control.sh")))
    wrapper = wrapper_hunks(repin(rename((F6 / "f6_trial.sh").read_text()), changed))
    (STAGE / "f7.sh").write_text(wrapper)

    # Every pin in the new scripts refers to an F7 file or an unchanged baseline.
    stale = {"%s %s" % old for old, new in changed if old != new}
    for name in ["control.sh", "collect_f7.sh", "f7.sh", "f7_render.sh"]:
        text = (STAGE / name).read_text()
        subprocess.run(["/bin/sh", "-n", str(STAGE / name)], check=True)
        for pair in stale:
            assert pair not in text, (name, pair)
        assert "3278904515" not in text, name  # the F1-F6 arm token
        assert "navhook-v1" not in text, name
        assert not re.search(r"exists [^\n;]*&&\s*fail", text), name
        assert not re.search(r"\bdm [^\n]*\bts\b", text), name
    for name in ["f5_dm.sh", "f5_sc.sh"]:
        subprocess.run(["/bin/sh", "-n", str(STAGE / name)], check=True)

    shutil.copyfile(SRC / "README.md", STAGE / "README.md")
    shutil.copyfile(SRC / "OBSERVATIONS-F7.txt", STAGE / "OBSERVATIONS-F7.txt")

    diffs = []
    for old, name in [("control.sh", "control.sh"), ("collect_f6.sh", "collect_f7.sh"), ("f6_trial.sh", "f7.sh"),
                      ("f5_dm.sh", "f5_dm.sh"), ("f5_sc.sh", "f5_sc.sh"),
                      ("smartphone_integrator.json", "smartphone_integrator.json")]:
        diffs += difflib.unified_diff((F6 / old).read_text().splitlines(True), (STAGE / name).read_text().splitlines(True),
                                      fromfile=F6.name + "/" + old, tofile=STAGE.name + "/" + name)
    (BASE / "reports/f7-v1-scripts.diff").write_text("".join(diffs))

    names = sorted(p.name for p in STAGE.iterdir() if p.is_file() and p.name != "SHA256SUMS")
    (STAGE / "SHA256SUMS").write_text("".join("%s  %s\n" % (sha(STAGE / n), n) for n in names))

    tests = subprocess.run([sys.executable, "-m", "unittest", "test_f7_gate.py", "test_f7_trial.py", "-v"],
                           cwd=BASE / "tests", env=dict(os.environ, PYTHONPATH=str(BASE / "tests")),
                           capture_output=True, text=True)
    log = BASE / "reports/f7-v1-host-tests.txt"
    log.write_text(tests.stdout + tests.stderr)
    assert tests.returncode == 0, tests.stdout[-4000:] + tests.stderr[-8000:]

    report = {
        "sd_folder": STAGE.name, "delivery": "copy the folder to the SD root; no ZIP is produced",
        "build_id": BUILD_ID, "runtime_root": RUNTIME, "marker": "MU1320_F7_TRIAL=" + MARKER,
        "java_artifact_sha256": sha(jar), "hook_sha256": sha(STAGE / "libcarplay_hook.so"),
        "carried_from_f6_v2": CARRIED,
        "scripts_derived_from": "F6 v2 scripts + rename + hunks; see reports/f7-v1-scripts.diff",
        "host_test_log_sha256": sha(log), "vehicle_tested": False,
        "files": {n: sha(STAGE / n) for n in names + ["SHA256SUMS"]},
    }
    (BASE / "reports/f7-v1-prepare.json").write_text(json.dumps(report, indent=2) + "\n")
    print("Prepared", STAGE.name, "with", len(names) + 1, "files; no vehicle writes were performed.")


if __name__ == "__main__":
    main()
