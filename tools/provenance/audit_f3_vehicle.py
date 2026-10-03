#!/usr/bin/env python3
"""Audit the F3 v2 BAP vehicle run from the raw SD output (no road text copied).

Input:  resource/private/vehicle-dump/f3-bap-v2/ (out/ action logs + collections + OBSERVATIONS)
Output: reports/f3-bap-vehicle-v2.json
"""
import json
import re
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
PRIVATE = BASE.parent / "private-data" / "mu1320-rgi"
DUMP = BASE.parent / "resource/private/vehicle-dump/f3-bap-v2"
JDK = PRIVATE / "tools/jxe2jar/jvms/zulu8.78.0.19-ca-jdk8.0.412-macosx_aarch64/zulu-8.jdk/Contents/Home/bin"
BUILD = PRIVATE / "f3-bap-v2"
TOOL = PRIVATE / "f3-replay-tool"
STOCK_JAR = PRIVATE / "MU1320-base.jar"


def one(pattern):
    found = sorted(DUMP.glob(pattern))
    assert len(found) == 1, (pattern, found)
    return found[0]


def actions(kind):
    return [p.read_text(errors="replace") for p in sorted(DUMP.glob(f"action-{kind}-*.txt"))]


def collect(phase):
    for text in actions("collect"):
        if f"F3_COLLECT_BEGIN phase={phase}" in text:
            return text
    raise AssertionError(phase)


def bap_lines(path):
    out = []
    for line in path.read_text().splitlines():
        m = re.match(r"B i=(\d+) t=(\d+) (.*)$", line)
        if m:
            out.append((int(m.group(1)), int(m.group(2)), m.group(3)))
    return out


