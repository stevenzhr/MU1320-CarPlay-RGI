#!/usr/bin/env python3
"""Audit the returned native-to-Java ingress v1 vehicle run from raw SD output.

Every verdict is recomputed from the raw action logs, per-process files and
collector output; collector summary lines are only cross-checked. Route names
and destinations in the native log are never copied into the report.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
DUMP = BASE.parent / "resource/private/vehicle-dump/navjava-ingress-v1"
REPORT = BASE / "reports/navjava-ingress-vehicle-v1.json"

SI_OLD = ("535418540", "7359")
SI_NEW = ("4083375225", "7502")
NAVIGNORE = ("2960431692", "2645")
JAVA = ("2635590041", "27941")
MARKER = "MU1320_NAVJAVA_TRIAL=mu1320_navjava_v1_8b972a0d"
PRELOAD = "LD_PRELOAD=/mnt/app/root/mu1320-rgi-navjava-v1/libcarplay_hook.so"
JARS = "/mnt/app/eso/hmi/lsd/jars/"

checks = []


def check(name, ok, detail=""):
    checks.append({"check": name, "pass": bool(ok), "detail": detail})


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def action(kind, needle=None):
    found = []
    for path in sorted(DUMP.glob(f"action-{kind}-*.txt")):
        text = path.read_text(errors="replace")
        if needle is None or needle in text:
            found.append((path, text))
    return found


def one(kind, needle=None):
    found = action(kind, needle)
    assert len(found) == 1, (kind, needle, [p.name for p, _ in found])
    return found[0]


def footer_ok(text):
    return "CONTROL_EXIT=0" in text and "OUTER_EXIT_BEFORE_SD_CLEANUP=0" in text


def cksum_lines(text, begin, end):
    block = text.split(begin, 1)[1].split(end, 1)[0]
    out = {}
    for line in block.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0].isdigit():
            out[parts[2]] = (parts[0], parts[1])
        elif "No such file" in line:
            out[line.split(":", 1)[0]] = None
    return out


def identities(text, pid):
    """The before/after identity rows inside this process's PROCESS block only."""
    block = re.search(rf"PROCESS_BEGIN: role=\w+ pid={pid}\n(.*?)\nPROCESS_END", text, re.S).group(1)
    before = block.split("ENVIRONMENT_BEGIN", 1)[0]
    after = block.split("IDENTITY_AFTER", 1)[1]
    pattern = re.compile(rf"^\s*{pid}\s+(\d+)\s+(\S+)\s+(.+?)\s*$", re.M)
    return pattern.findall(before) + pattern.findall(after)


def phase(name):
    dirs = [d for d in DUMP.iterdir() if d.is_dir() and d.name.startswith(name + "-")]
    assert len(dirs) == 1, dirs
    d = dirs[0]
    collect = (d / "collect.txt").read_text(errors="replace")
    dio = re.search(r"DIRECT_SI_PARENT: dio=(\d+) si=(\d+)", collect)
    return d, collect, dio.group(1), dio.group(2)


def audit_phase(label, d, collect, dio, si, armed):
    cfg = cksum_lines(collect, "CONFIG_CHECKSUMS", "ACTIVE_ARCHIVES")
    want = SI_NEW if armed else SI_OLD
    check(f"{label}: both SI paths {'trial' if armed else 'baseline'}",
          set(cfg.values()) == {want} and len(cfg) == 2, str(cfg))
    arch = cksum_lines(collect, "ACTIVE_ARCHIVES", "RAM_MARKERS")
    check(f"{label}: NavActiveIgnore.jar unchanged", arch.get(JARS + "NavActiveIgnore.jar") == NAVIGNORE)
    new = arch.get(JARS + "CarPlayRGI-MU1320-IngressV1.jar")
    check(f"{label}: ingress JAR {'active' if armed else 'absent'}", new == (JAVA if armed else None), str(new))
    check(f"{label}: arm token absent", "ABSENT: /tmp/mu1320-navhook-v1.arm" in collect)
    check(f"{label}: exactly one live DIO, direct SI child",
          "DIO_PROCESSES_OBSERVED=1" in collect and "DIO_PARENT_NOT_SI" not in collect)
    check(f"{label}: no invalid/changed observation", "OBSERVATION_INVALID_OR_CHANGED" not in collect)
    for pid, role in [(dio, "DIO"), (si, "SI")]:
        ids = identities(collect, pid)
        check(f"{label}: {role} {pid} identity stable across observation",
              len(ids) >= 2 and len(set(ids)) == 1, str(ids[:2]))
    env = (d / f"DIO-{dio}-environment.txt").read_text()
    mem = (d / f"DIO-{dio}-mem.txt").read_text()
    si_env = (d / f"SI-{si}-environment.txt").read_text()
    si_mem = (d / f"SI-{si}-mem.txt").read_text()
    check(f"{label}: raw DIO env marker={int(armed)} preload={int(armed)}",
          (MARKER in env) == armed and (PRELOAD in env) == armed and "LD_PRELOAD" in env if armed
          else MARKER not in env and "LD_PRELOAD" not in env)
    check(f"{label}: collector summary agrees with raw env",
          f"DIO_ENV_MARKER={int(armed)} DIO_ENV_PRELOAD={int(armed)}" in collect)
    check(f"{label}: DIO hook mapping {'present' if armed else 'absent'}", ("libcarplay_hook.so" in mem) == armed)
    check(f"{label}: SI itself has no marker/preload/hook",
          MARKER not in si_env and "LD_PRELOAD" not in si_env and "libcarplay_hook" not in si_mem)
    receipts = re.findall(r"^FILE: /tmp/mu1320-navhook-v1-gate-(\d+)$", collect, re.M)
    count = re.search(r"GLOBAL_GATE_RECEIPT_COUNT=(\d+)", collect).group(1)
    return env, mem, receipts, int(count)


