#!/usr/bin/env python3
"""Audit the F1 v2 vehicle run from the raw SD output; writes reports/f1-v2-vehicle.json."""
import hashlib
import json
import re
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
DUMP = BASE.parent / "resource/private/vehicle-dump/f1-navi-v2"
JARS = "/mnt/app/eso/hmi/lsd/jars/"
F1_JAR = "3095502315      23735 " + JARS + "CarPlayRGI-MU1320-F1NaviV2.jar"
NAI = "2960431692       2645 " + JARS + "NavActiveIgnore.jar"


def read(path):
    return path.read_text(errors="replace")


def section(text, begin, end):
    return text.split(begin, 1)[1].split(end, 1)[0]


def uptime(text):
    m = re.search(r"Thu Jan 01 (\d\d):(\d\d):(\d\d) GMT 1970", text)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))


def modes(slog):
    rows = []
    for line in slog.splitlines():
        m = re.search(r"(\d\d:\d\d:\d\d)\.\d+ AM \[AirPlay\] <AirPlay> Modes changed: (.*)$", line)
        if m:
            fields = dict(part.strip().split(" ", 1) for part in m.group(2).split(","))
            rows.append((m.group(1), fields))
    return rows


def main():
    checks, facts = {}, {}
    actions = {p.name: read(p) for p in DUMP.glob("action-*.txt")}
    install = [t for n, t in actions.items() if n.startswith("action-install-")]
    rollback = [t for n, t in actions.items() if n.startswith("action-rollback-")]
    status = [t for n, t in actions.items() if n.startswith("action-status-")]
    checks["pre_install_status_baseline"] = any("FILES: INSTALLATION_BASELINE" in t for t in status)
    checks["install_passed"] = len(install) == 1 and "F1_install_FILES_PASSED" in install[0] and "CONTROL_EXIT=0" in install[0]
    checks["install_fresh_workspace"] = "install_STEP: write NavActiveIgnore backup" in install[0]
    checks["rollback_passed"] = len(rollback) == 1 and "F1_rollback_FILES_PASSED" in rollback[0] and "CONTROL_EXIT=0" in rollback[0]
    checks["rollback_used_quarantine"] = "move quarantined NavActiveIgnore back" in rollback[0]
    terminal = read(DUMP / "terminal_output.txt")
    checks["terminal_footers_zero"] = terminal.count("OUTER_EXIT: 0") >= 3 and "OUTER_EXIT: 1" not in terminal

    (f1_dir,) = DUMP.glob("f1-*")
    (restored_dir,) = DUMP.glob("restored-*")
    f1, restored = read(f1_dir / "collect.txt"), read(restored_dir / "collect.txt")
    for name, text, archive_expect, witness in [("f1", f1, F1_JAR, "install"), ("restored", restored, NAI, "rollback")]:
        archives = section(text, "HMI_ARCHIVES_BEGIN", "HMI_ARCHIVES_END")
        checks[name + "_expected_archive_present"] = archive_expect in archives
        checks[name + "_other_archive_absent"] = (NAI.split()[-1] not in archives) if name == "f1" else ("F1NaviV2" not in archives)
        checks[name + "_witness_absent_after_full_restart"] = "ABSENT: /tmp/mu1320-f1-v2.%s-witness" % witness in text
        checks[name + "_no_trial_logs"] = all("ABSENT: " + p in text for p in
                                              ["/tmp/carplay_java.log", "/tmp/carplay_hook.log", "/tmp/mu1320-f1-naviseam.log"])
        checks[name + "_dio_without_preload"] = "DIO_ENV_PRELOAD=0" in text and "DIO_ENV_PRELOAD=1" not in text
        checks[name + "_si_baseline"] = text.count(" 535418540       7359 ") == 2
        checks[name + "_no_javacore"] = read((f1_dir if name == "f1" else restored_dir) / "javacore-list.txt").strip() == ""
        facts[name] = {
            "uptime_s": uptime(text),
            "j9": re.search(r"HMI_J9 pid=(\d+)", text).group(1),
            "si": re.search(r"^SI pid=(\d+) parent=(\d+)", text, re.M).groups(),
            "dio": re.findall(r"^DIO pid=(\d+)", text, re.M),
        }
    # A new boot between f1 and restored: uptime restarted and SI identity changed.
    checks["new_boot_between_f1_and_restored"] = (facts["restored"]["uptime_s"] < facts["f1"]["uptime_s"]
                                                  and facts["restored"]["si"] != facts["f1"]["si"])

    f1_slog, restored_slog = read(f1_dir / "sloginfo.txt"), read(restored_dir / "sloginfo.txt")
    f1_modes = modes(f1_slog)
    checks["carplay_session_started_f1"] = "session started" in f1_slog and "state=[2|STARTED]" in f1_slog
    checks["carplay_session_started_restored"] = "session started" in restored_slog
    checks["turn_by_turn_granted_to_phone"] = any(m["turns"] == "controller" for _, m in f1_modes)
    checks["speech_granted_to_phone"] = any(m["speech"].startswith("controller") for _, m in f1_modes)
    java_errors = [l for l in f1_slog.splitlines()
                   if re.search(r"VerifyError|LinkageError|NoClassDefFound|ClassFormatError|IncompatibleClassChange", l)]
    checks["no_java_linkage_errors_in_slog"] = not java_errors
    facts["f1_airplay_modes"] = [{"t": t, **m} for t, m in f1_modes]
    facts["phone_mode_seen"] = any(m["phone"] != "n/a" for _, m in f1_modes)

    obs = read(DUMP / "OBSERVATIONS.txt")
    status_ok = all(checks.values())
    report = {
        "status": "F1_V2_NAVI_SEAM_AND_ROLLBACK_VERIFIED" if status_ok else "FAIL",
        "checks": checks,
        "facts": facts,
        "user_observations_sha256": hashlib.sha256(obs.encode()).hexdigest(),
        "inputs_sha256": {str(p.relative_to(DUMP)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sorted(DUMP.rglob("*")) if p.is_file()},
        "limits": [
            "No per-call log of the seam; NAVI behaviour is inferred from observation (native route not taken over while AirPlay turns=controller) plus the archive set after a full restart.",
            "No AirPlay phone mode was recorded in the collected f1 boot; the phone check is user-reported only.",
            "Restored boot recorded only a short CarPlay session; rollback-column observations are user-reported.",
            "Android Auto not tested (not used).",
        ],
    }
    (BASE / "reports/f1-v2-vehicle.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(report["status"])
    for k, v in checks.items():
        if not v:
            print("FAILED", k)
    return 0 if status_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
