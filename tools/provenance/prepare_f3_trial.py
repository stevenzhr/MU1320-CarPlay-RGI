#!/usr/bin/env python3
"""Prepare the F3 BAP trial SD folder (copied to the SD card as is; no ZIP).

Vehicle mechanics = the navjava/F2 packages that passed on the car (same
navhook v1.2 hook, one-shot token, private DIO config, SI envs transaction)
+ the F1 v2 NavActiveIgnore quarantine (moved to the private workspace on
install, moved back on rollback).  Scripts are derived from the navjava
templates by an explicit rename table and quarantine hunks;
reports/f3-bap-<version>-scripts.diff records the result against the F2 scripts.
"""
import copy
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
from formats import config  # noqa: E402
from prepare_configs import add_ids  # noqa: E402

RESOURCE = BASE.parent / "resource"
# v1 ran on the car on 2026-09-25 (HOLD_OFF: stock check used the persistent
# route); its outputs keep the unversioned report names f3-bap-*.
VERSION = 2
V = "v%d" % VERSION
BUILD_ID = "MU1320-F3-BAP-V%d" % VERSION
REPORT = "f3-bap-" + V
STAGE = BASE / ("mu1320-f3-bap-" + V)
JAR_NAME = "carplay_mu1320_f3_bap_%s.jar.DISABLED" % V
RUNTIME = "/mnt/app/root/mu1320-rgi-f3-" + V
HOOK = RUNTIME + "/libcarplay_hook.so"
CONFIG_DIR = RUNTIME + "/config"
MARKER = "mu1320_f3_%s_" % V + hashlib.sha256(BUILD_ID.encode()).hexdigest()[:8]
NAVJAVA_MARKER = "mu1320_navjava_v1_8b972a0d"
LISTENER = BUILD_ID + " LISTENER_READY"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def crc(path):
    return subprocess.check_output(["cksum", str(path)], text=True).split()[:2]


def replace_once(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new)


def rename_tokens(text):
    """navjava -> F3 names.  Native token/receipt names (navhook) are kept."""
    for old, new in [
        (NAVJAVA_MARKER, MARKER),
        ("MU1320-NAVJAVA-INGRESS-V1", BUILD_ID),
        ("MU1320-NAVJAVA-V1-VERBOSE", "MU1320-F3-%s-VERBOSE" % V.upper()),
        ("CarPlayRGI-MU1320-IngressV1.jar", "CarPlayRGI-MU1320-F3Bap%s.jar" % V.upper()),
        ("carplay_mu1320_navjava_ingress_v1", "carplay_mu1320_f3_bap_" + V),
        ("mu1320-rgi-navjava-v1", "mu1320-rgi-f3-" + V),
        ("mu1320-navjava-v1", "mu1320-f3-" + V),
        ("collect_navjava.sh", "collect_f3.sh"),
        ("navjava_trial.sh", "f3_trial.sh"),
        ("MU1320_NAVJAVA_TRIAL", "MU1320_F3_TRIAL"),
        (".mu1320-navjava", ".mu1320-f3"),
        ("NAVJAVA_", "F3_"),
        ("INGRESS_INSTALLED", "F3_BAP_INSTALLED"),
        ("ingress Java archive", "F3 BAP Java archive"),
        ("Java ingress listener", "Java F3 listener"),
        ("ingress Java", "F3 BAP Java"),
        ("unknown ingress archive", "unknown F3 BAP archive"),
    ]:
        text = text.replace(old, new)
    assert not re.search(r"navjava|ingress", text, re.I), re.findall(r".*(?:navjava|ingress).*", text, re.I)
    return text


