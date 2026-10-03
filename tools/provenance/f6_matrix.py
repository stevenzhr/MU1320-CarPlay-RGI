#!/usr/bin/env python3
"""F6 support matrix from F5-format vehicle collections.

Input: one or more collect directories (armed-*/snapshot-*), each holding the
F5 Java logs copied by collect_f5.sh:

  mu1320-f5-frames.cap   sanitized iAP2 frame diffs (source_name kept)
  mu1320-f5-state.log    RouteStateCore line per input (numbers only)
  mu1320-f5-bap.log      BAP calls per input
  mu1320-f5-render.log   cluster context takeovers per input

plus, optionally, the SD `out/f6-marks.txt` written by f6_mark.sh.

All four logs share the input counter i, so every BAP call and cluster action
is attributed to the route (and navigation app) whose frame caused it.  Routes
are split at route end (route_state 0), link loss, a new session, or a change
of source app while a route is active (app switch).

Per route, and then per app, each field gets one of:

  SENT            the app provided it and F5 sent it to the BAP/renderer
  APP_NOT_PROVIDED routes of this app ran long enough but the field never came
  NOT_EXERCISED   no route of this app reached the situation (e.g. no lanes)
  NOT_SENT        the app provided it but F5 did not send it (a defect)

Whether the VC/HUD actually *showed* a field is not in any log; that column
comes from the observation sheet and photos.  Output: markdown and JSON.
"""
import argparse
import json
import re
import sys
from collections import Counter, OrderedDict
from pathlib import Path

# iAP2 RouteGuidanceManeuver types (upstream ManeuverMapper.MT_*).
MT = {
    0: "NO_TURN", 1: "LEFT", 2: "RIGHT", 3: "STRAIGHT", 4: "U_TURN", 5: "FOLLOW_ROAD",
    6: "ENTER_ROUNDABOUT", 7: "EXIT_ROUNDABOUT", 8: "OFF_RAMP", 9: "ON_RAMP",
    10: "ARRIVE_END_OF_NAV", 11: "START_ROUTE", 12: "ARRIVE", 13: "KEEP_LEFT", 14: "KEEP_RIGHT",
    15: "ENTER_FERRY", 16: "EXIT_FERRY", 17: "CHANGE_FERRY", 18: "START_ROUTE_U_TURN",
    19: "U_TURN_AT_ROUNDABOUT", 20: "LEFT_AT_END", 21: "RIGHT_AT_END",
    22: "HIGHWAY_OFF_RAMP_LEFT", 23: "HIGHWAY_OFF_RAMP_RIGHT", 24: "ARRIVE_LEFT",
    25: "ARRIVE_RIGHT", 26: "U_TURN_WHEN_POSSIBLE", 27: "ARRIVE_END_OF_DIRECTIONS",
    47: "SHARP_LEFT", 48: "SHARP_RIGHT", 49: "SLIGHT_LEFT", 50: "SLIGHT_RIGHT",
    51: "CHANGE_HIGHWAY", 52: "CHANGE_HIGHWAY_LEFT", 53: "CHANGE_HIGHWAY_RIGHT",
}
for _n in range(1, 20):
    MT[27 + _n] = "ROUNDABOUT_EXIT_%d" % _n

CATEGORY = OrderedDict([
    ("turn", {1, 2, 20, 21, 47, 48, 49, 50}),
    ("keep", {13, 14}),
    ("roundabout", {6, 7, 19} | set(range(28, 47))),
    ("ramp_exit", {8, 9, 22, 23, 51, 52, 53}),
    ("u_turn", {4, 18, 26}),
    ("arrive", {10, 12, 24, 25, 27}),
    ("ferry", {15, 16, 17}),
])

# iAP2 RouteGuidanceUpdate distance display units.
UNITS = {"0": "km", "1": "mi", "2": "m", "3": "yd", "4": "ft"}
ROUTE_STATES = {0: "NO_ROUTE", 1: "ROUTE_SET", 2: "ARRIVED", 3: "LOADING", 4: "LOCATING",
                5: "REROUTING", 6: "PROCEED_TO_ROUTE"}

# A route shorter than this cannot prove that an app withholds a field.
MIN_ROUTE_S = 20.0

LINE = re.compile(r"^([A-Z0-9]+) i=(\d+) t=(\d+) (.*)$")


