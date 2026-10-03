#!/usr/bin/env python3
"""Audit the F2 shadow vehicle run from the raw SD output (no road text copied).

Input: resource/private/vehicle-dump/f2-shadow-v1/ (out/ + terminal + OBSERVATIONS)
Output: reports/f2-shadow-vehicle-v1.json
"""
import json
import re
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
PRIVATE = BASE.parent / "private-data" / "mu1320-rgi"
DUMP = BASE.parent / "resource/private/vehicle-dump/f2-shadow-v1"
JDK = (PRIVATE / "tools/jxe2jar/jvms/zulu8.78.0.19-ca-jdk8.0.412-macosx_aarch64/"
       "zulu-8.jdk/Contents/Home/bin/java")
CLASSES = PRIVATE / "f2-shadow-v1/classes"
TEST_CLASSES = PRIVATE / "f2-shadow-v1/test-classes"
FREE_TEXT = re.compile(r"^(current_road|destination|dist_dest_str|dist_maneuver_str|"
                       r"(m|lg)\d+_(name|after_road|distance_str|exit_info|exit_info_hex|lane_desc))$")


def one(pattern):
    found = sorted(DUMP.glob(pattern))
    assert len(found) == 1, (pattern, found)
    return found[0]


def action(kind, phase=None):
    for path in sorted(DUMP.glob(f"action-{kind}-*.txt")):
        text = path.read_text(errors="replace")
        if phase is None or f"F2_COLLECT_BEGIN phase={phase}" in text:
            return text
    raise AssertionError((kind, phase))


def field(line, key):
    return re.search(" " + key + r"=(\S+)", line).group(1)


