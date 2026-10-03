#!/usr/bin/env python3
"""Prepare the F2 shadow-state SD folder (copied to the SD card as is; no ZIP).

Vehicle mechanics are the navjava-ingress v1 package that passed on the car
(§49): same vehicle-verified navhook v1.2 hook, one-shot token, private DIO
config, SI envs transaction, NavActiveIgnore retained and hash-pinned.  The
control/collector/wrapper scripts are derived from the navjava templates by
an explicit substitution table; reports/f2-shadow-scripts.diff records it.
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
STAGE = BASE / "mu1320-f2-shadow-v1"
JAR_NAME = "carplay_mu1320_f2_shadow_v1.jar.DISABLED"
RUNTIME = "/mnt/app/root/mu1320-rgi-f2-v1"
HOOK = RUNTIME + "/libcarplay_hook.so"
CONFIG_DIR = RUNTIME + "/config"
MARKER = "mu1320_f2_v1_" + hashlib.sha256(b"MU1320-F2-SHADOW-V1").hexdigest()[:8]
NAVJAVA_MARKER = "mu1320_navjava_v1_8b972a0d"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def crc(path):
    return subprocess.check_output(["cksum", str(path)], text=True).split()[:2]


def replace_once(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new)


def rename_tokens(text):
    """navjava -> F2 names.  Native token/receipt names (navhook) are kept."""
    for old, new in [
        (NAVJAVA_MARKER, MARKER),
        ("MU1320-NAVJAVA-INGRESS-V1", "MU1320-F2-SHADOW-V1"),
        ("MU1320-NAVJAVA-V1-VERBOSE", "MU1320-F2-V1-VERBOSE"),
        ("CarPlayRGI-MU1320-IngressV1.jar", "CarPlayRGI-MU1320-F2ShadowV1.jar"),
        ("carplay_mu1320_navjava_ingress_v1", "carplay_mu1320_f2_shadow_v1"),
        ("mu1320-rgi-navjava-v1", "mu1320-rgi-f2-v1"),
        ("mu1320-navjava-v1", "mu1320-f2-v1"),
        ("collect_navjava.sh", "collect_f2.sh"),
        ("navjava_trial.sh", "f2_trial.sh"),
        ("MU1320_NAVJAVA_TRIAL", "MU1320_F2_TRIAL"),
        (".mu1320-navjava", ".mu1320-f2"),
        ("NAVJAVA_", "F2_"),
        ("INGRESS_INSTALLED", "F2_SHADOW_INSTALLED"),
        ("ingress Java archive", "F2 shadow Java archive"),
        ("Java ingress listener", "Java F2 listener"),
        ("ingress Java", "F2 shadow Java"),
        ("unknown ingress archive", "unknown F2 shadow archive"),
    ]:
        text = text.replace(old, new)
    assert not re.search(r"navjava|ingress", text, re.I), re.findall(r".*(?:navjava|ingress).*", text, re.I)
    return text


def derive_templates():
    control = rename_tokens((BASE / "scripts/navjava_control.sh.in").read_text())
    sd = rename_tokens((BASE / "scripts/navjava_sd.sh.in").read_text())
    collector = (BASE / "scripts/collect_navjava.sh.in").read_text()
    collector = replace_once(collector, """    java_ok=0; java_reject=0
    if [ -f /tmp/carplay_java.log ]; then java_ok=$(grep -c 'RGI-Ingress.*PARSE_OK' /tmp/carplay_java.log 2>/dev/null || :); java_reject=$(grep -c 'RGI-Ingress.*PARSE_REJECT' /tmp/carplay_java.log 2>/dev/null || :); fi
    echo "JAVA_PARSE_OK_COUNT=${java_ok:-0}"; echo "JAVA_PARSE_REJECT_COUNT=${java_reject:-0}"