def parse_capture(path):
    """Per input i: (t, snapshot dict of the fields F6 looks at, event name or None)."""
    frame = {}
    out = OrderedDict()
    capped = False
    with open(path, encoding="utf-8", errors="replace") as stream:
        for raw in stream:
            line = raw.rstrip("\n")
            if line.startswith("#CAPTURE_CAP_REACHED"):
                capped = True
                break
            if not line.startswith("@"):
                continue
            head = line.split(" ", 3)
            if len(head) < 4:
                raise ValueError("bad capture line: %r" % line[:80])
            i = int(head[0][1:])
            t = int(head[1])
            if head[2] == "E":
                if head[3] in ("SESSION", "LINK_LOST"):
                    frame.clear()
                out[i] = (t, {}, head[3])
                continue
            diff = head[3].split(" ", 1)[1]
            if diff not in ("=", "!"):
                for item in diff.split("\x1f"):
                    if item.startswith("-"):
                        frame.pop(item[1:], None)
                        continue
                    parts = item.split("\t", 2)
                    if len(parts) != 3:
                        raise ValueError("bad diff item at @%d" % i)
                    frame[parts[0]] = parts[2]
            keep = {k: frame[k] for k in (
                "source_name", "route_state", "eta_seconds", "time_remaining_seconds",
                "dist_dest_m", "dist_dest_units", "dist_maneuver_m", "dist_maneuver_units",
                "lane_guidance_total", "lane_guidance_showing", "lane_guidance_index", "visible_in_app")
                if k in frame}
            # B8: does the snapshot carry lane data for the active lane event?
            li = frame.get("lane_guidance_index")
            keep["lane_data"] = "1" if li not in (None, "") and any(
                frame.get("lg%d_index" % s) == li for s in range(32)) else "0"
            out[i] = (t, keep, None)
    return out, capped


def parse_log(path, tag):
    rows = []
    if not path.exists():
        return rows
    with open(path, encoding="utf-8", errors="replace") as stream:
        for raw in stream:
            m = LINE.match(raw.rstrip("\n"))
            if m and m.group(1) == tag:
                rows.append((int(m.group(2)), int(m.group(3)), m.group(4)))
    return rows


def kv(text):
    return dict(p.split("=", 1) for p in text.split() if "=" in p)


def parse_state(path):
    out = OrderedDict()
    for i, t, body in parse_log(path, "F2"):
        out[i] = (t, kv(body))
    return out


def parse_marks(path):
    marks = []
    if not path or not Path(path).exists():
        return marks
    cur = None
    for raw in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        if re.match(r"F[67]MARK step=", raw):  # F7 v1.1 f7_mark.sh writes F7MARK blocks
            m = re.match(r"F[67]MARK step=(\S+) note=(.*)$", raw)
            cur = {"step": m.group(1), "note": m.group(2).strip()}
        elif cur is not None and raw.startswith("DATE: "):
            cur["date"] = raw[6:]
        elif cur is not None and raw.startswith("EPOCH: "):
            cur["epoch"] = raw[7:]
        elif cur is not None and raw.startswith("LAST mu1320-f5-state.log: "):
            m = LINE.match(raw.split(": ", 1)[1])
            cur["state_i"] = int(m.group(2)) if m else None
            cur["state_t"] = int(m.group(3)) if m else None
        elif cur is not None and raw in ("F6MARK_END", "F7MARK_END"):
            marks.append(cur)
            cur = None
    return marks


class Route:
    def __init__(self, app, i, t):
        self.app = app
        self.first_i = i
        self.last_i = i
        self.t0 = t
        self.t1 = t
        self.end = "OPEN"
        self.switched_from = None
        self.states = Counter()
        self.transitions = []
        self.types = Counter()
        self.units = Counter()
        self.provided = Counter()
        self.dm_decrease = 0
        self.bap = Counter()
        self.eta_src = Counter()
        self.lanes_on = 0
        self.lane_episodes = []   # [first_i, last_i, lane index, data seen]
        self.render = Counter()
        self.reroute_clears = 0
        self.arrived_t = None
        self.marks = []

    def seconds(self):
        return (self.t1 - self.t0) / 1000.0


