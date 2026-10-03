"""Host tests for scripts/f6_matrix.py (F6 support matrix from F5 logs).

Synthetic collections in the F5 on-car formats: frames.cap diffs, F2 state
lines, B (BAP) and R (render) lines, all keyed by the shared input counter.
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "scripts"))
import f6_matrix as m  # noqa: E402

VEHICLE = BASE.parent / "resource/private/vehicle-dump/f5-vchud-v2/snapshot-18210953"


class Collection:
    """Builds one collect directory input by input."""

    def __init__(self):
        self.i = 0
        self.cap = ["#F2CAP v1 TEST"]
        self.state = ["F2 TEST START"]
        self.bap = ["B i=0 t=1 START_PROBE build=TEST-F6 yield=stock_rg_active metric=0"]
        self.render = []
        self.fields = {}

    def event(self, t, name):
        self.i += 1
        self.cap.append("@%d %d E %s" % (self.i, t, name))
        if name in ("SESSION", "LINK_LOST"):
            self.fields = {}
        self.state.append("F2 i=%d t=%d ev=%s rs=-1 act=0 pt=-1 dm=-1 dd=-1 eta=0 lanes=-1" % (self.i, t, name))
        return self.i

    def frame(self, t, rs, pt=-1, dm=-1, **fields):
        self.i += 1
        fields.setdefault("route_state", str(rs))
        diff = []
        for k, v in fields.items():
            if v is None:
                if k in self.fields:
                    diff.append("-" + k)
                    del self.fields[k]
            elif self.fields.get(k) != str(v):
                diff.append("%s\t%s\t%s" % (k, "s" if k == "source_name" else "n", v))
                self.fields[k] = str(v)
        self.cap.append("@%d %d F 1 %s" % (self.i, t, "\x1f".join(diff) if diff else "="))
        self.state.append("F2 i=%d t=%d ev=UPDATE rs=%d act=%d pt=%d dm=%d dd=-1 eta=0 lanes=-1"
                          % (self.i, t, rs, 1 if rs > 0 else 0, pt, dm))
        return self.i

    def b(self, text, t=0):
        self.bap.append("B i=%d t=%d %s" % (self.i, t, text))

    def r(self, text, t=0):
        self.render.append("R i=%d t=%d %s" % (self.i, t, text))

    def write(self, parent, name="armed-1"):
        d = Path(parent) / name
        d.mkdir(parents=True)
        (d / "mu1320-f5-frames.cap").write_text("\n".join(self.cap) + "\n", encoding="utf-8")
        (d / "mu1320-f5-state.log").write_text("\n".join(self.state) + "\n")
        (d / "mu1320-f5-bap.log").write_text("\n".join(self.bap) + "\n")
        (d / "mu1320-f5-render.log").write_text("\n".join(self.render) + "\n")
        return d


def apple_route(c, t0, seconds=60, eta=True, lanes=False, reroute=False, arrive=False):
    c.frame(t0, 3, source_name="Apple Maps", source_supports_rg=1)
    c.b("START d=11/0")
    c.frame(t0 + 500, 1, pt=1, dm=300, dist_maneuver_m=300, dist_maneuver_units=4,
            dist_dest_m=2000, dist_dest_units=1,
            eta_seconds=1790000000 if eta else None,
            time_remaining_seconds=600 if eta else None,
            lane_guidance_showing=1 if lanes else 0, lane_guidance_total=2 if lanes else 0)
    c.b("CALL DIST_TURN 300 bar=-")
    c.b("CALL DIST_DEST 2000")
    c.b("CALL ETA src=eta arrival=1790000000" if eta else "CALL ETA src=none arrival=-1")
    if lanes:
        c.b("CALL LANES n=2 slot=0 [0:0:2 1:c0:0]")
    c.r("TAKE from=74 mode=kdk")
    c.frame(t0 + 1500, 1, pt=1, dm=200, dist_maneuver_m=200)
    c.b("CALL DIST_TURN 200 bar=-")
    if reroute:
        c.frame(t0 + 2000, 5, pt=1, dm=200)
        c.frame(t0 + 2100, 3, pt=-1, dm=-1, dist_maneuver_m=None)
        c.frame(t0 + 2500, 1, pt=2, dm=500, dist_maneuver_m=500)
    if arrive:
        c.frame(t0 + seconds * 1000 - 1000, 2, pt=25, dm=0, dist_maneuver_m=0)
    c.frame(t0 + seconds * 1000, 1, pt=1, dm=100, dist_maneuver_m=100)
    c.frame(t0 + seconds * 1000 + 100, 0, route_state=0, dist_maneuver_m=None, dist_dest_m=None,
            eta_seconds=None, time_remaining_seconds=None)
    c.b("TEARDOWN")
    c.r("RELEASE to=74 mode=kdk")


class MatrixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_matrix(self, c, marks=None):
        parent = Path(tempfile.mkdtemp(dir=self.tmp))
        d = c.write(parent)
        if marks is not None:
            (parent / "f6-marks.txt").write_text(marks)
        return m.analyse([d])

    def test_one_route_all_fields_sent(self):
        c = Collection()
        c.event(1, "SESSION")
        apple_route(c, 10000, lanes=True)
        res = self.run_matrix(c)
        self.assertEqual(len(res["routes"]), 1)
        r = res["routes"][0]
        self.assertEqual(r["app"], "Apple Maps")
        self.assertEqual(r["end"], "ROUTE_END")
        f = r["fields"]
        for key in ("dist_turn", "dist_decreasing", "dist_dest", "eta", "lanes"):
            self.assertEqual(f[key], "SENT", key)
        self.assertEqual(f["map_box"], "SHOWN")
        self.assertEqual(f["arrival"], "NOT_EXERCISED")
        self.assertEqual(r["render"], {"RELEASE": 1, "TAKE": 1}, "closing input's RELEASE belongs to the route")
        self.assertEqual(r["units"], ["ft", "mi"])
        self.assertEqual(r["maneuvers"], {"turn": ["LEFT"]})

    def test_missing_eta_on_long_route_is_app_not_provided(self):
        c = Collection()
        apple_route(c, 10000, seconds=60, eta=False)
        self.assertEqual(self.run_matrix(c)["routes"][0]["fields"]["eta"], "APP_NOT_PROVIDED")

    def test_missing_eta_on_short_route_is_not_exercised(self):
        c = Collection()
        apple_route(c, 10000, seconds=5, eta=False)
        self.assertEqual(self.run_matrix(c)["routes"][0]["fields"]["eta"], "NOT_EXERCISED")

    def test_provided_but_not_sent_is_a_defect_and_wins_the_app_row(self):
        c = Collection()
        apple_route(c, 10000)
        # Second route: eta present, but F5 never sent an arrival time.
        c.frame(100000, 1, pt=2, dm=400, source_name="Apple Maps", dist_maneuver_m=400,
                eta_seconds=1790000500)
        c.b("CALL ETA src=none arrival=-1")
        c.frame(130000, 0, route_state=0, eta_seconds=None)
        res = self.run_matrix(c)
        self.assertEqual([r["fields"]["eta"] for r in res["routes"]], ["SENT", "NOT_SENT"])
        self.assertEqual(res["apps"]["Apple Maps"]["fields"]["eta"], "NOT_SENT")

    def test_lanes_follow_the_showing_gate_not_the_total(self):
        c = Collection()
        c.frame(1000, 1, pt=1, dm=300, source_name="Google Maps", lane_guidance_total=3,
                lane_guidance_showing=0, dist_maneuver_m=300)
        c.b("CALL LANES off")
        c.frame(40000, 0, route_state=0)
        self.assertEqual(self.run_matrix(c)["routes"][0]["fields"]["lanes"], "NOT_EXERCISED")

    def test_app_switch_splits_the_route(self):
        c = Collection()
        c.frame(1000, 1, pt=1, dm=300, source_name="Apple Maps", dist_maneuver_m=300)
        c.frame(2000, 1, pt=2, dm=800, source_name="Google Maps", dist_maneuver_m=800)
        c.frame(3000, 0, route_state=0)
        res = self.run_matrix(c)
        self.assertEqual([(r["app"], r["end"], r["switched_from"]) for r in res["routes"]],
                         [("Apple Maps", "APP_SWITCH", None), ("Google Maps", "ROUTE_END", "Apple Maps")])
        self.assertEqual(res["apps"]["Google Maps"]["app_switch_in"], 1)

    def test_link_loss_and_session_end_routes(self):
        c = Collection()
        c.frame(1000, 1, pt=1, dm=300, source_name="Apple Maps")
        c.event(2000, "LINK_LOST")
        c.event(3000, "SESSION")
        c.frame(4000, 6, pt=11, source_name="Waze")
        c.event(5000, "SESSION")
        res = self.run_matrix(c)
        self.assertEqual([(r["app"], r["end"]) for r in res["routes"]],
                         [("Apple Maps", "LINK_LOST"), ("Waze", "SESSION")])

    def test_reroute_counted_and_teardown_inside_it_is_a_clear(self):
        c = Collection()
        apple_route(c, 10000, reroute=True, arrive=True)
        r = self.run_matrix(c)["routes"][0]
        self.assertEqual(r["reroutes"], 1)
        self.assertEqual(r["reroute_clears"], 0)
        self.assertEqual(r["fields"]["reroute"], "SEEN")
        self.assertEqual(r["fields"]["arrival"], "SEEN")
        self.assertEqual(r["arrived_s"], 1.0)
        self.assertIn("arrive", r["maneuvers"])

        c = Collection()
        c.frame(1000, 1, pt=1, dm=300, source_name="Apple Maps")
        c.frame(2000, 5, pt=1, dm=300)
        c.frame(2100, 3)
        c.b("TEARDOWN")
        c.frame(2500, 1, pt=2, dm=600)
        c.frame(3000, 0, route_state=0)
        self.assertEqual(self.run_matrix(c)["routes"][0]["reroute_clears"], 1)

    def test_marks_attach_to_the_route_they_were_taken_in(self):
        c = Collection()
        apple_route(c, 10000)
        last = c.i
        marks = ("F6MARK step=A2 note=apple start\nDATE: Sat Sep 26 10:00:00 2026\nEPOCH: NA\n"
                 "LAST mu1320-f5-state.log: F2 i=3 t=11500 ev=UPDATE rs=1\nF6MARK_END\n"
                 "F6MARK step=X1 note=other boot\nDATE: y\nEPOCH: NA\n"
                 "LAST mu1320-f5-state.log: F2 i=3 t=999 ev=UPDATE rs=1\nF6MARK_END\n"
                 "F6MARK step=A9 note=\nDATE: x\nEPOCH: 1790000000\n"
                 "LAST mu1320-f5-state.log: ABSENT\nF6MARK_END\n")
        res = self.run_matrix(c, marks)
        self.assertEqual(res["routes"][0]["marks"], ["A2"])
        self.assertEqual(res["sources"][0]["marks"], 1)
        self.assertEqual(res["sources"][0]["marks_other_boot"], 2)
        self.assertGreater(last, 3)

    def test_capture_cap_and_markdown_and_json(self):
        c = Collection()
        apple_route(c, 10000)
        c.cap.append("#CAPTURE_CAP_REACHED bytes=3145728")
        c.cap.append("@99 1 F 1 route_state\tn\t1")
        d = c.write(self.tmp)
        out_md = self.tmp / "m.md"
        out_json = self.tmp / "m.json"
        self.assertEqual(m.main([str(d), "--md", str(out_md), "--json", str(out_json)]), 0)
        data = json.loads(out_json.read_text())
        self.assertTrue(data["sources"][0]["capture_capped"])
        text = out_md.read_text()
        self.assertIn("| 车道 |", text)
        self.assertIn("Apple Maps", text)

    def test_bad_capture_line_is_rejected(self):
        c = Collection()
        c.cap.append("@1 5")
        with self.assertRaises(ValueError):
            self.run_matrix(c)

    @unittest.skipUnless((VEHICLE / "mu1320-f5-frames.cap").exists(), "private vehicle data absent")
    def test_f5_v2_vehicle_collection(self):
        res = m.analyse([VEHICLE])
        apps = res["apps"]
        self.assertEqual(sorted(apps), ["Apple Maps", "Google Maps"])
        # B3: Google Maps provides an arrival time and F5 sent it.
        self.assertEqual(apps["Google Maps"]["fields"]["eta"], "SENT")
        # B8 check (2026-09-27): the other 7 "showing" episodes are single-frame
        # blips without a lane index (not junctions) and are not counted.
        self.assertEqual(apps["Google Maps"]["fields"]["lanes"], "SENT")
        self.assertEqual(apps["Google Maps"]["lane_junctions"], [1, 1, 0])
        self.assertEqual(apps["Apple Maps"]["fields"]["arrival"], "SEEN")
        self.assertEqual(res["sources"][0]["bap_fault"], 0)
        self.assertEqual(sum(r["reroute_clears"] for r in res["routes"]), 0)


if __name__ == "__main__":
    unittest.main()