def quarantine_hunks(control):
    """F1 v2 NavActiveIgnore quarantine on top of the navjava transaction."""
    c = control
    c = replace_once(c, "OLD=$JARS/NavActiveIgnore.jar\n",
                     "OLD=$JARS/NavActiveIgnore.jar\n"
                     "QUARANTINE=$ROOT/quarantine/NavActiveIgnore.jar\n"
                     "BACKUP=$ROOT/backup/NavActiveIgnore.jar\n")
    c = replace_once(c,
        """echo "JAVA_ARCHIVE: $(java_state)"; echo "NAV_ACTIVE_IGNORE: $(navignore_ok "$OLD" && echo RETAINED_BASELINE || echo UNKNOWN)"\n""",
        """navignore_state() {
    if navignore_ok "$OLD"; then echo ACTIVE_BASELINE
    elif exists "$OLD"; then echo UNKNOWN_PRESENT
    elif navignore_ok "$QUARANTINE"; then echo QUARANTINED
    else echo MISSING; fi
}
echo "JAVA_ARCHIVE: $(java_state)"; echo "NAV_ACTIVE_IGNORE: $(navignore_state)"
echo "BAP_KILL_SWITCH: $(exists /tmp/mu1320-f3-bap-off && echo PRESENT || echo ABSENT)"
""")
    c = replace_once(c,
        """    [ -d "$ROOT" ] && [ ! -L "$ROOT" ] && [ -d "$ROOT/config" ] && [ -d "$ROOT/backup" ] || fail 'unsafe runtime workspace'\n""",
        """    [ -d "$ROOT" ] && [ ! -L "$ROOT" ] && [ -d "$ROOT/config" ] && [ -d "$ROOT/backup" ] && [ -d "$ROOT/quarantine" ] || fail 'unsafe runtime workspace'
    [ "$(dir_attrs "$ROOT/quarantine")" = 'drwx------ 0 0' ] || fail 'runtime quarantine attributes'
""")
    c = replace_once(c,
        """navignore_ok "$OLD" || fail 'NavActiveIgnore baseline changed'\n""",
        """[ "$(navignore_state)" = QUARANTINED ] || fail 'NavActiveIgnore must be quarantined before arm'\n""")
    c = replace_once(c,
        """    navignore_ok "$OLD" || fail 'NavActiveIgnore differs; this trial retains the exact baseline file'\n""",
        """    navignore_ok "$OLD" || fail 'NavActiveIgnore must be the active baseline file before install'
    if exists "$QUARANTINE"; then fail 'quarantine slot occupied while NavActiveIgnore is active; preserve both'; fi
""")
    c = replace_once(c,
        """    navignore_ok "$OLD" || fail 'retained NavActiveIgnore changed; preserve state'
    if old_si_ok "$SYSTEM" && ! exists "$NEW"; then echo""",
        """    case "$(navignore_state)" in ACTIVE_BASELINE|QUARANTINED|MISSING) ;; *) fail 'unknown NavActiveIgnore state; preserve it' ;; esac
    if old_si_ok "$SYSTEM" && ! exists "$NEW" && [ "$(navignore_state)" = ACTIVE_BASELINE ]; then echo""")
    c = replace_once(c,
        """    for directory in "$ROOT" "$ROOT/backup" "$ROOT/config"; do\n""",
        """    for directory in "$ROOT" "$ROOT/backup" "$ROOT/config" "$ROOT/quarantine"; do\n""")
    c = replace_once(c,
        """    java_ok "$NEW" || fail 'Java install validation'; navignore_ok "$OLD" || fail 'NavActiveIgnore changed'
    phase_write JAVA_INSTALLED
""",
        """    java_ok "$NEW" || fail 'Java install validation'; navignore_ok "$OLD" || fail 'NavActiveIgnore changed'
    phase_write JAVA_INSTALLED
    # Same qnx6 filesystem: rename moves NavActiveIgnore out of the recursive scan tree atomically.
    echo 'install_STEP: move NavActiveIgnore out of the scan tree'
    mv "$OLD" "$QUARANTINE" || fail 'NavActiveIgnore quarantine rename'
    navignore_ok "$QUARANTINE" || fail 'quarantined NavActiveIgnore validation'
    cmp "$QUARANTINE" "$BACKUP" >/dev/null || fail 'quarantine differs from backup'
    ! exists "$OLD" || fail 'NavActiveIgnore still in scan tree'
    phase_write NAVIGNORE_QUARANTINED
""")
    c = replace_once(c,
        """    old_si_ok "$SYSTEM" || fail 'restored SI validation'; phase_write SI_RESTORED
""",
        """    old_si_ok "$SYSTEM" || fail 'restored SI validation'; phase_write SI_RESTORED
    if ! navignore_ok "$OLD"; then
        if navignore_ok "$QUARANTINE"; then
            echo 'rollback_STEP: move quarantined NavActiveIgnore back'
            mv "$QUARANTINE" "$OLD" || fail 'NavActiveIgnore restore rename'
        else
            pending="$JARS/.mu1320-f3-restore.pending.$$"
            if exists "$pending"; then fail 'restore pending collision'; fi
            echo 'rollback_STEP: restore NavActiveIgnore from verified backup'
            cp -p "$BACKUP" "$pending" || fail 'NavActiveIgnore restore copy'
            chmod 777 "$pending" || fail 'NavActiveIgnore restore chmod'
            navignore_ok "$pending" || fail 'NavActiveIgnore restore validation'
            mv "$pending" "$OLD" || fail 'NavActiveIgnore restore commit'
        fi
    fi
    navignore_ok "$OLD" || fail 'restored NavActiveIgnore validation'; phase_write NAVIGNORE_RESTORED
""")
    c = replace_once(c, """navignore_ok "$OLD" || fail 'NavActiveIgnore baseline not retained'\n""",
                     """navignore_ok "$OLD" || fail 'NavActiveIgnore baseline not restored'\n""")
    return c