def main():
    checks = {}

    def check(name, ok, detail=None):
        checks[name] = {"pass": bool(ok), **({"detail": detail} if detail is not None else {})}

    install, arm, rollback = action("install"), action("arm"), action("rollback")
    armed, snapshot, restored = action("collect", "armed"), action("collect", "snapshot"), action("collect", "restored")
    terminal = (DUMP / "terminal_output.txt").read_text(errors="replace")
    check("install_files_passed", "F2_install_FILES_PASSED" in install and "MOUNTS_RESTORED: app=ro system=ro" in install)
    check("arm_after_listener", "ARMED_ONCE" in arm and "SYSTEM_CONFIG: F2_TRIAL" in arm and "ACTIVE_CONFIG: F2_TRIAL" in arm)
    check("rollback_files_passed", "F2_rollback_FILES_PASSED" in rollback and "MOUNTS_RESTORED: app=ro system=ro" in rollback)
    check("terminal_footers", terminal.count("OUTER_EXIT: 0") >= 7 and "OUTER_EXIT: 1" not in terminal
          and terminal.count("SD_MOUNT_RESTORED") >= 7, terminal.count("OUTER_EXIT: 0"))

    receipts = re.findall(r"MU1320_NAVHOOK_V1_GATE mode=(\w+) pid=(\d+) ppid=(\d+)", armed)
    active = [r for r in receipts if r[0] == "ACTIVE_TOKEN_CONSUMED"]
    hook_log = (one("snapshot-*/carplay_hook.log")).read_text(errors="replace")
    owner = re.search(r"bus initialised FORKSAFE owner-pid=(\d+)", hook_log).group(1)
    check("single_token_consumer_is_bus_owner", len(active) == 1 and active[0][1] == owner,
          {"receipts": receipts, "bus_owner": owner})
    check("replacement_dio_passive", all(r[0] == "PASSIVE" for r in receipts if r[1] != owner))
    check("hook_ends_without_disconnect_frame",
          "State cleared: disconnect" not in hook_log and "State cleared: shutdown" not in hook_log,
          "active DIO exited on USB unplug without rgd_clear_state; only socket loss signals it")

    state_armed = one("armed-*/mu1320-f2-state.log").read_bytes()
    state_path = one("snapshot-*/mu1320-f2-state.log")
    cap_path = one("snapshot-*/mu1320-f2-frames.cap")
    check("snapshot_equals_armed_files",
          state_armed == state_path.read_bytes()
          and one("armed-*/mu1320-f2-frames.cap").read_bytes() == cap_path.read_bytes(),
          "no F2 input after the accidental re-plug: the replacement DIO was passive")
    lines = [l for l in state_path.read_text().splitlines() if l.startswith("F2 i=")]
    events = [l for l in lines if " ev=UPDATE " not in l]
    check("no_rejects", not any("ev=REJECT" in l for l in lines), len(lines))

    activations = [l for l in lines if re.search(r"ev=\S*(?<!DE)ACTIVATE", l)]
    ends = [l for l in lines if "ROUTE_END" in field(l, "ev")]
    check("routes_activated", len(activations) == 3, len(activations))
    check("route_end_clears", len(ends) == 3 and all(
        field(l, "act") == "0" and field(l, "dm") == "-1" and field(l, "dd") == "-1"
        and field(l, "ord") == "-" and field(l, "dest") == "0" for l in ends))
    check("activation_starts_without_old_distance", all(field(l, "dd") == "-1" for l in activations))
    first_dd, last_dd, route, prev = [], [], None, None
    for l in lines:
        ev, dd = field(l, "ev"), int(field(l, "dd"))
        if l in activations:
            route = []
        if route is not None and dd >= 0:
            route.append(dd)
        if "ROUTE_END" in ev and route is not None:
            first_dd.append(route[0] if route else None)
            last_dd.append(route[-1] if route else None)
            route = None
    check("next_route_distance_is_new", all(first_dd[i + 1] != last_dd[i] for i in range(len(first_dd) - 1)),
          {"first": first_dd, "last": last_dd})
    arrived = [l for l in lines if "ARRIVED" in field(l, "ev")]
    check("arrival_seen_with_arrived_symbol", len(arrived) == 1 and "sym=MANEUVER:3/0" in arrived[0])
    link = [l for l in lines if "LINK_LOST" in field(l, "ev")]
    check("usb_unplug_link_lost_inactive", len(link) == 1 and field(link[0], "act") == "0")

    drive = [(int(field(l, "t")), int(field(l, "dm")), field(l, "ps"), field(l, "pv"))
             for l in lines if field(l, "act") == "1"]
    primaries = []
    for _, _, ps, pv in drive:
        if ps != "-1" and (not primaries or primaries[-1] != (ps, pv)):
            primaries.append((ps, pv))
    decreasing = 0
    for (t0, d0, p0, v0), (t1, d1, p1, v1) in zip(drive, drive[1:]):
        if (p0, v0) == (p1, v1) and d0 > 0 and d1 > 0 and d1 < d0:
            decreasing += 1
    check("driving_distance_decreases_and_primary_advances", decreasing >= 10 and len(primaries) >= 5,
          {"decreasing_steps": decreasing, "primary_sequence": primaries})
    symbols = {}
    for l in lines:
        s = field(l, "sym")
        symbols[s] = symbols.get(s, 0) + 1
    holds = [int(field(l, "t")) for l in lines if field(l, "sym") == "HOLD"]

    cap = cap_path.read_text(encoding="utf-8")
    leaked, lane_data, showing = [], 0, 0
    for line in cap.splitlines():
        if not line.startswith("@") or " F " not in line:
            continue
        for item in line.split(" ", 4)[-1].split("\x1f"):
            parts = item.split("\t")
            if len(parts) != 3:
                continue
            key, _, value = parts
            if FREE_TEXT.match(key) and value and not value.startswith("~"):
                leaked.append(key)
            if key.startswith("lg") and key.endswith("_index") and value != "-1":
                lane_data += 1
            if key == "lane_guidance_showing" and value == "1":
                showing += 1
    check("capture_has_no_free_text", not leaked, leaked[:5])
    check("lane_0x5204_reached_java_and_validated", lane_data > 0 and "Lane guidance: idx=" in hook_log,
          {"lg_slots_with_data": lane_data, "lane_guidance_showing_1": showing})

    replay = subprocess.run([str(JDK), "-Xverify:all", "-cp", f"{TEST_CLASSES}:{CLASSES}",
                             "com.luka.carplay.rgd.F2Replay", str(cap_path), str(state_path)],
                            capture_output=True, text=True)
    check("host_replay_zero_mismatch", replay.returncode == 0 and "mismatches=0" in replay.stdout,
          replay.stdout.strip())

    check("restored_baseline", "SYSTEM_CONFIG: BASELINE" in restored and "ACTIVE_CONFIG: BASELINE" in restored
          and "JAVA_ARCHIVE: ABSENT" in restored and "NAV_ACTIVE_IGNORE: RETAINED_BASELINE" in restored
          and "GLOBAL_GATE_RECEIPT_COUNT=0" in restored and "DIO_ENV_MARKER=0 DIO_ENV_PRELOAD=0" in restored)
    restored_mem = one("restored-*/DIO-*-mem.txt").read_text(errors="replace")
    check("restored_dio_no_hook_mapping", "libcarplay_hook" not in restored_mem)
    boot = re.search(r"Thu Jan 01 (\d\d:\d\d:\d\d) GMT 1970", restored).group(1)
    si_before = re.search(r"DIRECT_SI_PARENT: dio=\d+ si=(\d+)", armed).group(1)
    si_after = re.search(r"DIRECT_SI_PARENT: dio=\d+ si=(\d+)", restored).group(1)
    check("restored_after_full_restart", boot < "00:05:00" and si_before != si_after,
          {"restored_uptime_clock": boot, "si_armed": si_before, "si_restored": si_after})

    failed = [name for name, item in checks.items() if not item["pass"]]
    report = {
        "status": "F2_SHADOW_STATE_AND_ROLLBACK_VERIFIED" if not failed else "FAIL",
        "failed": failed,
        "inputs": len(lines),
        "event_lines": len(events),
        "symbols": symbols,
        "hold_samples": len(holds),
        "hold_only_within_1s_of_activation": all(
            any(0 <= h - int(field(a, "t")) <= 1000 for a in activations) for h in holds),
        "checks": checks,
        "not_covered_on_vehicle": [
            "USB disconnect while a route is active (link loss arrived 3 s after the arrival route end)",
            "Google Maps: USB was re-plugged by accident, the replacement DIO was passive (one-shot token)",
            "reconnect replay rebuild (one-shot token); covered by host E2E only",
            "REROUTING (state 5) and source_supports_rg=0",
            "lane selection for output: primary maneuvers carried no linked lane slot; F3 must port upstream selection",
        ],
    }
    out = BASE / "reports/f2-shadow-vehicle-v1.json"
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(report["status"], "failed:", failed)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