""", """    echo F2_FILES_BEGIN
    # The capture holds sanitized frame diffs (free text replaced by tokens); it is
    # copied for host replay, not printed.  The state log holds no road text.
    for f in /tmp/mu1320-f2-state.log /tmp/mu1320-f2-frames.cap; do
        if [ -f "$f" ] && [ ! -L "$f" ]; then name=${f##*/}; cp "$f" "$logdir/$name"; echo "COPIED: $f $(cksum "$f")"; else echo "MISSING: $f"; fi
    done
    echo F2_FILES_END
    state_log=/tmp/mu1320-f2-state.log
    for label in 'F2 i=' 'ev=REJECT' 'ACTIVATE' 'DEACTIVATE' 'ROUTE_END' 'ARRIVED' 'DISCONNECT' 'LINK_LOST' 'SESSION' 'HARD_CLEAR' 'REPLAY' 'sym=MANEUVER'; do
        n=0; if [ -f "$state_log" ]; then n=$(grep -c -- "$label" "$state_log" 2>/dev/null || :); fi
        echo "F2_COUNT[$label]=${n:-0}"
    done
    echo F2_EVENT_LINES_BEGIN
    if [ -f "$state_log" ]; then grep -v -- ' ev=UPDATE ' "$state_log" | head -300 || :; fi
    echo F2_EVENT_LINES_END
""")
    collector = replace_once(
        collector,
        "    echo 'INTERPRETATION: success requires stable active DIO + ACTIVE_TOKEN_CONSUMED + hook 0x52xx + Java PARSE_OK with zero PARSE_REJECT'\n",
        "    echo 'INTERPRETATION: F2 shadow evidence = stable active DIO + ACTIVE_TOKEN_CONSUMED + hook 0x52xx + F2 state lines with zero ev=REJECT; clear events must show act=0 and no distance'\n")
    collector = rename_tokens(collector)
    return control, collector, sd


def main():
    build = json.loads((BASE / "reports/f2-shadow-build.json").read_text())
    audit = json.loads((BASE / "reports/f2-shadow-audit.json").read_text())
    navjava_vehicle = json.loads((BASE / "reports/navjava-ingress-vehicle-v1.json").read_text())
    assert audit["status"] == "PASS"
    assert navjava_vehicle["status"] == "NATIVE_TO_JAVA_INGRESS_AND_ROLLBACK_VERIFIED"
    jar = STAGE / JAR_NAME
    assert sha(jar) == build["jar_sha256"]
    assert sorted(path.name for path in STAGE.iterdir()) == [jar.name], "stage must hold only the new JAR"

    # Same SI/DIO transformation as navjava, only runtime path and marker differ.
    stock_si = RESOURCE / "smartphone_integrator.json"
    stock_dio = RESOURCE / "dio_manager.json"
    source = stock_si.read_text()
    begin = source.index('"carplay":{')
    end = source.index('"carlife":{', begin)
    carplay = source[begin:end]
    carplay = replace_once(carplay, '"IPL_CONFIG_DIR_DIO_MANAGER=/etc/eso/production"]',
                           '"IPL_CONFIG_DIR_DIO_MANAGER=' + CONFIG_DIR + '", '
                           '"MU1320_F2_TRIAL=' + MARKER + '", "LD_PRELOAD=' + HOOK + '"]')
    patched_si = source[:begin] + carplay + source[end:]
    expected = copy.deepcopy(config(source))
    child = expected["children"]["carplay"]
    assert child["exec"] == "dio_manager" and child["path"] == "/mnt/app/eso/bin/apps"
    child["envs"] = [("IPL_CONFIG_DIR_DIO_MANAGER=" + CONFIG_DIR)
                     if item == "IPL_CONFIG_DIR_DIO_MANAGER=/etc/eso/production" else item
                     for item in child["envs"]]
    child["envs"] += ["MU1320_F2_TRIAL=" + MARKER, "LD_PRELOAD=" + HOOK]
    assert config(patched_si) == expected
    (STAGE / "smartphone_integrator.json").write_text(patched_si)
    navjava_si = (BASE / "navjava-trial/smartphone_integrator.json").read_text()
    assert navjava_si.replace("mu1320-rgi-navjava-v1", "mu1320-rgi-f2-v1").replace(
        "MU1320_NAVJAVA_TRIAL=" + NAVJAVA_MARKER, "MU1320_F2_TRIAL=" + MARKER) == patched_si

    patched_dio = add_ids(stock_dio.read_text())
    assert patched_dio == (BASE / "navjava-trial/dio_manager.json").read_text()
    (STAGE / "dio_manager.json").write_text(patched_dio)
    (STAGE / "IDENTITY").write_text("MU1320-F2-SHADOW-V1\n")
    (STAGE / "ARM-TOKEN").write_text("MU1320-NAVHOOK-ONE-SHOT-V1\n")

    # Native pieces: byte-identical to the vehicle-run navjava package.
    for name in ["libcarplay_hook.so", "loader_check", "loader_check.c", "mount_state",
                 "mount_state.c", "trial_gate.c", "trial_gate.h"]:
        shutil.copyfile(BASE / "navjava-trial" / name, STAGE / name)
        assert sha(STAGE / name) == sha(BASE / "navjava-trial" / name)
    for name in ["loader_check", "mount_state"]:
        (STAGE / name).chmod(0o755)
    assert (STAGE / "ARM-TOKEN").read_bytes() == (BASE / "navjava-trial/ARM-TOKEN").read_bytes()
    shutil.copyfile(BASE / "f2-src/README.md", STAGE / "README.md")
    shutil.copyfile(BASE / "f2-src/OBSERVATIONS-TEMPLATE.txt", STAGE / "OBSERVATIONS-TEMPLATE.txt")

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

    def render(template, output):
        text = template
        for _ in range(2):
            for key, value in values.items():
                text = text.replace("@" + key + "@", value)
        assert not re.search(r"@[A-Z_]+@", text), output
        (STAGE / output).write_text(text)
        subprocess.run(["/bin/sh", "-n", str(STAGE / output)], check=True)
        return text

    render(collector_t, "collect_f2.sh")
    pin("COLLECT", STAGE / "collect_f2.sh")
    control = render(control_t, "control.sh")
    pin("CONTROL", STAGE / "control.sh")
    render(sd_t, "f2_trial.sh")
    assert not re.search(r"exists [^\n;]*&&\s*fail", control)
    assert "MU1320-F2-SHADOW-V1 LISTENER_READY" in control

    # Audit trail: rendered F2 scripts versus the navjava scripts that ran on the car.
    diffs = []
    for old, new in [("control.sh", "control.sh"), ("collect_navjava.sh", "collect_f2.sh"),
                     ("navjava_trial.sh", "f2_trial.sh")]:
        diffs += difflib.unified_diff(
            (BASE / "navjava-trial" / old).read_text().splitlines(True),
            (STAGE / new).read_text().splitlines(True),
            fromfile="navjava-trial/" + old, tofile="mu1320-f2-shadow-v1/" + new)
    (BASE / "reports/f2-shadow-scripts.diff").write_text("".join(diffs))

    tests = subprocess.run(
        [sys.executable, "-m", "unittest", "test_navjava_trial.py", "test_f2_trial.py", "-v"],
        cwd=BASE / "tests", env=dict(os.environ, PYTHONPATH=str(BASE / "tests")),
        capture_output=True, text=True)
    test_log = BASE / "reports/f2-shadow-host-tests.txt"
    test_log.write_text(tests.stdout + tests.stderr)
    assert tests.returncode == 0, tests.stdout + tests.stderr

    names = sorted(path.name for path in STAGE.iterdir() if path.is_file() and path.name != "SHA256SUMS")
    (STAGE / "SHA256SUMS").write_text("".join(f"{sha(STAGE / name)}  {name}\n" for name in names))
    report = {
        "version": 1,
        "sd_folder": STAGE.name,
        "delivery": "copy the folder to the SD root; no ZIP is produced",
        "runtime_root": RUNTIME,
        "marker": "MU1320_F2_TRIAL=" + MARKER,
        "native_artifact_sha256": sha(STAGE / "libcarplay_hook.so"),
        "native_artifact_is_vehicle_verified_v1_2": True,
        "java_artifact_sha256": sha(jar),
        "java_scope": "EVT_RGD_UPDATE -> RouteStateCore shadow decisions; publishes nothing",
        "nav_active_ignore": "retained active, hash-pinned, copied to private rollback workspace",
        "renderer_included": False,
        "bap_included": False,
        "ownership_change_included": False,
        "scripts_derived_from": "navjava templates; see reports/f2-shadow-scripts.diff",
        "host_test_log_sha256": sha(test_log),
        "vehicle_tested": False,
        "files": {name: sha(STAGE / name) for name in names + ["SHA256SUMS"]},
    }
    (BASE / "reports/f2-shadow-prepare.json").write_text(json.dumps(report, indent=2) + "\n")
    print("Prepared", STAGE.name, "with", len(names) + 1, "files; no vehicle writes were performed.")


if __name__ == "__main__":
    main()