def derive_templates():
    control = quarantine_hunks(rename_tokens((BASE / "scripts/navjava_control.sh.in").read_text()))
    sd = rename_tokens((BASE / "scripts/navjava_sd.sh.in").read_text())
    collector = (BASE / "scripts/collect_navjava.sh.in").read_text()
    collector = replace_once(collector, """    java_ok=0; java_reject=0
    if [ -f /tmp/carplay_java.log ]; then java_ok=$(grep -c 'RGI-Ingress.*PARSE_OK' /tmp/carplay_java.log 2>/dev/null || :); java_reject=$(grep -c 'RGI-Ingress.*PARSE_REJECT' /tmp/carplay_java.log 2>/dev/null || :); fi
    echo "JAVA_PARSE_OK_COUNT=${java_ok:-0}"; echo "JAVA_PARSE_REJECT_COUNT=${java_reject:-0}"
""", """    echo F3_FILES_BEGIN
    # The capture holds sanitized frame diffs (free text replaced by tokens); it is
    # copied for host replay, not printed.  State and BAP logs hold no road text.
    for f in /tmp/mu1320-f3-state.log /tmp/mu1320-f3-frames.cap /tmp/mu1320-f3-bap.log; do
        if [ -f "$f" ] && [ ! -L "$f" ]; then name=${f##*/}; cp "$f" "$logdir/$name"; echo "COPIED: $f $(cksum "$f")"; else echo "MISSING: $f"; fi
    done
    echo F3_FILES_END
    state_log=/tmp/mu1320-f3-state.log; bap_log=/tmp/mu1320-f3-bap.log
    for label in 'F2 i=' 'ev=REJECT' 'ACTIVATE' 'ROUTE_END' 'ARRIVED' 'LINK_LOST' 'sym=MANEUVER'; do
        n=0; if [ -f "$state_log" ]; then n=$(grep -c -- "$label" "$state_log" 2>/dev/null || :); fi
        echo "F3_STATE_COUNT[$label]=${n:-0}"
    done
    for label in ' START ' ' TEARDOWN ' ' RELEASE_SILENT ' ' HOLD_OFF ' ' FAULT ' ' BIND ok' ' BIND fail' ' GATE ' ' CALL ' ' CALL DESCRIPTOR '; do
        n=0; if [ -f "$bap_log" ]; then n=$(grep -c -- "$label" "$bap_log" 2>/dev/null || :); fi
        echo "F3_BAP_COUNT[$label]=${n:-0}"
    done
    echo F3_BAP_EVENT_LINES_BEGIN
    if [ -f "$bap_log" ]; then grep -v -- ' CALL ' "$bap_log" | head -300 || :; fi
    echo F3_BAP_EVENT_LINES_END
    echo "F3_KILL_SWITCH: $( [ -e /tmp/mu1320-f3-bap-off ] && echo PRESENT || echo ABSENT )"
    if command -v sloginfo >/dev/null 2>&1; then sloginfo > "$logdir/sloginfo.txt" 2>&1; lrc=$?; else echo 'sloginfo unavailable' > "$logdir/sloginfo.txt"; lrc=127; fi
    echo "SLOGINFO_SAVED exit=$lrc lines=$(grep -c '' "$logdir/sloginfo.txt" 2>/dev/null || :)"
    echo SLOG_EXCERPT_BEGIN
    grep -i -E 'Modes changed|exception|verifyerror|linkageerror|noclassdef|incompatibleclass' "$logdir/sloginfo.txt" 2>/dev/null | tail -80 || :
    echo SLOG_EXCERPT_END
""")
    collector = replace_once(
        collector,
        "    echo ACTIVE_ARCHIVES; cksum /mnt/app/eso/hmi/lsd/jars/NavActiveIgnore.jar 2>&1 || :; cksum /mnt/app/eso/hmi/lsd/jars/CarPlayRGI-MU1320-IngressV1.jar 2>&1 || :\n",
        "    echo ACTIVE_ARCHIVES; cksum /mnt/app/eso/hmi/lsd/jars/NavActiveIgnore.jar 2>&1 || :; cksum /mnt/app/eso/hmi/lsd/jars/CarPlayRGI-MU1320-IngressV1.jar 2>&1 || :\n"
        "    cksum /mnt/app/root/mu1320-rgi-navjava-v1/quarantine/NavActiveIgnore.jar 2>&1 || :\n")
    collector = replace_once(
        collector,
        "    echo 'INTERPRETATION: success requires stable active DIO + ACTIVE_TOKEN_CONSUMED + hook 0x52xx + Java PARSE_OK with zero PARSE_REJECT'\n",
        "    echo 'INTERPRETATION: F3 evidence = stable active DIO + ACTIVE_TOKEN_CONSUMED + BIND ok + START/TEARDOWN per route with zero FAULT; VC/HUD display is judged from OBSERVATIONS'\n")
    collector = rename_tokens(collector)
    return control, collector, sd