def build_routes(cap, state, bap, render):
    routes = []
    cur = None
    prev_rs = 0
    prev_dm = None
    prev_pt = None
    owner = {}
    prev_i = None
    lanes_calls = []
    for i, (t, snap, event) in cap.items():
        st = state.get(i, (t, {}))[1]
        rs = int(st.get("rs", snap.get("route_state", "0") or 0))
        app = snap.get("source_name")
        ended = event is not None or rs <= 0
        if cur is not None and (ended or (app and cur.app and app != cur.app)):
            cur.end = event or ("APP_SWITCH" if not ended else "ROUTE_END")
            if cur.end == "APP_SWITCH":
                nxt = Route(app, i, t)
                nxt.switched_from = cur.app
                routes.append(cur)
                cur = nxt
            else:
                # The closing input's teardown/release belongs to this route.
                owner[i] = cur
                routes.append(cur)
                cur = None
            prev_dm = prev_pt = None
        if cur is None and not ended and rs > 0:
            cur = Route(app, i, t)
        if cur is None:
            prev_rs = rs
            continue
        owner[i] = cur
        cur.last_i = i
        cur.t1 = t
        if cur.app is None and app:
            cur.app = app
        cur.states[rs] += 1
        if rs == 2 and cur.arrived_t is None:
            cur.arrived_t = t
        if rs != prev_rs:
            cur.transitions.append(rs)
        pt = int(st.get("pt", "-1"))
        if pt >= 0:
            cur.types[pt] += 1
        dm = int(st.get("dm", "-1"))
        if dm >= 0 and prev_dm is not None and pt == prev_pt and dm < prev_dm:
            cur.dm_decrease += 1
        prev_dm, prev_pt = (dm if dm >= 0 else None), pt
        for key in ("dist_maneuver_units", "dist_dest_units"):
            if key in snap:
                cur.units[(key, UNITS.get(snap[key], snap[key]))] += 1
        if snap.get("dist_maneuver_m") not in (None, "", "0") or dm > 0:
            cur.provided["dist_turn"] += 1
        if snap.get("dist_dest_m") not in (None, "", "0"):
            cur.provided["dist_dest"] += 1
        if snap.get("eta_seconds") not in (None, "", "0"):
            cur.provided["eta"] += 1
        if snap.get("time_remaining_seconds") not in (None, "", "0"):
            cur.provided["time_remaining"] += 1
        # F5 (upstream gate) shows lanes only while iOS says lane_guidance_showing=1.
        if snap.get("lane_guidance_showing") == "1":
            cur.provided["lanes"] += 1
            li = snap.get("lane_guidance_index")
            ep = cur.lane_episodes[-1] if cur.lane_episodes else None
            if ep is None or ep[2] != li or ep[1] != prev_i:
                ep = [i, i, li, False]
                cur.lane_episodes.append(ep)
            ep[1] = i
            ep[3] = ep[3] or snap.get("lane_data") == "1"
            ep.append(i)   # one entry per frame (count below)
        prev_i = i
        prev_rs = rs
    if cur is not None:
        routes.append(cur)

    for i, t, body in bap:
        r = owner.get(i)
        if r is None:
            continue
        word = body.split(" ", 2)
        key = word[0] if word[0] != "CALL" else "CALL " + word[1]
        r.bap[key] += 1
        if body.startswith("CALL ETA src="):
            r.eta_src[body.split("src=", 1)[1].split()[0]] += 1
        if body.startswith("CALL LANES") and not body.startswith("CALL LANES off"):
            r.lanes_on += 1
        if body.startswith("CALL LANES"):
            lanes_calls.append((i, not body.startswith("CALL LANES off")))
    # iOS briefly reports showing=1 without a lane index for a single frame
    # (after a reroute or maneuver change); that is not a lane junction.
    for r in routes:
        r.lane_episodes = [ep[:4] for ep in r.lane_episodes if ep[2] not in (None, "") or len(ep) - 4 > 1]
    # B8: a lane episode counts as shown when FctID 24 was on at some input in it.
    for r in routes:
        for ep in r.lane_episodes:
            on = False
            shown = False
            for i, v in lanes_calls:
                if i > ep[1]:
                    break
                on = v
                if i >= ep[0] and on:
                    shown = True
            ep.append(shown or on)
    for i, t, body in render:
        r = owner.get(i)
        if r is None:
            continue
        r.render[body.split(" ", 1)[0]] += 1
    # A BAP teardown or cluster release inside a reroute (5 -> 3 -> 1) is a
    # visible flash: count them from the state sequence.
    rr = {}
    for i, (t, st) in state.items():
        rr[i] = int(st.get("rs", "0"))
    for i, t, body in bap + render:
        r = owner.get(i)
        if r is None or not (body.startswith("TEARDOWN") or body.startswith("RELEASE")):
            continue
        back = [rr.get(j, 0) for j in range(max(r.first_i, i - 8), i + 1)]
        if 5 in back and rr.get(i, 0) in (3, 5):
            r.reroute_clears += 1
    return routes