def main():
    result = {"version": 1, "inputs": {}, "checks": checks}
    for path in sorted(DUMP.rglob("*")):
        if path.is_file():
            result["inputs"][str(path.relative_to(DUMP))] = sha(path)

    # --- file transactions -------------------------------------------------
    _, before = one("status", "SYSTEM_CONFIG: BASELINE")
    check("pre-install status: both SI baseline, JAR absent, NavActiveIgnore retained, token absent",
          "ACTIVE_CONFIG: BASELINE" in before and "JAVA_ARCHIVE: ABSENT" in before
          and "NAV_ACTIVE_IGNORE: RETAINED_BASELINE" in before and "TOKEN: ABSENT" in before
          and footer_ok(before))
    _, install = one("install")
    check("install: loader passed, Java and SI committed, mounts restored",
          "STAGE1_LOADER_PASSED" in install and "install_STEP: commit Java archive rename" in install
          and "install_STEP: commit SI rename" in install
          and "MOUNTS_RESTORED: app=ro system=ro" in install
          and "NAVJAVA_install_FILES_PASSED" in install and footer_ok(install))
    _, after = one("status", "SYSTEM_CONFIG: NAVJAVA_TRIAL")
    check("post-reboot status: trial SI at both paths, ingress JAR installed",
          "ACTIVE_CONFIG: NAVJAVA_TRIAL" in after and "JAVA_ARCHIVE: INGRESS_INSTALLED" in after
          and "TOKEN: ABSENT" in after and footer_ok(after))
    _, arm = one("arm")
    check("arm: listener gate passed, armed once", "ARMED_ONCE" in arm and footer_ok(arm))
    _, rollback = one("rollback")
    check("rollback: SI restored, Java moved out of scan tree, mounts restored",
          "rollback_STEP: commit SI rename" in rollback
          and "rollback_STEP: move ingress Java archive out of the scan tree" in rollback
          and "MOUNTS_RESTORED: app=ro system=ro" in rollback
          and "NAVJAVA_rollback_FILES_PASSED" in rollback and footer_ok(rollback))
    for path, text in action("collect"):
        check(f"{path.name}: collect exit 0 and control footer", "COLLECT_EXIT=0" in text and footer_ok(text))

    # --- armed -----------------------------------------------------------
    d, collect, dio, si = phase("armed")
    env, mem, receipts, count = audit_phase("armed", d, collect, dio, si, True)
    receipt = (d / f"DIO-{dio}-gate-receipt.txt").read_text().strip()
    check("armed: exactly one global gate receipt, for this DIO",
          count == 1 and receipts == [dio], f"count={count} receipts={receipts}")
    check("armed: receipt ACTIVE_TOKEN_CONSUMED with matching pid/ppid",
          receipt == f"MU1320_NAVHOOK_V1_GATE mode=ACTIVE_TOKEN_CONSUMED pid={dio} ppid={si}")

    hook = (d / "carplay_hook.log").read_text(errors="replace")
    hook_lines = hook.splitlines()
    check("armed: hook Identify patched and accepted, auth complete",
          "Identify patched: 538 -> 624 bytes" in hook and "Identify accepted (0x1D02)" in hook
          and "Auth complete (0xAA05)" in hook)
    check("armed: hook bus owner is the gated DIO and connected to Java",
          f"connected to Java server pid={dio}" in hook and f"owner-pid={dio}" in hook)
    sent = sum("Sent 0x5200" in l for l in hook_lines)
    first = "FIRST RouteGuidance message received! msgid=0x5201" in hook
    updates = [re.search(r"Update: state=(\d+)", l).group(1) for l in hook_lines if "] Update: state=" in l]
    maneuvers = sum("] Maneuver: idx=" in l for l in hook_lines)
    lanes = sum("Lane" in l and "[RGD]" in l for l in hook_lines)
    times = [l[:12] for l in hook_lines if "] Update: state=" in l]
    check("armed: native route data received (0x5201 Update + 0x5202 Maneuver)",
          first and len(updates) > 0 and maneuvers > 0)

    java = (d / "carplay_java.log").read_text(errors="replace")
    parse_ok = [l for l in java.splitlines() if "[RGI-Ingress] PARSE_OK" in l]
    check("armed: Java LISTENER_READY before any PARSE_OK",
          "MU1320-NAVJAVA-INGRESS-V1 LISTENER_READY" in java
          and java.index("LISTENER_READY") < java.index("PARSE_OK"))
    check("armed: Java PARSE_OK >= 1, PARSE_REJECT = 0, collector counts agree",
          len(parse_ok) >= 1 and "PARSE_REJECT" not in java
          and f"JAVA_PARSE_OK_COUNT={len(parse_ok)}" in collect and "JAVA_PARSE_REJECT_COUNT=0" in collect)
    frames = [int(re.search(r"frame=(\d+)", l).group(1)) for l in parse_ok]
    check("armed: Java frames contiguous from 1, no replay",
          frames == list(range(1, len(frames) + 1)) and all("replay=0" in l for l in parse_ok))
    def field(line, key):
        return int(re.search(rf"\b{key}=(-?\d+)", line).group(1))
    j_states = [field(l, "route_state") for l in parse_ok]
    check("armed: Java route_state sequence reaches the hook's final state",
          j_states[-1] == int(updates[-1]) and set(j_states) <= {int(s) for s in updates},
          f"java={sorted(set(j_states))} hook={sorted(set(int(s) for s in updates))}")
    check("armed: Java saw the listed maneuver slots with types",
          any(field(l, "listed_slots") > 0 and field(l, "typed_slots") == field(l, "listed_slots") for l in parse_ok))
    check("armed: Java saw destination and maneuver distances present",
          any(field(l, "dist_dest_present") == 1 and field(l, "dist_maneuver_present") == 1 for l in parse_ok))

    # --- restored ----------------------------------------------------------
    rd, rcollect, rdio, rsi = phase("restored")
    _, _, rreceipts, rcount = audit_phase("restored", rd, rcollect, rdio, rsi, False)
    check("restored: no gate receipt of any process", rcount == 0 and not rreceipts)
    check("restored: RAM verbose marker, Java and hook logs gone (fresh boot)",
          "ABSENT: /tmp/carplay_verbose" in rcollect and "FILE: /tmp/carplay_java.log\nNO_LOG" in rcollect
          and "FILE: /tmp/carplay_hook.log\nNO_LOG" in rcollect)
    check("restored: new SI process (full restart), not the armed SI", rsi != si, f"armed={si} restored={rsi}")

    result["evidence"] = {
        "armed": {"si": si, "dio": dio, "hook_0x5200_sent": sent,
                  "hook_updates": len(updates), "hook_update_states": sorted(set(int(s) for s in updates)),
                  "hook_maneuver_messages": maneuvers, "hook_lane_messages": lanes,
                  "hook_update_window": [times[0], times[-1]] if times else None,
                  "java_parse_ok": len(parse_ok), "java_parse_reject": 0,
                  "java_route_states": sorted(set(j_states)),
                  "java_max_listed_slots": max(field(l, "listed_slots") for l in parse_ok),
                  "java_max_lane_slots": max(field(l, "lane_slots") for l in parse_ok)},
        "restored": {"si": rsi, "dio": rdio},
    }
    result["not_verified"] = [
        "Hook has no per-frame EMIT log; native->Java linkage is by gated-DIO bus owner PID, Java server connection and matching state sequence, not per-frame IDs",
        "Lane guidance through Java: this route produced no 0x5204 lane message (java lane_slots=0); lanes remain harness-tested only",
        "Driving: distance decrement, reroute, arrival (parked run; states 0/3/6 only)",
        "Terminal footer SD_MOUNT_RESTORED / OUTER_EXIT not in returned files; only in-log CONTROL_EXIT and OUTER_EXIT_BEFORE_SD_CLEANUP",
        "Phone / Siri / audio / touch / Android Auto regression: user-reported only, not in logs",
        "Replacement-DIO passive forwarding",
        "arm-time live-DIO guard fix: no DIO was present at arm, so the new detection path did not fire on the vehicle",
    ]
    failed = [c["check"] for c in checks if not c["pass"]]
    result["status"] = "NATIVE_TO_JAVA_INGRESS_AND_ROLLBACK_VERIFIED" if not failed else "FAIL"
    result["failed"] = failed
    REPORT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    for c in checks:
        print(("PASS " if c["pass"] else "FAIL ") + c["check"] + (f"  [{c['detail']}]" if not c["pass"] and c["detail"] else ""))
    print(result["status"])
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