def main():
    build = json.loads((BASE / "reports" / (REPORT + "-build.json")).read_text())
    audit = json.loads((BASE / "reports" / (REPORT + "-audit.json")).read_text())
    f2_prepare = json.loads((BASE / "reports/f2-shadow-prepare.json").read_text())
    assert audit["status"] == "PASS"
    jar = STAGE / JAR_NAME
    assert sha(jar) == build["jar_sha256"]
    assert sorted(path.name for path in STAGE.iterdir()) == [jar.name], "stage must hold only the new JAR"

    # Same SI/DIO transformation as navjava/F2, only runtime path and marker differ.
    stock_si = RESOURCE / "smartphone_integrator.json"
    stock_dio = RESOURCE / "dio_manager.json"
    source = stock_si.read_text()
    begin = source.index('"carplay":{')
    end = source.index('"carlife":{', begin)
    carplay = source[begin:end]
    carplay = replace_once(carplay, '"IPL_CONFIG_DIR_DIO_MANAGER=/etc/eso/production"]',
                           '"IPL_CONFIG_DIR_DIO_MANAGER=' + CONFIG_DIR + '", '
                           '"MU1320_F3_TRIAL=' + MARKER + '", "LD_PRELOAD=' + HOOK + '"]')
    patched_si = source[:begin] + carplay + source[end:]
    expected = copy.deepcopy(config(source))
    child = expected["children"]["carplay"]
    assert child["exec"] == "dio_manager" and child["path"] == "/mnt/app/eso/bin/apps"
    child["envs"] = [("IPL_CONFIG_DIR_DIO_MANAGER=" + CONFIG_DIR)
                     if item == "IPL_CONFIG_DIR_DIO_MANAGER=/etc/eso/production" else item
                     for item in child["envs"]]
    child["envs"] += ["MU1320_F3_TRIAL=" + MARKER, "LD_PRELOAD=" + HOOK]
    assert config(patched_si) == expected
    (STAGE / "smartphone_integrator.json").write_text(patched_si)
    navjava_si = (BASE / "navjava-trial/smartphone_integrator.json").read_text()
    assert navjava_si.replace("mu1320-rgi-navjava-v1", "mu1320-rgi-f3-" + V).replace(
        "MU1320_NAVJAVA_TRIAL=" + NAVJAVA_MARKER, "MU1320_F3_TRIAL=" + MARKER) == patched_si

    patched_dio = add_ids(stock_dio.read_text())
    assert patched_dio == (BASE / "navjava-trial/dio_manager.json").read_text()
    (STAGE / "dio_manager.json").write_text(patched_dio)
    (STAGE / "IDENTITY").write_text(BUILD_ID + "\n")
    (STAGE / "ARM-TOKEN").write_text("MU1320-NAVHOOK-ONE-SHOT-V1\n")

    # Native pieces: byte-identical to the vehicle-run navjava/F2 packages.
    for name in ["libcarplay_hook.so", "loader_check", "loader_check.c", "mount_state",
                 "mount_state.c", "trial_gate.c", "trial_gate.h"]:
        shutil.copyfile(BASE / "navjava-trial" / name, STAGE / name)
        assert sha(STAGE / name) == sha(BASE / "navjava-trial" / name) == f2_prepare["files"][name]
    for name in ["loader_check", "mount_state"]:
        (STAGE / name).chmod(0o755)
    assert (STAGE / "ARM-TOKEN").read_bytes() == (BASE / "navjava-trial/ARM-TOKEN").read_bytes()
    shutil.copyfile(BASE / "f3-src/README.md", STAGE / "README.md")
    shutil.copyfile(BASE / "f3-src/OBSERVATIONS-TEMPLATE.txt", STAGE / "OBSERVATIONS-TEMPLATE.txt")

    values = {"MARKER": MARKER}

    def pin(label, path):
        checksum, size = crc(path)
        values[label + "_CRC"], values[label + "_SIZE"] = checksum, size

    navignore = RESOURCE / "jars/NavActiveIgnore.jar"
    for label, path in [
        ("SI_OLD", stock_si), ("SI_NEW", STAGE / "smartphone_integrator.json"),
        ("DIO_OLD", stock_dio), ("DIO_NEW", STAGE / "dio_manager.json"),
        ("IDENTITY", STAGE / "IDENTITY"), ("ARM", STAGE / "ARM-TOKEN"),
        ("HOOK", STAGE / "libcarplay_hook.so"), ("MOUNT", STAGE / "mount_state"),
        ("LOADER", STAGE / "loader_check"), ("JAVA", jar), ("NAVIGNORE", navignore),
    ]:
        pin(label, path)

    runtime_files = [
        ("smartphone_integrator", RESOURCE / "smartphone_integrator", "/mnt/app/eso/bin/apps/smartphone_integrator"),
        ("dio_manager", RESOURCE / "dio_manager", "/mnt/app/eso/bin/apps/dio_manager"),
        ("libsocket.so.3", RESOURCE / "native-libs/lib/libsocket.so.3", "/lib/libsocket.so.3"),
        ("libNme.so", RESOURCE / "native-libs/mnt/app/armle/usr/lib/libNme.so", "/mnt/app/armle/usr/lib/libNme.so"),
        ("libNmeBaseClasses.so", RESOURCE / "native-libs/mnt/app/armle/usr/lib/libNmeBaseClasses.so", "/mnt/app/armle/usr/lib/libNmeBaseClasses.so"),
        ("libNmeSDK.so", RESOURCE / "native-libs/mnt/app/armle/usr/lib/libNmeSDK.so", "/mnt/app/armle/usr/lib/libNmeSDK.so"),
        ("libNmeTransport.so", RESOURCE / "cinemo/libNmeTransport.so", "/mnt/app/armle/usr/lib/cinemo/libNmeTransport.so"),
        ("libNmeNav.so", RESOURCE / "cinemo/libNmeNav.so", "/mnt/app/armle/usr/lib/cinemo/libNmeNav.so"),
    ]
    values["NATIVE_CHECKS"] = "\n    ".join(
        f'check {crc(local)[0]} {crc(local)[1]} {target} || fail "{name} baseline"'
        for name, local, target in runtime_files)
    payloads = [("SI_NEW", "smartphone_integrator.json"), ("DIO_NEW", "dio_manager.json"),
                ("IDENTITY", "IDENTITY"), ("ARM", "ARM-TOKEN"),
                ("HOOK", "libcarplay_hook.so"), ("LOADER", "loader_check"), ("JAVA", jar.name)]
    values["PAYLOAD_CHECKS"] = "\n    ".join(
        f'check @{label}_CRC@ @{label}_SIZE@ "$stage_dir/{name}" || fail "{name} payload checksum"'
        for label, name in payloads)
    pinned = {}
    for manifest in ["input-manifest.json", "supplement-manifest.json"]:
        pinned.update(json.loads((BASE / "reports" / manifest).read_text())["files"])
    baseline_checks, archive_cases = [], []
    for path in sorted((RESOURCE / "jars").iterdir()):
        assert path.suffix in [".jar", ".zip"]
        assert sha(path) == pinned["jars/" + path.name]["sha256"]
        checksum, size = crc(path)
        target = "/mnt/app/eso/hmi/lsd/jars/" + path.name
        baseline_checks.append(f'check {checksum} {size} {target} || fail "baseline archive differs: {path.name}"')
        archive_cases.append(f'            "{target}") check {checksum} {size} "$archive" || fail "archive changed: {path.name}" ;;')
    values["BASELINE_ARCHIVE_CHECKS"] = "\n    ".join(baseline_checks)
    values["ARCHIVE_CASES"] = "\n".join(archive_cases)

    control_t, collector_t, sd_t = derive_templates()
    # The collector's quarantine path is renamed with the runtime root above.
    assert RUNTIME + "/quarantine/NavActiveIgnore.jar" in collector_t

    def render(template, output):
        text = template
        for _ in range(2):
            for key, value in values.items():
                text = text.replace("@" + key + "@", value)
        assert not re.search(r"@[A-Z_]+@", text), output
        (STAGE / output).write_text(text)
        subprocess.run(["/bin/sh", "-n", str(STAGE / output)], check=True)
        return text

    render(collector_t, "collect_f3.sh")
    pin("COLLECT", STAGE / "collect_f3.sh")
    control = render(control_t, "control.sh")
    pin("CONTROL", STAGE / "control.sh")
    render(sd_t, "f3_trial.sh")
    assert not re.search(r"exists [^\n;]*&&\s*fail", control)
    assert LISTENER in control

    # Audit trail: rendered F3 scripts versus the F2 scripts that ran on the car.
    f2 = BASE / "mu1320-f2-shadow-v1"
    diffs = []
    for old, new in [("control.sh", "control.sh"), ("collect_f2.sh", "collect_f3.sh"),
                     ("f2_trial.sh", "f3_trial.sh")]:
        diffs += difflib.unified_diff(
            (f2 / old).read_text().splitlines(True), (STAGE / new).read_text().splitlines(True),
            fromfile="mu1320-f2-shadow-v1/" + old, tofile=STAGE.name + "/" + new)
    (BASE / "reports" / (REPORT + "-scripts.diff")).write_text("".join(diffs))

    tests = subprocess.run(
        [sys.executable, "-m", "unittest", "test_navjava_trial.py", "test_f2_trial.py", "test_f3_trial.py", "-v"],
        cwd=BASE / "tests", env=dict(os.environ, PYTHONPATH=str(BASE / "tests")),
        capture_output=True, text=True)
    test_log = BASE / "reports" / (REPORT + "-host-tests.txt")
    test_log.write_text(tests.stdout + tests.stderr)
    assert tests.returncode == 0, tests.stdout + tests.stderr

    names = sorted(path.name for path in STAGE.iterdir() if path.is_file() and path.name != "SHA256SUMS")
    (STAGE / "SHA256SUMS").write_text("".join(f"{sha(STAGE / name)}  {name}\n" for name in names))
    report = {
        "version": 1,
        "sd_folder": STAGE.name,
        "delivery": "copy the folder to the SD root; no ZIP is produced",
        "runtime_root": RUNTIME,
        "marker": "MU1320_F3_TRIAL=" + MARKER,
        "native_artifact_sha256": sha(STAGE / "libcarplay_hook.so"),
        "native_artifact_is_vehicle_verified_v1_2": True,
        "java_artifact_sha256": sha(jar),
        "java_scope": "RouteStateCore -> BapPlanner -> stock CombiBAPServiceNavi FctIDs 17/39/23/18/49/55/21, yield while stock DSI rgActive",
        "nav_active_ignore": "quarantined to the private workspace on install (F1 v2), restored on rollback",
        "renderer_included": False,
        "bap_included": True,
        "scripts_derived_from": "navjava templates + quarantine hunks; see reports/" + REPORT + "-scripts.diff (vs F2)",
        "host_test_log_sha256": sha(test_log),
        "vehicle_tested": False,
        "files": {name: sha(STAGE / name) for name in names + ["SHA256SUMS"]},
    }
    (BASE / "reports" / (REPORT + "-prepare.json")).write_text(json.dumps(report, indent=2) + "\n")
    print("Prepared", STAGE.name, "with", len(names) + 1, "files; no vehicle writes were performed.")


if __name__ == "__main__":
    main()