def field_status(provided, sent, exercised=True):
    if not exercised:
        return "NOT_EXERCISED"
    if provided and sent:
        return "SENT"
    if provided and not sent:
        return "NOT_SENT"
    return "APP_NOT_PROVIDED"


def route_summary(r):
    cats = OrderedDict()
    for name, members in CATEGORY.items():
        seen = sorted(MT.get(k, str(k)) for k in r.types if k in members)
        if seen:
            cats[name] = seen
    long_enough = r.seconds() >= MIN_ROUTE_S
    f = OrderedDict()
    f["dist_turn"] = field_status(r.provided["dist_turn"] > 0, r.bap["CALL DIST_TURN"] > 0)
    f["dist_decreasing"] = "SENT" if r.dm_decrease > 0 else ("NOT_EXERCISED" if not long_enough else "NOT_SEEN")
    f["dist_dest"] = field_status(r.provided["dist_dest"] > 0, r.bap["CALL DIST_DEST"] > 0,
                                  long_enough or r.provided["dist_dest"] > 0)
    eta_sent = r.eta_src["eta"] + r.eta_src["rem"] > 0
    f["eta"] = field_status(r.provided["eta"] + r.provided["time_remaining"] > 0, eta_sent,
                            long_enough or r.provided["eta"] > 0)
    f["lanes"] = field_status(r.provided["lanes"] > 0, r.lanes_on > 0, r.provided["lanes"] > 0)
    shown = sum(1 for ep in r.lane_episodes if ep[4])
    if r.lane_episodes and 0 < shown < len(r.lane_episodes):
        f["lanes"] = "PARTIAL"   # some lane junctions shown, others not (B8)
    f["reroute"] = "SEEN" if r.states[5] else "NOT_EXERCISED"
    f["arrival"] = "SEEN" if r.states[2] else "NOT_EXERCISED"
    f["map_box"] = "SHOWN" if r.render["TAKE"] else ("NOT_SHOWN" if long_enough else "NOT_EXERCISED")
    return OrderedDict([
        ("app", r.app or "?"), ("first_i", r.first_i), ("last_i", r.last_i),
        ("t0_ms", r.t0), ("seconds", round(r.seconds(), 1)), ("end", r.end),
        ("switched_from", r.switched_from),
        ("states", {ROUTE_STATES.get(k, str(k)): v for k, v in sorted(r.states.items())}),
        ("reroutes", sum(1 for s in r.transitions if s == 5)),
        ("reroute_clears", r.reroute_clears),
        # B2: how long iOS keeps the route in ARRIVED before it ends (or the capture ends).
        ("arrived_s", None if r.arrived_t is None else round((r.t1 - r.arrived_t) / 1000.0, 1)),
        ("maneuvers", cats),
        ("units", sorted({u for (_, u) in r.units})),
        ("dm_decreases", r.dm_decrease),
        ("eta_src", dict(r.eta_src)),
        ("bap", {k: v for k, v in sorted(r.bap.items())}),
        ("render", {k: v for k, v in sorted(r.render.items())}),
        ("fields", f),
        ("lane_junctions", OrderedDict([("total", len(r.lane_episodes)),
                                        ("shown", shown),
                                        ("no_lane_data", sum(1 for ep in r.lane_episodes if not ep[3]))])),
        ("marks", r.marks),
    ])


RANK = {"NOT_SENT": 5, "PARTIAL": 5, "SENT": 4, "SEEN": 4, "SHOWN": 4, "NOT_SHOWN": 3, "NOT_SEEN": 2,
        "APP_NOT_PROVIDED": 2, "NOT_EXERCISED": 0}


