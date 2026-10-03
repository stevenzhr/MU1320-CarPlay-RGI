#!/usr/bin/env python3
"""Prepare the combined native-to-Java ingress vehicle package."""
import copy
import difflib
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

from formats import config
from prepare_configs import add_ids

BASE = Path(__file__).resolve().parents[1]
RESOURCE = BASE.parent / "resource"
STAGE = BASE / "navjava-trial"
RUNTIME = "/mnt/app/root/mu1320-rgi-navjava-v1"
HOOK = RUNTIME + "/libcarplay_hook.so"
CONFIG_DIR = RUNTIME + "/config"
MARKER = "mu1320_navjava_v1_8b972a0d"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def crc(path):
    return subprocess.check_output(["cksum", str(path)], text=True).split()[:2]


def replace_once(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new)


def main():
    build = json.loads((BASE / "reports/navjava-ingress-build.json").read_text())
    audit = json.loads((BASE / "reports/navjava-ingress-audit.json").read_text())
    vehicle = json.loads((BASE / "reports/navhook-trial-vehicle-v1.json").read_text())
    assert audit["status"] == "PASS"
    assert vehicle["status"] == "NATIVE_RGI_RECEPTION_AND_RUNTIME_ROLLBACK_VERIFIED"
    jar = STAGE / "carplay_mu1320_navjava_ingress_v1.jar.DISABLED"
    assert sha(jar) == build["jar_sha256"]
    # build_navjava_ingress.py creates STAGE only for the immutable JAR.
    assert sorted(path.name for path in STAGE.iterdir()) == [jar.name]

    stock_si = RESOURCE / "smartphone_integrator.json"
    stock_dio = RESOURCE / "dio_manager.json"
    source = stock_si.read_text()
    begin = source.index('"carplay":{')
    end = source.index('"carlife":{', begin)
    carplay = source[begin:end]
    old_env = '"IPL_CONFIG_DIR_DIO_MANAGER=/etc/eso/production"]'
    new_env = ('"IPL_CONFIG_DIR_DIO_MANAGER=' + CONFIG_DIR + '", '
               '"MU1320_NAVJAVA_TRIAL=' + MARKER + '", '
               '"LD_PRELOAD=' + HOOK + '"]')
    carplay = replace_once(carplay, old_env, new_env)
    patched_si = source[:begin] + carplay + source[end:]
    expected = copy.deepcopy(config(source))
    child = expected["children"]["carplay"]
    assert child["exec"] == "dio_manager" and child["path"] == "/mnt/app/eso/bin/apps"
    child["envs"] = [("IPL_CONFIG_DIR_DIO_MANAGER=" + CONFIG_DIR)
                     if item == "IPL_CONFIG_DIR_DIO_MANAGER=/etc/eso/production" else item
                     for item in child["envs"]]
    child["envs"] += ["MU1320_NAVJAVA_TRIAL=" + MARKER, "LD_PRELOAD=" + HOOK]
    assert config(patched_si) == expected
    (STAGE / "smartphone_integrator.json").write_text(patched_si)

    patched_dio = add_ids(stock_dio.read_text())
    before, after = config(stock_dio.read_text()), config(patched_dio)
    expected_dio = copy.deepcopy(before)
    expected_dio["iap2"]["MessagesSentByAccessory"] += ["0x5200", "0x5203"]
    expected_dio["iap2"]["MessagesReceivedFromDevice"] += ["0x5201", "0x5202", "0x5204"]
    assert after == expected_dio
    (STAGE / "dio_manager.json").write_text(patched_dio)
    (STAGE / "IDENTITY").write_text("MU1320-NAVJAVA-INGRESS-V1\n")
    (STAGE / "ARM-TOKEN").write_text("MU1320-NAVHOOK-ONE-SHOT-V1\n")

    native_report = json.loads((BASE / "reports/navhook-trial-build.json").read_text())
    native = BASE / "navhook-trial/libcarplay_hook.so"
    assert sha(native) == native_report["artifact"]["sha256"]
    copies = {
        "libcarplay_hook.so": native,
        "loader_check": BASE / "navhook-trial/loader_check",
        "loader_check.c": BASE / "navhook-trial/loader_check.c",
        "mount_state": BASE / "navhook-trial/mount_state",
        "mount_state.c": BASE / "navhook-trial/mount_state.c",
        "trial_gate.c": BASE / "navhook-trial/trial_gate.c",
        "trial_gate.h": BASE / "navhook-trial/trial_gate.h",
        "README.md": BASE / "navjava-trial-src/README.md",
    }
    for name, path in copies.items():
        shutil.copyfile(path, STAGE / name)
    for name in ["loader_check", "mount_state"]:
        (STAGE / name).chmod(0o755)

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
                ("HOOK", "libcarplay_hook.so"), ("LOADER", "loader_check"),
                ("JAVA", jar.name)]
    values["PAYLOAD_CHECKS"] = "\n    ".join(
        f'check @{label}_CRC@ @{label}_SIZE@ "$stage_dir/{name}" || fail "{name} payload checksum"'
        for label, name in payloads)

    pinned = {}
    for manifest in ["input-manifest.json", "supplement-manifest.json"]:
        pinned.update(json.loads((BASE / "reports" / manifest).read_text())["files"])
    baseline_checks = []
    archive_cases = []
    for path in sorted((RESOURCE / "jars").iterdir()):
        assert path.suffix in [".jar", ".zip"]
        assert sha(path) == pinned["jars/" + path.name]["sha256"]
        checksum, size = crc(path)
        target = "/mnt/app/eso/hmi/lsd/jars/" + path.name
        baseline_checks.append(f'check {checksum} {size} {target} || fail "baseline archive differs: {path.name}"')
        archive_cases.append(f'            "{target}") check {checksum} {size} "$archive" || fail "archive changed: {path.name}" ;;')
    values["BASELINE_ARCHIVE_CHECKS"] = "\n    ".join(baseline_checks)
    values["ARCHIVE_CASES"] = "\n".join(archive_cases)

    def render(template, output):
        text = (BASE / "scripts" / template).read_text()
        for _ in range(2):
            for key, value in values.items():
                text = text.replace("@" + key + "@", value)
        assert not re.search(r"@[A-Z_]+@", text), output
        (STAGE / output).write_text(text)
        subprocess.run(["/bin/sh", "-n", str(STAGE / output)], check=True)

    render("collect_navjava.sh.in", "collect_navjava.sh")
    pin("COLLECT", STAGE / "collect_navjava.sh")
    render("navjava_control.sh.in", "control.sh")
    pin("CONTROL", STAGE / "control.sh")
    render("navjava_sd.sh.in", "navjava_trial.sh")

    (BASE / "reports/navjava-ingress-si.diff").write_text("".join(difflib.unified_diff(
        source.splitlines(True), patched_si.splitlines(True),
        fromfile="stock/smartphone_integrator.json", tofile="navjava-trial/smartphone_integrator.json")))
    dio_source = stock_dio.read_text()
    (BASE / "reports/navjava-ingress-dio.diff").write_text("".join(difflib.unified_diff(
        dio_source.splitlines(True), patched_dio.splitlines(True),
        fromfile="stock/dio_manager.json", tofile="navjava-trial/dio_manager.json")))
    report = {
        "version": 1,
        "runtime_root": RUNTIME,
        "marker": "MU1320_NAVJAVA_TRIAL=" + MARKER,
        "native_artifact_sha256": sha(native),
        "native_artifact_is_vehicle_verified_v1_2": True,
        "java_artifact_sha256": sha(jar),
        "java_scope": "receive and parse EVT_RGD_UPDATE only",
        "nav_active_ignore": "retained active, hash-pinned, copied to private rollback workspace",
        "renderer_included": False,
        "bap_included": False,
        "ownership_change_included": False,
        "global_receipt_glob_fixed": True,
        "wrapper_exit_evidence": "control exit saved on SD; final SD restore and outer exit emitted to terminal",
        "vehicle_tested": False,
        "files": {path.name: sha(path) for path in STAGE.iterdir() if path.is_file()},
    }
    (BASE / "reports/navjava-ingress-prepare.json").write_text(json.dumps(report, indent=2) + "\n")
    print("Prepared native-to-Java ingress trial; no vehicle writes were performed.")


if __name__ == "__main__":
    main()