def main():
    checks = {}

    def check(name, ok, detail=None):
        checks[name] = {"pass": bool(ok), **({"detail": detail} if detail is not None else {})}

    # ---- transactions ----------------------------------------------------------
    install, = actions("install")
    arm, = actions("arm")
    rollback, = actions("rollback")
    check("install_files_passed", "F3_install_FILES_PASSED" in install and "CONTROL_EXIT=0" in install)
    check("arm_after_listener", "ARMED_ONCE" in arm and "NAV_ACTIVE_IGNORE: QUARANTINED" in arm
          and "SYSTEM_CONFIG: F3_TRIAL" in arm and "ACTIVE_CONFIG: F3_TRIAL" in arm)
    check("rollback_files_passed", "F3_rollback_FILES_PASSED" in rollback and "CONTROL_EXIT=0" in rollback
          and "move quarantined NavActiveIgnore back" in rollback)
    check("all_actions_control_exit_0",
          all("CONTROL_EXIT=0" in t for k in ["install", "arm", "rollback", "status", "collect"] for t in actions(k)))

    armed, snapshot, restored = collect("armed"), collect("snapshot"), collect("restored")
    receipts = re.findall(r"MU1320_NAVHOOK_V1_GATE mode=(\w+) pid=(\d+) ppid=(\d+)", armed)
    check("single_token_consumer", len({r for r in receipts if r[0] == "ACTIVE_TOKEN_CONSUMED"}) == 1
          and "DIO_ENV_MARKER=1 DIO_ENV_PRELOAD=1" in armed, sorted(set(receipts)))
    check("restored_baseline",
          re.search(r"2960431692\s+2645 /mnt/app/eso/hmi/lsd/jars/NavActiveIgnore.jar", restored) is not None
          and "CarPlayRGI-MU1320-F3BapV2.jar: No such file" in restored
          and "quarantine/NavActiveIgnore.jar: No such file" in restored
          and "DIO_ENV_MARKER=0 DIO_ENV_PRELOAD=0" in restored and "GLOBAL_GATE_RECEIPT_COUNT=0" in restored)
    slog = one("snapshot-*/sloginfo.txt").read_text(errors="replace")
    check("no_java_linkage_errors_in_sloginfo",
          not re.search(r"(?i)verifyerror|linkageerror|noclassdef|incompatibleclass", slog))

    # ---- replays -----------------------------------------------------------------
    snap = one("snapshot-*/mu1320-f3-bap.log").parent
    armed_dir = one("armed-*/mu1320-f3-bap.log").parent
    arm_bytes = (armed_dir / "mu1320-f3-bap.log").read_bytes()
    check("armed_log_is_prefix_of_snapshot", (snap / "mu1320-f3-bap.log").read_bytes().startswith(arm_bytes))
    TOOL.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(JDK / "javac"), "-source", "1.8", "-target", "1.8", "-Xlint:-options", "-nowarn",
                    "-cp", f"{BUILD / 'classes'}:{STOCK_JAR}", "-d", str(TOOL),
                    str(BASE / "f2-src/F2Replay.java"), str(BASE / "f3-src/F3Replay.java")], check=True)
    replay = subprocess.run([str(JDK / "java"), "-cp", f"{TOOL}:{BUILD / 'classes'}:{STOCK_JAR}",
                             "com.luka.carplay.rgd.F3Replay", str(snap / "mu1320-f3-frames.cap"),
                             str(snap / "mu1320-f3-bap.log"), str(snap / "mu1320-f3-state.log")],
                            capture_output=True, text=True)
    out = replay.stdout
    check("state_replay_0_mismatch", "F3_STATE_REPLAY inputs=370 compared=370 mismatches=0" in out, out.splitlines()[:1])
    gated = re.search(r"F3_BAP_GATED_REPLAY vehicle_lines=(\d+) replay_lines=(\d+) compared=(\d+) mismatches=(\d+)", out)
    check("bap_gated_replay_whole_session_0_mismatch", replay.returncode == 0 and gated and gated.group(4) == "0"
          and gated.group(1) == gated.group(2), gated.group(0) if gated else out)

    # ---- BAP behaviour -----------------------------------------------------------
    lines = bap_lines(snap / "mu1320-f3-bap.log")
    bodies = [b for _, _, b in lines]
    state = [l for l in (snap / "mu1320-f3-state.log").read_text().splitlines() if l.startswith("F2 i=")]
    check("no_rejects_no_faults", not any("ev=REJECT" in l for l in state) and not any(b.startswith("FAULT") for b in bodies))
    check("bound_to_appconnectornavi", any(b.startswith("BIND ok service=de.audi.app.combi.bap.app.navi.AppConnectorNavi")
                                           for b in bodies) and not any(b.startswith("BIND fail") for b in bodies))
    starts = [b for b in bodies if b.startswith("START ")]
    teardowns = [b.split("reason=")[1] for b in bodies if b.startswith("TEARDOWN ")]
    check("starts_and_releases_balanced", len(starts) == len(teardowns) + sum(b.startswith("RELEASE_SILENT") for b in bodies),
          {"starts": len(starts), "teardowns": teardowns})

    # Yield: no BAP call while the last observed stock rg_active was not 0.
    rg, violations, persistent_while_idle = -1, [], False
    for i, t, b in lines:
        m = re.match(r"STOCK rg_active=(-?\d+) persistent_route=(-?\d+)", b)
        if m:
            rg = int(m.group(1))
            if rg == 0 and m.group(2) == "1":
                persistent_while_idle = True
        elif b.startswith("CALL ") and rg != 0:
            violations.append((i, t, b))
    check("no_bap_call_while_stock_guidance_active_or_unknown", not violations, violations[:5])
    check("v1_root_cause_confirmed_persistent_route_while_idle", persistent_while_idle)
    holds = [b for b in bodies if b.startswith("HOLD_OFF reason=STOCK_ROUTE")]
    check("stock_first_hold_off", len(holds) >= 1, holds)

    # Step 6: CarPlay route ended by the stock start; order of F3 teardown vs stock rgActive.
    td = [(i, t) for i, t, b in lines if b.startswith("TEARDOWN reason=ROUTE_END")]
    rg_on = [t for i, t, b in lines if b.startswith("STOCK rg_active=1")]
    step6 = next(((i, t, rg_on[0] - t) for i, t in td if rg_on and 0 < rg_on[0] - t < 5000), None)
    check("step6_teardown_before_stock_guidance", step6 is not None,
          {"input": step6[0], "stock_rg_active_after_ms": step6[2]} if step6 else None)

    # Kill switch: teardown at kill=1, nothing until kill=0.
    kill_on = next(k for k, (_, _, b) in enumerate(lines) if b == "GATE kill=1")
    kill_off = next(k for k, (_, _, b) in enumerate(lines) if b == "GATE kill=0")
    between = [b for _, _, b in lines[kill_on + 1:kill_off]]
    check("kill_switch_teardown_then_silent", lines[kill_on + 1][2] == "TEARDOWN reason=KILL_SWITCH"
          and not any(b.startswith(("CALL RG_STATUS 1", "START")) for b in between),
          {"restart_after_ms": next(t for _, t, b in lines[kill_off:] if b.startswith("START")) - lines[kill_off][1]})
    check("link_lost_during_active_route_tears_down", teardowns and teardowns[-1] == "LINK_LOST+DEACTIVATE")

    # Driven route: turns, bar countdown.
    descr = [b for b in bodies if b.startswith("CALL DESCRIPTOR ")]
    bars = [(i, int(re.search(r"DIST_TURN (\d+) bar=(\d+)", b).group(1)), int(re.search(r"bar=(\d+)", b).group(1)))
            for i, _, b in lines if re.match(r"CALL DIST_TURN \d+ bar=\d+", b)]
    # A new countdown starts when the distance jumps up by more than 20 m (next
    # maneuver); rises of <= 5 m inside a countdown are GPS jitter and counted.
    runs, cur, jitter = [], [], 0
    for item in bars:
        if cur and item[1] > cur[-1][1] + 20:
            runs.append(cur)
            cur = []
        elif cur and item[1] > cur[-1][1]:
            jitter += 1
        cur.append(item)
    if cur:
        runs.append(cur)
    monotone = all(all(b[1] <= a[1] + 5 for a, b in zip(r, r[1:])) for r in runs)
    check("turn_symbols_published", {"CALL DESCRIPTOR 13/192", "CALL DESCRIPTOR 13/64"} <= set(descr),
          sorted(set(descr)))
    check("bargraph_countdowns_monotone", len(runs) >= 3 and monotone and jitter <= 3,
          {"jitter_rises_le_5m": jitter, "runs": [{"from_m": r[0][1], "to_m": r[-1][1], "bar": [r[0][2], r[-1][2]], "samples": len(r)} for r in runs]})
    check("start_route_follow_street", sum("sr=1" in s for s in starts) >= 1 and "CALL DESCRIPTOR 13/0" not in descr)

    obs = one("OBSERVATIONS*.txt").read_text(errors="replace")
    observed = {
        "vc_arrow": "arrow=show" in obs,
        "hud_arrow_and_distance_ft": "100ft" in obs,
        "vc_distance_to_destination_shown": "dist to dest=not show" not in obs,
        "route_end_clear_s": 1, "unplug_clear_s": 2, "kill_clear_s": 1,
        "stock_guidance_kept_during_yield": "stock arrow shown and kept" in obs,
        "stock_first_display": "stock" if "(stock/CarPlay/none)=stock" in obs else "?",
    }
    check("observations_vc_hud_arrow", observed["vc_arrow"] and observed["hud_arrow_and_distance_ft"])
    check("observations_yield_kept_stock", observed["stock_guidance_kept_during_yield"]
          and observed["stock_first_display"] == "stock")

    passed = all(c["pass"] for c in checks.values())
    report = {
        "status": "F3_BAP_OUTPUT_AND_ROLLBACK_VERIFIED" if passed else "F3_BAP_VEHICLE_AUDIT_FAILED",
        "passed": sum(c["pass"] for c in checks.values()),
        "total": len(checks),
        "checks": checks,
        "observations": observed,
        "call_counts": {name: sum(b.startswith("CALL " + name) for b in bodies)
                        for name in ["RG_STATUS", "RG_TYPE", "DESCRIPTOR", "EXIT_VIEW", "DIST_TURN",
                                     "MANEUVER_STATE", "DIST_DEST"]},
        "not_verified": [
            "terminal_output.txt not returned: SD_MOUNT_RESTORED/OUTER_EXIT footers only via CONTROL_EXIT in action logs",
            "arrival symbol, lanes, ETA, roundabouts/exits, reroute, Google Maps/Waze",
            "VC distance-to-destination (FctID 21 sent; not displayed)",
        ],
    }
    out_path = BASE / "reports/f3-bap-vehicle-v2.json"
    out_path.write_text(json.dumps(report, indent=2) + "\n")
    print(report["status"], f"{report['passed']}/{report['total']}")
    for name, c in checks.items():
        if not c["pass"]:
            print("FAIL", name, c.get("detail"))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