def app_matrix(summaries):
    apps = OrderedDict()
    for s in summaries:
        a = apps.setdefault(s["app"], OrderedDict([("routes", 0), ("seconds", 0.0), ("fields", OrderedDict()),
                                                  ("maneuvers", set()), ("units", set()),
                                                  ("app_switch_in", 0), ("reroute_clears", 0),
                                                  ("cluster_faults", 0), ("lane_junctions", [0, 0, 0])]))
        a["routes"] += 1
        a["seconds"] = round(a["seconds"] + s["seconds"], 1)
        a["reroute_clears"] += s["reroute_clears"]
        lj = s.get("lane_junctions", {})
        a["lane_junctions"] = [a["lane_junctions"][0] + lj.get("shown", 0), a["lane_junctions"][1] + lj.get("total", 0),
                               a["lane_junctions"][2] + lj.get("no_lane_data", 0)]
        a["cluster_faults"] += sum(s["render"].get(k, 0) for k in ("TAKE_FAILED", "FIGHT_STOP", "UNSTICK_73"))
        if s["switched_from"]:
            a["app_switch_in"] += 1
        for cat in s["maneuvers"]:
            a["maneuvers"].add(cat)
        a["units"].update(s["units"])
        for k, v in s["fields"].items():
            old = a["fields"].get(k)
            # Any NOT_SENT wins (defect); otherwise the strongest evidence wins.
            if old is None or RANK.get(v, 0) > RANK.get(old, 0):
                a["fields"][k] = v
    for a in apps.values():
        a["maneuvers"] = sorted(a["maneuvers"])
        a["units"] = sorted(a["units"])
    return apps


def attach_marks(routes, marks, state):
    """Attach each mark to the route it was taken in.  A mark belongs to this
    collection only if its last state line (i and t) is a line of this state
    log: marks from an earlier boot reuse small i values with other t."""
    matched = 0
    for m in marks:
        i = m.get("state_i")
        if i is None or i not in state or state[i][0] != m.get("state_t"):
            continue
        matched += 1
        best = None
        for r in routes:
            if r.first_i <= i + 1 and i <= r.last_i + 1:
                best = r
        if best is not None:
            best.marks.append(m["step"])
    return matched


def analyse(dirs, marks_path=None):
    all_routes = []
    sources = []
    for d in dirs:
        d = Path(d)
        cap, capped = parse_capture(d / "mu1320-f5-frames.cap")
        state = parse_state(d / "mu1320-f5-state.log")
        bap = parse_log(d / "mu1320-f5-bap.log", "B")
        render = parse_log(d / "mu1320-f5-render.log", "R")
        routes = build_routes(cap, state, bap, render)
        marks = parse_marks(marks_path or (d.parent / "f6-marks.txt"))
        matched = attach_marks(routes, marks, state)
        faults = sum(1 for _, _, b in bap if b.startswith("FAULT"))
        rejects = sum(1 for _, (t, st) in state.items() if "REJECT" in st.get("ev", ""))
        build = next((b.split("build=", 1)[1].split()[0] for _, _, b in bap if "build=" in b), "?")
        sources.append(OrderedDict([("dir", str(d)), ("build", build), ("inputs", len(cap)),
                                    ("capture_capped", capped), ("routes", len(routes)),
                                    ("bap_fault", faults), ("state_reject", rejects),
                                    ("marks", matched), ("marks_other_boot", len(marks) - matched)]))
        for r in routes:
            s = route_summary(r)
            s["dir"] = d.name
            all_routes.append(s)
    return OrderedDict([("sources", sources), ("routes", all_routes), ("apps", app_matrix(all_routes))])


FIELD_ROWS = [
    ("dist_turn", "到转向距离"), ("dist_decreasing", "距离递减"), ("dist_dest", "到目的地距离"),
    ("eta", "ETA/剩余时间"), ("lanes", "车道"), ("reroute", "重算"), ("arrival", "到达"),
    ("map_box", "地图框箭头"),
]


