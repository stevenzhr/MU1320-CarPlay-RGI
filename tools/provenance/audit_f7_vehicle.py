#!/usr/bin/env python3
"""Audit the returned F7 v2 vehicle run (Toolbox menu + sessions Q/D/R) from the raw SD output.

Input:  resource/private/vehicle-dump/f7-daily-v2/ (out/ action logs + snapshots + OBSERVATIONS-F7.txt)
Output: reports/f7-daily-v2-vehicle.json

Action logs carry no wall clock (the unit runs on 1970 time), so boots are grouped by the
smartphone_integrator pid (gate receipt ppid) or, for actions without a receipt, by the
/tmp gate record they print (/tmp is cleared by every reboot).
"""
import json
import re
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
PRIVATE = BASE.parent / "private-data" / "mu1320-rgi"
DUMP = BASE.parent / "resource/private/vehicle-dump/f7-daily-v2"
JDK = PRIVATE / "tools/jxe2jar/jvms/zulu8.78.0.19-ca-jdk8.0.412-macosx_aarch64/zulu-8.jdk/Contents/Home/bin"
JAVA = PRIVATE / "f7-daily-v2-java"
STOCK_JAR = PRIVATE / "MU1320-base.jar"
MARKER = "MU1320_F7_TRIAL=mu1320_f7_v2_773045ab"
GEM_LD = "ld=/mnt/app/eso/hmi/graphics:"          # menu (GEM) caller; SSH shows /net/mmx paths
RECEIPT = re.compile(r"MU1320_F7_GATE mode=(\w+) reason=(\w+) pid=(\d+) ppid=(\d+) strikes=(\d+) prev=(\d+) prev_alive=(\d)")


def actions(kind):
    return {p.stem.split("-")[-1]: p.read_text(errors="replace") for p in sorted(DUMP.glob(f"action-{kind}-*.txt"))}


def field(text, name):
    m = re.search(rf"^{name}: (.*)$", text, re.M)
    return m.group(1) if m else None


def receipts(text):
    seen, out = set(), []
    for r in RECEIPT.findall(text):
        if r[2] not in seen:
            seen.add(r[2])
            out.append({"mode": r[0], "reason": r[1], "pid": int(r[2]), "ppid": int(r[3]),
                        "strikes": int(r[4]), "prev": int(r[5])})
    return out


def lines(path, tag):
    out = []
    for line in path.read_text(errors="replace").splitlines():
        m = re.match(rf"{tag} i=(\d+) t=(\d+) (.*)$", line)
        if m:
            out.append((int(m.group(1)), int(m.group(2)), m.group(3)))
    return out


