#!/usr/bin/env python3
"""Prepare the F7 v2.1 SD folder, the F8 fixed candidate (copied to the SD card as
is; no ZIP).

F7 v2.1 = F7 v2 (closed 2026-10-02) with every runtime binary unchanged plus:

  F8 monitor (BACKLOG B10)  f8_mon.sh, installed to <workspace>/mon/ with a copy of
       mount_state.  The renderer keeper (run by the F7 Java on every CarPlay
       session) starts it once per boot through f7_spawn, before any HOLD exit.
       Every 60 s it samples free memory, CPU times, threads, data size and
       descriptors of the processes F7 touches; every 2 samples it appends them and
       copies the changed F7 logs to out/f8/boot-<seq>-<pid>/ on the SD.  It ends
       when F7 is uninstalled or switched off (off monitor / /tmp/mu1320-f8-mon-off).
  SD lock   f7.sh and the monitor share /tmp/mu1320-f8-sd.lock, so the SD mount
       state never changes under a menu action or a flush.
  purge guard (B14 note)  purge refuses while the F7 Java ran in this boot, the
       monitor or renderer runs, or a DIO carries the F7 marker: reboot first.
  status    F8_MONITOR, F8_MONITOR_STATE and OTHER_WORKSPACES (old v1.1 etc.).
  switch    off|on monitor (persistent), like the other components.

Byte for byte from F7 v2 (same workspace mu1320-rgi-f7-v2, BUILD_ID, marker and
JAR name, so the car-proven hook/Java/renderer are not rebuilt): the JAR, hook,
renderer, atlas, helpers, SI/DIO configs, IDENTITY, f5_*.sh, f7_mark.sh, loader.
Only the SD folder name changes: mu1320-f7-daily-v2.1.
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
V2 = BASE / "mu1320-f7-daily-v2"
STAGE = BASE / "mu1320-f7-daily-v2.1"
SRC = BASE / "f8-src"
BUILD_ID = "MU1320-F7-DAILY-V2"          # unchanged: Java and hook are the v2 bytes
CANDIDATE = "MU1320-F7-DAILY-V2.1"
RUNTIME = "mu1320-rgi-f7-v2"
CARRIED = ["IDENTITY", "carplay_mu1320_f7_daily_v2.jar.DISABLED", "libcarplay_hook.so", "loader_check", "loader_check.c",
           "mount_state", "mount_state.c", "dio_manager.json", "smartphone_integrator.json", "maneuver_render",
           "flag_atlas.rgba", "f4_unbuf.so", "geom-example.cfg", "f7_spawn", "f7_spawn.c", "trial_gate.c", "trial_gate.h",
           "f5_sc.sh", "f5_dm.sh", "f7_mark.sh"]
SCRIPTS = ["control.sh", "collect_f7.sh", "f7.sh", "f7_render.sh", "f5_sc.sh", "f5_dm.sh", "f7_mark.sh", "f8_mon.sh"]
PATCHED = ["f7_render.sh", "collect_f7.sh", "control.sh", "f7.sh"]
EXEC = ["loader_check", "mount_state", "maneuver_render", "f7_spawn", "f5_sc.sh", "f7_render.sh", "f7_mark.sh", "f8_mon.sh"]
# test_f7_v21_trial reruns every F7/F7 v2 transaction case on this folder; the v2 folder
# tests themselves are not rerun (the user fills its observation sheet in place).
TESTS = ["test_f7_v21_trial.py", "test_f8_mon.py", "test_toolbox_v1.py"]
USER_FILLED = {"OBSERVATIONS-F7.txt"}
ENTRY = "MU1320_F7_TOOLBOX_ENTRY 1\nbuild=%s\nwrapper=f7.sh\n" % CANDIDATE
MOUNT_PIN = "2952412687 7302"

# ---- f7_render.sh: start the monitor once per boot, before any HOLD exit ---------------
KEEP_ANCHOR = 'out "BEGIN pid=$$"\n'
KEEP_BLOCK = KEEP_ANCHOR + '''# F7 v2.1 (F8): start the long-term monitor once per boot, before the HOLD exits so a
# stopped boot keeps its record.  It never fails the keeper.
MON=$ROOT/mon
MON_RUN=/tmp/mu1320-f8-mon.run
mon_start() {
    [ -f "$JAR" ] || return 0
    if exists /tmp/mu1320-f8-mon-off || exists "$ROOT/off-monitor"; then out 'MON off'; return 0; fi
    m_pid=''
    if [ -f "$MON_RUN" ]; then read -r m_pid < "$MON_RUN" || :; fi
    case "$m_pid" in ''|*[!0-9]*) ;; *) if kill -0 "$m_pid" 2>/dev/null; then return 0; fi ;; esac
    check @MON@ "$MON/f8_mon.sh" || { out 'MON_FAIL monitor checksum'; return 0; }
    check @MOUNT@ "$MON/mount_state" || { out 'MON_FAIL mount helper checksum'; return 0; }
    check 292735868 8680 "$RENDER/f7_spawn" || { out 'MON_FAIL launcher checksum'; return 0; }
    m_rc=0
    "$RENDER/f7_spawn" /tmp/mu1320-f8-mon.pid /tmp/mu1320-f8-mon.log "$MON" /bin/sh "$MON/f8_mon.sh" run || m_rc=$?
    if [ "$m_rc" = 0 ]; then out "MON SPAWNED pid=$(cat /tmp/mu1320-f8-mon.pid)"; else out "MON_FAIL f7_spawn exit $m_rc"; fi
    return 0
}
mon_start
'''

# ---- collect_f7.sh: monitor files and switch ---------------------------------------------
COL_SW_OLD = "    for component_name in native render bap touchpad; do\n"
COL_SW_NEW = "    for component_name in native render bap touchpad monitor; do\n"
COL_FILES_OLD = "/tmp/mu1320-f6-touchpad.log /tmp/mu1320-f7-keeper.log; do\n"
COL_FILES_NEW = ("/tmp/mu1320-f6-touchpad.log /tmp/mu1320-f7-keeper.log "
                 "/tmp/mu1320-f8-mon.log /tmp/mu1320-f8-mon.state /tmp/mu1320-f8-mon.buf; do\n")

# ---- control.sh ------------------------------------------------------------------------------
CTL_COMP_OLD = "case \"$component\" in ''|native|render|bap|touchpad) ;; *) exit 2 ;; esac\n"
CTL_COMP_NEW = "case \"$component\" in ''|native|render|bap|touchpad|monitor) ;; *) exit 2 ;; esac\n"
CTL_SW_OLD = "for component_name in native render bap touchpad; do\n"
CTL_SW_NEW = "for component_name in native render bap touchpad monitor; do\n"
CTL_STATUS_ANCHOR = 'echo "KEEPER_LAST: $keeper_last"\n'
CTL_STATUS_BLOCK = CTL_STATUS_ANCHOR + '''# F7 v2.1 (F8): the long-term monitor and any other workspace left in /mnt/app/root.
MON_RUN=/tmp/mu1320-f8-mon.run
mon_alive() {
    mon_pid=''
    if [ -f "$MON_RUN" ]; then read -r mon_pid < "$MON_RUN" || :; fi
    case "$mon_pid" in ''|*[!0-9]*) return 1 ;; esac
    kill -0 "$mon_pid" 2>/dev/null
}
mon_state=NONE; if [ -f /tmp/mu1320-f8-mon.state ]; then read -r mon_state < /tmp/mu1320-f8-mon.state || :; fi
if mon_alive; then echo "F8_MONITOR: RUNNING pid=$mon_pid"; elif [ "$mon_state" != NONE ]; then echo 'F8_MONITOR: ENDED'; else echo 'F8_MONITOR: ABSENT'; fi
echo "F8_MONITOR_STATE: $mon_state"
other_ws=''; set +f
for ws in /mnt/app/root/mu1320-rgi-*; do
    if [ -d "$ws" ] && [ "$ws" != "$ROOT" ]; then other_ws="$other_ws ${ws##*/}"; fi
done
set -f
echo "OTHER_WORKSPACES:${other_ws:- none}"
'''
CTL_RT_OLD = "    check 1042317273 4707 \"$ROOT/render/f7_render.sh\" || fail 'runtime renderer keeper checksum'\n"
CTL_RT_NEW = CTL_RT_OLD + '''    [ -d "$ROOT/mon" ] && [ ! -L "$ROOT/mon" ] || fail 'runtime monitor directory'
    check @MON@ "$ROOT/mon/f8_mon.sh" || fail 'runtime monitor checksum'
    check @MOUNT@ "$ROOT/mon/mount_state" || fail 'runtime monitor mount helper checksum'
'''
CTL_NOTE_OLD = ("switch_note() { case \"$1\" in native) echo 'from the next DIO start (USB connect)' ;; "
                "*) echo 'within 2 s, no restart' ;; esac; }\n")
CTL_NOTE_NEW = ("switch_note() { case \"$1\" in native) echo 'from the next DIO start (USB connect)' ;; "
                "monitor) echo 'off: within 60 s; on: from the next CarPlay session' ;; "
                "*) echo 'within 2 s, no restart' ;; esac; }\n")
CTL_PAY_OLD = "    check 1042317273 4707 \"$stage_dir/f7_render.sh\" || fail \"f7_render.sh payload checksum\"\n"
CTL_PAY_NEW = CTL_PAY_OLD + "    check @MON@ \"$stage_dir/f8_mon.sh\" || fail \"f8_mon.sh payload checksum\"\n"
CTL_PURGE_OLD = "    ! renderer_alive || fail 'renderer still running; reboot first'\n"
CTL_PURGE_NEW = CTL_PURGE_OLD + '''    # F7 v2.1: purge only after the reboot that follows rollback (F7 v2 car run purged in
    # the rollback boot): no F7 Java, monitor or hooked DIO may still be running.
    for java_log in "$JAVA_LOG" "$JAVA_LOG.1"; do
        if [ -f "$java_log" ] && grep 'MU1320-F7-DAILY-V2 LISTENER_READY' "$java_log" >/dev/null 2>&1; then
            fail 'F7 Java ran in this boot: reboot after rollback, then purge'
        fi
    done
    if mon_alive; then fail 'F8 monitor still running: reboot after rollback, then purge'; fi
    command -v pidin >/dev/null 2>&1 || fail 'missing pidin'
    table=$(pidin -F '%a %256n') || fail 'cannot inspect live processes'
    while read -r p_pid p_name; do
        case "$p_pid" in ''|*[!0-9]*) continue ;; esac
        case "$p_name" in
            *dio_manager*)
                if pidin -p "$p_pid" environment 2>/dev/null | grep "$MARKER" >/dev/null 2>&1; then
                    fail "DIO $p_pid carries the F7 hook: reboot after rollback, then purge"
                fi ;;
        esac
    done <<PURGE_TABLE
$table
PURGE_TABLE
'''
CTL_DIRS_OLD = 'for directory in "$ROOT" "$ROOT/backup" "$ROOT/config" "$ROOT/quarantine" "$ROOT/render"; do\n'
CTL_DIRS_NEW = 'for directory in "$ROOT" "$ROOT/backup" "$ROOT/config" "$ROOT/quarantine" "$ROOT/render" "$ROOT/mon"; do\n'
CTL_PUT_OLD = ("    put_file \"$stage_dir/f7_render.sh\" \"$ROOT/render/f7_render.sh\" 755 1042317273 4707 "
               "'runtime renderer keeper' plain\n")
CTL_PUT_NEW = CTL_PUT_OLD + (
    "    put_file \"$stage_dir/f8_mon.sh\" \"$ROOT/mon/f8_mon.sh\" 755 @MON@ 'runtime monitor' plain\n"
    "    put_file \"$stage_dir/mount_state\" \"$ROOT/mon/mount_state\" 755 @MOUNT@ 'runtime monitor mount helper' plain\n")

# ---- f7.sh: monitor switch and the shared SD lock -------------------------------------------
F7_CASE_OLD = "  'off native: 2'|'off render: 2'|'off bap: 2'|'off touchpad: 2'|'on native: 2'|'on render: 2'|'on bap: 2'|'on touchpad: 2') ;;\n"
F7_CASE_NEW = ("  'off native: 2'|'off render: 2'|'off bap: 2'|'off touchpad: 2'|'on native: 2'|'on render: 2'|'on bap: 2'|'on touchpad: 2') ;;\n"
               "  'off monitor: 2'|'on monitor: 2') ;;\n")
F7_USAGE_OLD = "off|on native|render|bap|touchpad'; exit 2 ;;\n"
F7_USAGE_NEW = "off|on native|render|bap|touchpad|monitor'; exit 2 ;;\n"
F7_LOCK_OLD = "initial=$(state) || fail 'SD mount query'; case \"$initial\" in ro|rw) ;; *) fail 'unknown SD mount state' ;; esac\n"
F7_LOCK_NEW = '''# F7 v2.1 (F8): the monitor remounts this SD for its flushes; both sides take the same
# lock before they look at or change the mount state.  A dead holder is replaced.
SD_LOCK=/tmp/mu1320-f8-sd.lock; sd_locked=0
lock_holder() { lh=''; if [ -f "$SD_LOCK" ]; then read -r lh < "$SD_LOCK" || :; fi; echo "$lh"; }
lock_take() {
    if (set -C; echo "$$" > "$SD_LOCK") 2>/dev/null; then return 0; fi
    lt=$(lock_holder)
    case "$lt" in ''|*[!0-9]*) ;; *) if kill -0 "$lt" 2>/dev/null; then return 1; fi ;; esac
    rm -f "$SD_LOCK" || return 1
    (set -C; echo "$$" > "$SD_LOCK") 2>/dev/null
}
sd_unlock() { if [ "$sd_locked" = 1 ] && [ "$(lock_holder)" = "$$" ]; then rm -f "$SD_LOCK" || :; fi; sd_locked=0; }
lock_wait=0
while ! lock_take; do
    [ "$lock_wait" -lt 30 ] || fail "SD busy for 30 s (F8 monitor flush, pid $(lock_holder)); press again"
    sleep 1; lock_wait=$((lock_wait + 1))
done
sd_locked=1; [ "$lock_wait" = 0 ] || echo "SD_LOCK_WAITED: ${lock_wait}s"
initial=$(state) || { sd_unlock; fail 'SD mount query'; }
case "$initial" in ro|rw) ;; *) sd_unlock; fail 'unknown SD mount state' ;; esac
'''
F7_UNLOCK_OLD = '    [ -z "$log" ] || echo "ACTION_LOG_ON_SD: $log"\n'
F7_UNLOCK_NEW = '    sd_unlock\n' + F7_UNLOCK_OLD

HUNKS = {
    "f7_render.sh": [(KEEP_ANCHOR, KEEP_BLOCK)],
    "collect_f7.sh": [(COL_SW_OLD, COL_SW_NEW), (COL_FILES_OLD, COL_FILES_NEW)],
    "control.sh": [(CTL_COMP_OLD, CTL_COMP_NEW), (CTL_SW_OLD, CTL_SW_NEW), (CTL_STATUS_ANCHOR, CTL_STATUS_BLOCK),
                   (CTL_RT_OLD, CTL_RT_NEW), (CTL_NOTE_OLD, CTL_NOTE_NEW), (CTL_PAY_OLD, CTL_PAY_NEW),
                   (CTL_PURGE_OLD, CTL_PURGE_NEW), (CTL_DIRS_OLD, CTL_DIRS_NEW), (CTL_PUT_OLD, CTL_PUT_NEW)],
    "f7.sh": [(F7_CASE_OLD, F7_CASE_NEW), (F7_USAGE_OLD, F7_USAGE_NEW), (F7_LOCK_OLD, F7_LOCK_NEW),
              (F7_UNLOCK_OLD, F7_UNLOCK_NEW)],
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def crc(path):
    out = subprocess.check_output(["cksum", str(path)], text=True).split()
    return out[0], out[1]


def patch(name, text, pins):
    for old, new in HUNKS.get(name, []):
        assert text.count(old) == 1, (name, old[:70])
        text = text.replace(old, new, 1)
    for key, value in pins.items():
        text = text.replace("@%s@" % key, value)
    assert "@MON@" not in text and "@MOUNT@" not in text, name
    return text


def repin(text, pins):
    for old, new in pins:
        if old != new:
            text = text.replace("%s %s" % old, "%s %s" % new)
            text = text.replace("'%s' ] && [ \"${2:-}\" = '%s'" % old, "'%s' ] && [ \"${2:-}\" = '%s'" % new)
    return text


def main():
    v2prep = json.loads((BASE / "reports/f7-v2-prepare.json").read_text())
    for name, digest in v2prep["files"].items():  # the car-run v2 folder is untouched
        if name in USER_FILLED:
            continue
        assert sha(V2 / name) == digest, "F7 v2 folder changed: " + name
    if STAGE.exists():
        assert not (STAGE / "out").exists(), "refusing to touch a stage folder that holds vehicle results"
        shutil.rmtree(STAGE)
    STAGE.mkdir()

    for name in CARRIED:
        shutil.copyfile(V2 / name, STAGE / name)
    for name in ["f8_mon.sh", "README.md", "OBSERVATIONS-F8.txt"]:
        shutil.copyfile(SRC / name, STAGE / name)
    (STAGE / "TOOLBOX-ENTRY").write_text(ENTRY)
    assert crc(STAGE / "mount_state") == tuple(MOUNT_PIN.split())
    pins = {"MON": "%s %s" % crc(STAGE / "f8_mon.sh"), "MOUNT": MOUNT_PIN}

    # Pins: each script in the order it is pinned by the next.
    changed = []
    for name in PATCHED:
        (STAGE / name).write_text(repin(patch(name, (V2 / name).read_text(), pins), changed))
        changed.append((crc(V2 / name), crc(STAGE / name)))
    for name in EXEC:
        (STAGE / name).chmod(0o755)

    stale = {"%s %s" % old for old, new in changed if old != new}
    for name in SCRIPTS:
        text = (STAGE / name).read_text()
        for shell in ["/bin/sh", "/bin/ksh"]:
            if Path(shell).exists():
                subprocess.run([shell, "-n", str(STAGE / name)], check=True)
        for pair in stale:
            assert pair not in text, (name, pair)
        assert not re.search(r"exists [^\n;]*&&\s*fail", text), name
        code = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
        assert not re.search(r"\bdm [^\n]*\bts\b|dmdt ts\b", code), name
        if name == "f8_mon.sh":
            assert "dmdt" not in code and "set -e" not in code, name
        assert not re.search(r"tr -c '[^']*[A-Za-z0-9]-[A-Za-z0-9]", text), name
        roots = set(re.findall(r"/mnt/app/root/(mu1320[\w.-]*)", text)) - {"mu1320-rgi-"}  # status glob
        assert roots <= {RUNTIME}, (name, roots)
    mon = (STAGE / "f8_mon.sh").read_text()
    assert not re.search(r"^\s*(cp|mv|rm|mkdir|echo)[^\n]*/mnt/(app|system)", mon, re.M), "monitor writes flash"
    assert "FOLDER=" + STAGE.name + "\n" in mon

    # Only the reviewed hunks differ from v2.
    for name in SCRIPTS:
        if name == "f8_mon.sh":
            continue
        expect = repin(patch(name, (V2 / name).read_text(), pins), changed)
        assert (STAGE / name).read_text() == expect
        assert ((V2 / name).read_text() != expect) == (name in HUNKS), name

    diffs = []
    for name in PATCHED + ["TOOLBOX-ENTRY", "README.md"]:
        diffs += difflib.unified_diff((V2 / name).read_text().splitlines(True), (STAGE / name).read_text().splitlines(True),
                                      fromfile=V2.name + "/" + name, tofile=STAGE.name + "/" + name)
    (BASE / "reports/f7-v2.1-scripts.diff").write_text("".join(diffs))

    names = sorted(p.name for p in STAGE.iterdir() if p.is_file() and p.name != "SHA256SUMS")
    (STAGE / "SHA256SUMS").write_text("".join("%s  %s\n" % (sha(STAGE / n), n) for n in names))

    tests = subprocess.run([sys.executable, "-m", "unittest"] + TESTS + ["-v"],
                           cwd=BASE / "tests", env=dict(os.environ, PYTHONPATH=str(BASE / "tests")),
                           capture_output=True, text=True)
    log = BASE / "reports/f7-v2.1-host-tests.txt"
    log.write_text(tests.stdout + tests.stderr)
    assert tests.returncode == 0, tests.stdout[-4000:] + tests.stderr[-8000:]

    report = {
        "sd_folder": STAGE.name, "delivery": "copy the folder to the SD root; no ZIP is produced",
        "candidate": CANDIDATE, "build_id": BUILD_ID, "runtime_root": "/mnt/app/root/" + RUNTIME,
        "carried_from_f7_v2": CARRIED,
        "unchanged_runtime_sha256": {n: sha(STAGE / n) for n in ["libcarplay_hook.so", "carplay_mu1320_f7_daily_v2.jar.DISABLED",
                                                                 "maneuver_render", "f7_spawn", "smartphone_integrator.json",
                                                                 "dio_manager.json"]},
        "new_files": ["f8_mon.sh", "OBSERVATIONS-F8.txt"],
        "behavioural_hunks": {k: len(v) for k, v in HUNKS.items()},
        "monitor_cksum": pins["MON"],
        "scripts_derived_from": "F7 v2 scripts patched and re-pinned; see reports/f7-v2.1-scripts.diff",
        "toolbox_entry": ENTRY,
        "host_tests": TESTS, "host_test_log_sha256": sha(log), "vehicle_tested": False,
        "files": {n: sha(STAGE / n) for n in names + ["SHA256SUMS"]},
    }
    (BASE / "reports/f7-v2.1-prepare.json").write_text(json.dumps(report, indent=2) + "\n")
    print("Prepared", STAGE.name, "with", len(names) + 1, "files; no vehicle writes were performed.")


if __name__ == "__main__":
    main()