def markdown(result):
    out = ["# F6 support matrix (logs only)", "",
           "由 `scripts/f6_matrix.py` 生成。只反映日志：应用是否提供、F5 是否发给 BAP/renderer。"
           "VC/HUD 是否**显示**要看观察表和照片，这里不能判定。", "",
           "状态：SENT = 应用提供且已发出；APP_NOT_PROVIDED = 路线够长但应用没提供；"
           "NOT_EXERCISED = 没遇到该情况；NOT_SENT = 应用提供了但没发出（缺陷）；"
           "SEEN/SHOWN = 出现过/地图框接管过；NOT_SEEN = 路线够长但没观察到；"
           "PARTIAL = 车道只在部分车道路口发出（B8）。", "",
           "## 来源", "", "| 采集 | build | 输入 | 路线 | FAULT | REJECT | capture 截断 | 打点 |",
           "| --- | --- | ---: | ---: | ---: | ---: | --- | ---: |"]
    for s in result["sources"]:
        out.append("| %s | %s | %d | %d | %d | %d | %s | %d |" % (
            Path(s["dir"]).parent.name + "/" + Path(s["dir"]).name, s["build"], s["inputs"], s["routes"],
            s["bap_fault"], s["state_reject"], "是" if s["capture_capped"] else "否", s["marks"]))
    apps = result["apps"]
    names = list(apps)
    out += ["", "## 按应用", "", "| 项目 | " + " | ".join(names) + " |",
            "| --- | " + " | ".join("---" for _ in names) + " |"]
    out.append("| 路线数 / 秒 | " + " | ".join("%d / %.0f" % (apps[n]["routes"], apps[n]["seconds"]) for n in names) + " |")
    for key, label in FIELD_ROWS:
        out.append("| %s | " % label + " | ".join(apps[n]["fields"].get(key, "-") for n in names) + " |")
    out.append("| 车道路口 发出/总数（无车道数据） | " + " | ".join(
        "%d/%d (%d)" % tuple(apps[n]["lane_junctions"]) for n in names) + " |")
    out.append("| 机动类别 | " + " | ".join(", ".join(apps[n]["maneuvers"]) or "-" for n in names) + " |")
    out.append("| 距离单位 | " + " | ".join(", ".join(apps[n]["units"]) or "-" for n in names) + " |")
    out.append("| 应用切换进入 | " + " | ".join(str(apps[n]["app_switch_in"]) for n in names) + " |")
    out.append("| 重算时清除 | " + " | ".join(str(apps[n]["reroute_clears"]) for n in names) + " |")
    out.append("| 地图框异常 TAKE_FAILED/FIGHT_STOP/UNSTICK_73 | " + " | ".join(str(apps[n]["cluster_faults"]) for n in names) + " |")
    out += ["", "## 每条路线", "",
            "| 采集 | 应用 | i | 秒 | 结束 | 状态 | 重算 | 到达后秒 | 机动 | ETA 来源 | TAKE/RELEASE | 打点 |",
            "| --- | --- | --- | ---: | --- | --- | ---: | ---: | --- | --- | --- | --- |"]
    for s in result["routes"]:
        out.append("| %s | %s%s | %d–%d | %.0f | %s | %s | %d | %s | %s | %s | %d/%d | %s |" % (
            s["dir"], s["app"], " (从 %s 切换)" % s["switched_from"] if s["switched_from"] else "",
            s["first_i"], s["last_i"], s["seconds"], s["end"],
            ",".join("%s:%d" % kv for kv in s["states"].items()), s["reroutes"],
            "-" if s["arrived_s"] is None else "%.0f" % s["arrived_s"],
            "; ".join("%s=%s" % (k, "/".join(v)) for k, v in s["maneuvers"].items()) or "-",
            ",".join("%s:%d" % kv for kv in sorted(s["eta_src"].items())) or "-",
            s["render"].get("TAKE", 0), s["render"].get("RELEASE", 0), ",".join(s["marks"]) or "-"))
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("dirs", nargs="+", help="collect directories (armed-*/snapshot-*)")
    ap.add_argument("--marks", help="f6-marks.txt (default: <dir>/../f6-marks.txt)")
    ap.add_argument("--json", help="write JSON here")
    ap.add_argument("--md", help="write markdown here (default: stdout)")
    args = ap.parse_args(argv)
    result = analyse(args.dirs, args.marks)
    text = markdown(result)
    if args.json:
        Path(args.json).write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if args.md:
        Path(args.md).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