def main():
    checks = {}

    def check(name, ok, detail=None):
        checks[name] = {"pass": bool(ok), **({"detail": detail} if detail is not None else {})}

    st, ins, col = actions("status"), actions("install"), actions("collect")
    stop, rb, purge = actions("stop"), actions("rollback"), actions("purge")
    every = {f"{k}-{n}": t for k, d in [("status", st), ("install", ins), ("collect", col), ("stop", stop),
                                        ("rollback", rb), ("purge", purge)] for n, t in d.items()}

    # ---- menu + transactions --------------------------------------------------
    check("all_actions_exit_0", all("CONTROL_EXIT=0" in t and "OUTER_EXIT_BEFORE_SD_CLEANUP=0" in t
                                    and "SD_INITIAL=ro" in t for t in every.values()), sorted(every))
    check("all_actions_expected_marker", all(f"EXPECTED_MARKER: {MARKER}" in t for t in every.values()))
    menu = {k for k, t in every.items() if GEM_LD in t}
    check("menu_env_sanitized", all(field(every[k], "RUN_ENV").startswith(f"cwd=/ umask=022 {GEM_LD}")
                                    and not re.search(r"ld=(\.|.*:\.)", field(every[k], "RUN_ENV")) for k in menu),
          {"menu": sorted(menu), "ssh": sorted(set(every) - menu)})
    check("purge_via_ssh_only", set(every) - menu == {k for k in every if k.startswith("purge-")})
    base = [n for n, t in st.items() if field(t, "SYSTEM_CONFIG") == "BASELINE"]
    check("baseline_status", base and all(field(st[n], "JAVA_LISTENER") == "ABSENT"
                                          and field(st[n], "NAV_ACTIVE_IGNORE") == "ACTIVE_BASELINE" for n in base), base)
    fresh = [n for n, t in ins.items() if "RESUME_WORKSPACE" not in t]
    resume = [n for n, t in ins.items() if "RESUME_WORKSPACE" in t]
    check("install_fresh_passed", len(fresh) == 1 and "F7_install_FILES_PASSED" in ins[fresh[0]]
          and "STAGE1_LOADER_PASSED" in ins[fresh[0]] and "MOUNTS_RESTORED: app=ro system=ro" in ins[fresh[0]], fresh)
    check("install_resume_all_exact", len(resume) == 1 and "F7_install_FILES_PASSED" in ins[resume[0]]
          and len(re.findall(r"install_STEP: .* already exact", ins[resume[0]])) == 13, resume)
    i2 = [n for n, t in st.items() if field(t, "SYSTEM_CONFIG") == "F7_TRIAL" and field(t, "GATE_LAST") == "ABSENT"]
    check("after_restart_status_trial_ready", i2 and all(field(st[n], "JAVA_LISTENER") == "F7_READY" for n in i2), i2)

    # ---- boots ----------------------------------------------------------------
    boots = {}
    for n, t in col.items():
        rc = receipts(t)
        if rc:
            boots.setdefault(rc[0]["ppid"], []).append(n)
    snap = {n: DUMP / re.search(r"SAVED_ON_SD: \S+/(snapshot-\d+)", t).group(1) for n, t in col.items()}

    # ---- session Q: B11 crash guard ------------------------------------------
    qcol = next(n for n, t in col.items() if "CRASH_GUARD" in t)
    chain = receipts(col[qcol])
    modes = [(r["mode"], r["reason"], r["strikes"]) for r in chain]
    check("b11_crash_guard_on_vehicle",
          modes[:5] == [("ACTIVE", "ON", 0), ("ACTIVE", "ON", 0), ("ACTIVE", "ON", 1), ("ACTIVE", "ON", 2),
                        ("PASSIVE", "CRASH_GUARD", 3)] and all(m[1] == "CRASH_GUARD" for m in modes[5:])
          and "GATE_RECORD: /tmp/mu1320-f7-gate.strikes 3" in col[qcol], modes)
    q2 = [n for n, t in st.items() if field(t, "GATE_STRIKES") == "3"]
    check("q2_status_shows_strikes_3", q2, q2)
    check("strikes_reset_by_reboot", all(receipts(col[ns[0]])[0]["strikes"] == 0 for ns in boots.values()))

    # ---- session Q: B12 stop -------------------------------------------------
    (sn, s), = stop.items()
    order = [l.split(":")[0] for l in s.splitlines()
             if l.startswith(("JAVA_RELEASE", "JAVA_CLUSTER_CONTEXT", "RENDERER_STOP", "DISARM_CLUSTER_CONTEXT", "F7_STOPPED"))]
    check("b12_stop_releases_through_java_first",
          order == ["JAVA_RELEASE", "JAVA_CLUSTER_CONTEXT", "RENDERER_STOP", "DISARM_CLUSTER_CONTEXT", "F7_STOPPED"]
          and "JAVA_RELEASE: BAP_OFF" in s and "CLUSTER_ON_80" not in s, order)
    qb = lines(snap[qcol] / "mu1320-f5-bap.log", "B")
    kill = [(i, t) for i, t, b in qb if b == "GATE kill=1"]
    check("b12_java_saw_kill_switch", len(kill) == 1, kill)
    active, last = False, None
    for i, t, b in qb:
        if b.startswith("START "):
            active = True
        elif b.startswith("TEARDOWN "):
            active, last = False, (i, t)
    stop_at = kill[0][1] if kill else None
    after = col[qcol]
    check("after_stop_stock_cluster", field(after, "F7_RENDERER") == "ABSENT"
          and field(after, "DM_CLUSTER_CONTEXT").startswith("74 list=[20 102 101 33]")
          and field(after, "DM_DISPLAYABLES").startswith("d98=ABSENT") and field(after, "KEEPER_LAST") == "KEEP HELD hold")
    observed = {"q_boot_ppid": chain[0]["ppid"], "q_boot_wall_clock": "2026-09-27 20:36-20:37 (SI dump reasons)",
                "bap_active_when_stop_pressed": active,
                "last_bap_teardown_before_stop_ms": (stop_at - last[1]) if last and stop_at else None,
                "q2_status_boot_gate_last": field(st[q2[0]], "GATE_LAST") if q2 else None}

    # ---- session D: daily boots ----------------------------------------------
    daily = {}
    for ppid, ns in boots.items():
        t = col[max(ns, key=lambda n: len(col[n]))]
        sdir = snap[max(ns, key=lambda n: len(col[n]))]
        bap = [b for _, _, b in lines(sdir / "mu1320-f5-bap.log", "B")]
        ren = [b for _, _, b in lines(sdir / "mu1320-f5-render.log", "R")]
        daily[ppid] = {
            "collects": sorted(ns), "dio": [r["pid"] for r in receipts(t)],
            "starts": sum(b.startswith("START ") for b in bap), "teardowns": sum(b.startswith("TEARDOWN ") for b in bap),
            "faults": sum(b.startswith("FAULT") for b in bap), "lanes": sum(b.startswith("CALL LANES") for b in bap),
            "arrived": "ARRIVED" in (sdir / "mu1320-f5-state.log").read_text(errors="replace"),
            "takes": sum(b.startswith("TAKE ") for b in ren), "releases": sum(b.startswith("RELEASE ") for b in ren),
            "bad_render": [b for b in ren if b.startswith(("TAKE_FAILED", "FIGHT_STOP", "DISPLAY fail"))],
            "keeper_ready": "KEEP READY" in (field(t, "KEEPER_LAST") or ""), "gestures": int(re.search(r"F7_TOUCH_COUNT\[ GESTURE \]=(\d+)", t).group(1)),
        }
    driven = {p: d for p, d in daily.items() if d["starts"] and p != chain[0]["ppid"]}
    check("d_at_least_2_cold_boots_auto", len(driven) >= 2 and all(d["keeper_ready"] for d in driven.values()),
          sorted(driven))
    check("d_no_faults_balanced", all(d["faults"] == 0 and not d["bad_render"] and d["starts"] == d["teardowns"]
                                      and d["releases"] == d["starts"] for d in daily.values()))
    check("d_no_rejects", all("F7_STATE_COUNT[ev=REJECT]=0" in t for t in col.values()))
    check("d_lanes_and_arrival_seen", any(d["lanes"] for d in driven.values()) and any(d["arrived"] for d in driven.values()))

    # Arrival: the last bargraph countdown before ARRIVED strictly decreasing (B9 on the car).
    arr = next(snap[n] for n in col if "F7_STATE_COUNT[ARRIVED]=1" in col[n])
    ab = lines(arr / "mu1320-f5-bap.log", "B")
    arr_i = next(int(m.group(1)) for m in re.finditer(r"F2 i=(\d+) \S+ ev=ARRIVED", (arr / "mu1320-f5-state.log").read_text()))
    bars = [int(m.group(1)) for i, _, b in ab if i <= arr_i for m in [re.match(r"CALL DIST_TURN \d+ bar=(-?\d+)", b)] if m]
    bars = bars[max([k for k in range(1, len(bars)) if bars[k] > bars[k - 1] + 20] or [0]):]   # last countdown
    check("b9_arrival_bar_decreasing", len(bars) >= 10 and all(y < x for x, y in zip(bars, bars[1:])), bars)

    # Java replay of every returned capture against the F7 v2 classes.
    args = []
    for n in sorted(col):
        if (snap[n] / "mu1320-f5-frames.cap").stat().st_size:
            args += ["--", snap[n].name, str(snap[n] / "mu1320-f5-frames.cap"), str(snap[n] / "mu1320-f5-bap.log")]
    rp = subprocess.run([str(JDK / "java"), "-Xverify:all", "-cp", f"{JAVA / 'host'}:{JAVA / 'classes'}:{STOCK_JAR}",
                         "com.luka.carplay.rgd.F6V3Replay"] + args, capture_output=True, text=True)
    res = re.findall(r"F6V3_REPLAY \[(\S+)\] inputs=(\d+) strict_lines=(\d+) strict_mismatches=(\d+)", rp.stdout)
    check("replay_all_captures_0_mismatch", rp.returncode == 0 and "F6V3_REPLAY_PASS" in rp.stdout
          and len(res) == len(args) // 4 and all(r[3] == "0" for r in res), [" ".join(r) for r in res])
    lanes = re.findall(r"LANE_EPISODES \[(\S+)\] total=(\d+) on=(\d+) from_memory=(\d+)", rp.stdout)
    check("lanes_all_live", all(t == o and m == "0" for _, t, o, m in lanes), lanes)

    slogs = {p.parent.name: p.read_text(errors="replace") for p in DUMP.glob("snapshot-*/sloginfo.txt")}
    check("no_java_linkage_errors", not any(re.search(r"(?i)verifyerror|linkageerror|noclassdef|incompatibleclass", s)
                                            for s in slogs.values()))
    dumps = {k: re.findall(r"appState=(\w+) pid=(\d+)", s) for k, s in slogs.items()}
    check("only_rapid_replug_dio_dumps", all(not d for k, d in dumps.items() if k != snap[qcol].name)
          and all(a == "TIMEOUT_SHUTDOWN" for a, _ in dumps[snap[qcol].name]), dumps[snap[qcol].name])

    # ---- session R ------------------------------------------------------------
    r_idle = [n for n, t in rb.items() if field(t, "GATE_LAST") == "ABSENT"]
    check("r1_rollback_usb_disconnected", len(r_idle) == 1 and "F7_rollback_FILES_PASSED" in rb[r_idle[0]]
          and "move quarantined NavActiveIgnore back" in rb[r_idle[0]], r_idle)
    check("all_rollbacks_release_java_first", all("JAVA_RELEASE: BAP_OFF" in t and "F7_rollback_FILES_PASSED" in t
                                                  for t in rb.values()))
    (pn, p), = purge.items()
    check("purge_passed", "F7_PURGED: runtime workspace removed" in p and "F7_purge_FILES_PASSED" in p
          and field(p, "SYSTEM_CONFIG") == "BASELINE" and field(p, "JAVA_ARCHIVE") == "ABSENT")
    post_rb = [n for n, t in col.items() if field(t, "SYSTEM_CONFIG") == "BASELINE"]
    same_boot_purge = [n for n, t in rb.items() if field(t, "GATE_LAST") == field(p, "GATE_LAST") != "ABSENT"]
    observed.update({
        "r1_collect_before_restart": [n for n in post_rb if field(col[n], "JAVA_LISTENER") == "F7_READY"],
        "r2_install_before_restart": [n for n in resume if field(ins[n], "JAVA_LISTENER") == "F7_READY"],
        "purge_same_boot_as_rollback": same_boot_purge,
        "daily": {str(k): v for k, v in daily.items()},
    })

    passed = all(c["pass"] for c in checks.values())
    report = {
        "status": "F7_V2_VEHICLE_VERIFIED" if passed else "F7_V2_VEHICLE_AUDIT_FAILED",
        "passed": sum(c["pass"] for c in checks.values()), "total": len(checks),
        "checks": checks, "observations": observed,
        "not_verified": [
            "B12 with guidance on screen: in the only stop log BAP had been idle since the last teardown",
            "Q2 last step (rm strikes, guidance back) inside the same boot",
            "R1 status/CarPlay after a full restart, R3 interrupted install",
            "which app (Apple/Google) each boot used",
        ],
    }
    (BASE / "reports/f7-daily-v2-vehicle.json").write_text(json.dumps(report, indent=2) + "\n")
    print(report["status"], f"{report['passed']}/{report['total']}")
    for name, c in checks.items():
        if not c["pass"]:
            print("FAIL", name, c.get("detail"))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
