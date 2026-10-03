"""Host transaction tests for the F5 VC/HUD SD folder.

F5 scripts are the F3 v2 scripts (install/arm/rollback transaction, F1 v2
NavActiveIgnore quarantine) plus the F4 renderer and context 80 steps in arm,
disarm, status and collect.  Every F3 v2 transaction test is rerun against the
F5 folder with a fake dmdt and a fake maneuver_render (from the F4 tests), so
the real F5 shell code runs; F5-specific cases are added.
"""
import json
import os
import re
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

import test_f3_trial as f3
import test_f4_trial as f4
import test_navjava_trial as navjava

BASE = navjava.BASE

FAKE_RENDERER = r'''#!/usr/bin/env python3
import fcntl, json, os, signal, sys, time
state_path = os.environ['F4_FAKE_STATE']
mode = os.environ.get('F5_FAKE_RENDER', '')
def update(**kw):
    with open(state_path + '.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        st = json.load(open(state_path))
        st.update(kw)
        json.dump(st, open(state_path, 'w'))
def out(msg):
    sys.stderr.write(msg + '\n'); sys.stderr.flush()
out('maneuver_render: starting 328x181 atlas=%s graphics=%s' % (os.path.exists('flag_atlas.rgba'), os.environ.get('GRAPHICS_ROOT')))
if mode == 'init-fail':
    out('platform_qnx: FAIL eglInitialize'); sys.exit(1)
def term(*_):
    update(d98_pid=None); out('platform_qnx: caught SIGTERM'); sys.exit(0)
signal.signal(signal.SIGTERM, term)
update(d98_pid=os.getpid())
out('maneuver_render: ready, waiting for commands on :19800')
if mode != 'no-java':
    out('server: connected to 127.0.0.1:19800')
while True:
    time.sleep(0.2)
'''


def pair(path):
    return tuple(subprocess.check_output(["cksum", str(path)], text=True).split()[:2])


class F5TrialTests(f3.F3V2TrialTests):
    STAGE = "mu1320-f5-vchud-v5"
    RUNTIME = "mu1320-rgi-f5-v5"
    NEW_JAR = "CarPlayRGI-MU1320-F5VchudV5.jar"
    PAYLOAD_JAR = "carplay_mu1320_f5_vchud_v5.jar.DISABLED"
    WRAPPER = "f5_trial.sh"
    COLLECTOR = "collect_f5.sh"
    LISTENER = ("[CP/W][NavJava] MU1320-F5-VCHUD-V5 LISTENER_READY bap-yield+render; "
                "NavActiveIgnore quarantined; renderer 98 via ctx 80\n")

    def setUp(self):
        super().setUp()
        sd = self.f.sd
        vehicle = str(self.f.vehicle)
        control = sd / "control.sh"
        collector = sd / self.COLLECTOR
        helper = sd / "f5_dm.sh"
        sc = sd / "f5_sc.sh"
        renderer = sd / "maneuver_render"
        old = {"helper": pair(helper), "sc": pair(sc), "renderer": pair(renderer), "collector": pair(collector),
               "control": pair(control)}

        def rewrite(text):
            return re.sub(r"/mnt/app|/tmp", lambda m: vehicle + m.group(), text)

        helper.write_text(rewrite(helper.read_text()))
        sc.write_text(rewrite(sc.read_text()))
        renderer.write_text(FAKE_RENDERER)
        renderer.chmod(0o755)
        dmdt = self.f.vehicle / "mnt/app/eso/bin/apps/dmdt"
        dmdt.parent.mkdir(parents=True, exist_ok=True)
        dmdt.write_text(f4.FAKE_DMDT)
        dmdt.chmod(0o755)
        state_dir = Path(tempfile.mkdtemp(prefix="f5dm"))
        self.state = state_dir / "state.json"
        self.state.write_text(json.dumps({"contexts": {"74": [20, 102, 101, 33], "72": [33], "10": [16]},
                                          "cluster": "74", "main": "10"}))
        saved = {k: os.environ.get(k) for k in ["F4_FAKE_STATE", "F5_FAKE_RENDER"]}
        os.environ["F4_FAKE_STATE"] = str(self.state)
        os.environ.pop("F5_FAKE_RENDER", None)

        def restore_env():
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        self.addCleanup(restore_env)
        self.addCleanup(self.kill_renderer)

        text = collector.read_text()
        text = text.replace("'%s' ] && [ \"${2:-}\" = '%s' ] || fail 'displaymanager helper checksum'" % old["helper"],
                            "'%s' ] && [ \"${2:-}\" = '%s' ] || fail 'displaymanager helper checksum'" % pair(helper))
        collector.write_text(text)
        text = control.read_text()
        for key, new in [("helper", pair(helper)), ("sc", pair(sc)), ("renderer", pair(renderer)),
                         ("collector", pair(collector))]:
            self.assertIn(" ".join(old[key]), text, key)
            text = text.replace(" ".join(old[key]), " ".join(new))
        self.assertIn("2992755173 34464", text)
        text = text.replace("2992755173 34464", " ".join(pair(dmdt)))
        control.write_text(text)
        wrapper = sd / self.WRAPPER
        wrapper.write_text(wrapper.read_text().replace(
            "'%s' ] && [ \"${2:-}\" = '%s' ] || fail 'control checksum'" % old["control"],
            "'%s' ] && [ \"${2:-}\" = '%s' ] || fail 'control checksum'" % pair(control)))

        # Fake pidin: unknown pids (the renderer) are answered from ps, like the F4 fake.
        pidin = self.f.commands / "pidin"
        pidin.write_text(pidin.read_text().replace(
            "p=a[a.index('-p')+1]; name=names[p]",
            "p=a[a.index('-p')+1]\n"
            "if p not in names:\n"
            " import subprocess\n"
            " print(subprocess.run(['ps','-o','command=','-p',p],capture_output=True,text=True).stdout.strip()); sys.exit(0)\n"
            "name=names[p]"))

    def kill_renderer(self):
        pid_file = self.tmp / "mu1320-f5-renderer.pid"
        if pid_file.exists():
            try:
                os.kill(int(pid_file.read_text().strip()), signal.SIGKILL)
            except (OSError, ValueError):
                pass

    def dm_state(self):
        return json.loads(self.state.read_text())

    def renderer_pid(self):
        pid_file = self.tmp / "mu1320-f5-renderer.pid"
        return int(pid_file.read_text().strip()) if pid_file.exists() else None

    def alive(self, pid):
        out = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
        return bool(out) and not out.startswith("Z")

    def arm_ready(self):
        self.ok("install")
        self.propagate()
        (self.tmp / "carplay_java.log").write_text(self.LISTENER)
        return self.ok("arm", mode="no_dio")

    def write_java_evidence(self):
        (self.tmp / "mu1320-f5-state.log").write_text(
            "F2 MU1320-F5-VCHUD-V5 START mode=BAP+RENDER publishes=17,39,23,18,49,55,21,24,22\n"
            "F2 i=1 t=0 ev=SESSION rs=-1 act=0 mc=-1 ord=- sym=INACTIVE\n"
            "F2 i=2 t=40 ev=ACTIVATE+PRIMARY rs=6 act=1 mc=11 ord=0,1 sym=MANEUVER:13/192\n"
            "F2 i=3 t=120 ev=ROUTE_END+DEACTIVATE rs=0 act=0 mc=0 ord=- sym=INACTIVE\n")
        (self.tmp / "mu1320-f5-frames.cap").write_text(
            "#F2CAP v1 MU1320-F5-VCHUD-V5\n@1 0 E SESSION\n@2 40 F 1 CAPTURE_BODY_NOT_PRINTED\n")
        (self.tmp / "mu1320-f5-bap.log").write_text(
            "B i=0 t=0 START_PROBE build=MU1320-F5-VCHUD-V5 yield=stock_rg_active metric=0 kill=0\n"
            "B i=2 t=40 BIND ok service=AppConnectorNavi refs=1\n"
            "B i=2 t=41 START d=13/192 dm=800 bar=-1 ms=2 dd=5400\n"
            "B i=2 t=41 CALL RG_STATUS 1\n"
            "B i=2 t=41 CALL DESCRIPTOR 13/192\n"
            "B i=2 t=41 CALL LANES n=2 slot=0 [0:0:0 1:c0:2]\n"
            "B i=2 t=41 CALL ETA src=eta arrival=1790309340\n"
            "B i=2 t=41 RCMD MAN icon=2 dir=0 exit=90 side=0 jn=3 bar=0/0\n"
            "B i=3 t=120 TEARDOWN reason=ROUTE_END+DEACTIVATE\n"
            "B i=3 t=120 RCMD CLEAR\n"
            "B i=3 t=120 CALL RG_STATUS 0\n")
        (self.tmp / "mu1320-f5-render.log").write_text(
            "R i=0 t=0 START_PROBE build=MU1320-F5-VCHUD-V5 render_off=0 calib=0\n"
            "R i=0 t=5 DISPLAY ok dm=de.audi.tghu.fwhmi.DisplayManagerMIB2High\n"
            "R i=0 t=6 RENDER_LISTEN 127.0.0.1:19800\n"
            "R i=2 t=60 GEOM layout=LayoutMIB2HighB9@t0 stock_stage=1 stage=popup src=(59,27 210x153) dst=(1091,110) backing=102\n"
            "R i=2 t=61 TAKE from=74 mode=native result=80 java_ctx=74 saved_backing=0/0\n"
            "R i=2 t=1062 VERIFY real=80 java_ctx=74\n"
            "R i=3 t=130 RELEASE to=74 mode=native result=74 java_ctx=74\n")
        (self.tmp / "mu1320-f5-sc.log").write_text("SC ctx=80 rc=0 reads=1 cluster=80 list=[98 102 101 33]\n")
        (self.tmp / "mu1320-f5-ctx-mode").write_text("kdk\n")

    def assert_java_evidence(self, stdout):
        self.assertIn("F5_STATE_COUNT[F2 i=]=3", stdout)
        self.assertIn("F5_STATE_COUNT[ev=REJECT]=0", stdout)
        self.assertIn("F5_BAP_COUNT[ BIND ok]=1", stdout)
        self.assertIn("F5_BAP_COUNT[ START ]=1", stdout)
        self.assertIn("F5_BAP_COUNT[ TEARDOWN ]=1", stdout)
        self.assertIn("F5_BAP_COUNT[ CALL ]=5", stdout)
        self.assertIn("F5_BAP_COUNT[ CALL LANES n=]=1", stdout)
        self.assertIn("F5_BAP_COUNT[ CALL ETA src=eta]=1", stdout)
        self.assertIn("F5_BAP_COUNT[ RCMD MAN ]=1", stdout)
        self.assertIn("F5_BAP_COUNT[ FAULT ]=0", stdout)
        self.assertIn("F5_RENDER_COUNT[ TAKE ]=1", stdout)
        self.assertIn("F5_RENDER_COUNT[ RELEASE ]=1", stdout)
        self.assertIn("F5_RENDER_COUNT[ VERIFY ]=1", stdout)
        self.assertIn("F5_RENDER_COUNT[ TAKE_FAILED]=0", stdout)
        self.assertIn("TEARDOWN reason=ROUTE_END+DEACTIVATE", stdout)
        self.assertNotIn("CALL RG_STATUS 1", stdout, "CALL lines are copied, not printed")
        self.assertNotIn("RCMD MAN icon", stdout, "RCMD lines are copied, not printed")
        self.assertNotIn("CAPTURE_BODY_NOT_PRINTED", stdout)
        self.assertIn("F5_KILL_SWITCH: ABSENT", stdout)
        self.assertIn("F5_DISPLAY_BEGIN", stdout)
        self.assertIn("DM_CLUSTER_CONTEXT: 74", stdout)
        armed = [p for p in (self.f.sd / "out").iterdir() if p.name.startswith("armed-")]
        self.assertEqual(len(armed), 1)
        self.assertIn("CALL RG_STATUS 1", (armed[0] / "mu1320-f5-bap.log").read_text())
        self.assertIn("TAKE from=74", (armed[0] / "mu1320-f5-render.log").read_text())
        self.assertIn("server: connected", (armed[0] / "mu1320-f5-renderer.log").read_text())
        self.assertIn("cluster=80", (armed[0] / "mu1320-f5-sc.log").read_text())
        self.assertEqual((armed[0] / "mu1320-f5-ctx-mode").read_text(), "kdk\n")

    # Overrides with F5 names (same flow as F3 v2).
    def test_install_arm_parse_collect_and_rollback(self):
        self.ok("install")
        self.assertTrue(self.new.is_file())
        self.assert_quarantined()
        for name in ["maneuver_render", "flag_atlas.rgba", "f5_sc.sh", "f5_dm.sh", "f4_unbuf.so"]:
            self.assertEqual((self.root / "render" / name).read_bytes(), (self.f.sd / name).read_bytes())
        self.assertEqual((self.root / "render/maneuver_render").stat().st_mode & 0o777, 0o755)
        self.assertEqual((self.root / "render/f5_sc.sh").stat().st_mode & 0o777, 0o755)
        status = self.ok("status")
        self.assertIn("JAVA_ARCHIVE: F5_INSTALLED", status.stdout)
        self.assertIn("F5_RENDERER: ABSENT", status.stdout)
        self.assertIn("DM_CONTEXT_80: ABSENT", status.stdout)
        self.assertNotEqual(self.run_action("arm", mode="no_dio").returncode, 0)

        self.propagate()
        (self.tmp / "carplay_java.log").write_text(self.LISTENER)
        arm = self.ok("arm", mode="no_dio")
        self.assertIn("RENDERER_READY", arm.stdout)
        self.assertIn("CONTEXT_80_DECLARED: [98 102 101 33] cluster_ctx=74", arm.stdout)
        self.assertIn("CONTEXT_HELPER_OK: gs=74", arm.stdout)
        pid = self.renderer_pid()
        self.assertTrue(pid and self.alive(pid))
        log = (self.tmp / "mu1320-f5-renderer.log").read_text()
        self.assertIn("atlas=True graphics=/proc/boot", log, "renderer runs in the render dir with the stock graphics root")
        st = self.dm_state()
        self.assertEqual(st["contexts"]["80"], [98, 102, 101, 33])
        self.assertEqual(st["cluster"], "74", "arm never switches the cluster")
        self.assertNotIn(["ts"], [a[:1] for a in st["log"]])
        token = self.tmp / "mu1320-navhook-v1.arm"
        token.unlink()
        (self.tmp / "mu1320-navhook-v1-gate-202").write_text(
            "MU1320_NAVHOOK_V1_GATE mode=ACTIVE_TOKEN_CONSUMED pid=202 ppid=101\n")
        (self.tmp / "carplay_hook.log").write_text(
            "Registered module 'routeguidance'\nIdentify patched\nUpdate: state=6\nManeuver: idx=0\n")
        self.write_java_evidence()
        armed = self.ok("collect", "armed")
        self.assertIn("GLOBAL_GATE_RECEIPT_COUNT=1", armed.stdout)
        self.assert_java_evidence(armed.stdout)
        self.assertIn("F5_RENDERER: RUNNING pid=%d" % pid, armed.stdout)
        self.assertIn("DM_CONTEXT_80: DECLARED list=[98 102 101 33]", armed.stdout)
        self.assertIn("DIO_ENV_MARKER=1 DIO_ENV_PRELOAD=1", armed.stdout)

        rollback = self.ok("rollback")
        self.assertIn("RENDERER_STOP: pid=%d" % pid, rollback.stdout)
        time.sleep(0.3)
        self.assertFalse(self.alive(pid))
        self.assertIn("move quarantined NavActiveIgnore back", rollback.stdout)
        self.assertFalse(self.new.exists())
        self.assertFalse(self.quarantine.exists())
        self.assertEqual(self.old.read_bytes(), self.old_bytes)
        self.assertEqual((self.root / "phase.txt").read_text(), "INSTALLATION_BASELINE_RESTORED\n")
        self.propagate()
        for path in list(self.tmp.iterdir()):
            if path.is_file() or path.is_symlink():
                path.unlink()
        restored = self.ok("collect", "restored", dio_pid="303")
        self.assertIn("DIO_ENV_MARKER=0 DIO_ENV_PRELOAD=0", restored.stdout)
        self.assertIn("F5_RENDERER: ABSENT", restored.stdout)
        self.assert_mounts()

    def test_status_reports_kill_switch(self):
        status = self.ok("status").stdout
        for line in ["BAP_KILL_SWITCH: ABSENT", "RENDER_OFF_SWITCH: ABSENT", "CALIBRATION_SWITCH: ABSENT",
                     "GEOMETRY_OVERRIDE: ABSENT", "CTX_MODE: kdk"]:
            self.assertIn(line, status)
        (self.tmp / "mu1320-f5-ctx-mode").write_text("native\n")
        self.assertIn("CTX_MODE: native", self.ok("status").stdout)
        (self.tmp / "mu1320-f5-ctx-mode").write_text("nonsense\n")
        self.assertIn("CTX_MODE: kdk", self.ok("status").stdout)
        for name in ["mu1320-f5-bap-off", "mu1320-f5-render-off", "mu1320-f5-calib", "mu1320-f5-geom.cfg"]:
            (self.tmp / name).write_text("")
        status = self.ok("status").stdout
        for line in ["BAP_KILL_SWITCH: PRESENT", "RENDER_OFF_SWITCH: PRESENT", "CALIBRATION_SWITCH: PRESENT",
                     "GEOMETRY_OVERRIDE: PRESENT"]:
            self.assertIn(line, status)

    def test_f3_listener_markers_do_not_arm_f5(self):
        self.ok("install")
        self.propagate()
        for marker in ["MU1320-F3-BAP-V2 LISTENER_READY bap-yield; NavActiveIgnore quarantined; no renderer",
                       "MU1320-F3-BAP-V1 LISTENER_READY bap-yield"]:
            (self.tmp / "carplay_java.log").write_text("[CP/W][NavJava] " + marker + "\n")
            result = self.run_action("arm", mode="no_dio")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("listener marker absent", result.stdout + result.stderr)
        self.assertIsNone(self.renderer_pid(), "renderer is started only after every Java/native check")

    def test_v1_runtime_workspace_is_not_touched(self):
        others = [self.f.app / "root/mu1320-rgi-f3-v2", self.f.app / "root/mu1320-rgi-f5-v1",
                  self.f.app / "root/mu1320-rgi-f5-v2", self.f.app / "root/mu1320-rgi-f5-v3",
                  self.f.app / "root/mu1320-rgi-f5-v4"]
        for other in others:
            other.mkdir(parents=True, mode=0o700)
            (other / "phase.txt").write_text("INSTALLATION_BASELINE_RESTORED\n")
        self.ok("install")
        self.ok("rollback", direct=True)
        for other in others:
            self.assertEqual((other / "phase.txt").read_text(), "INSTALLATION_BASELINE_RESTORED\n")

    # F5-specific renderer/display cases.
    def test_arm_fails_and_stops_renderer_without_java_link(self):
        os.environ["F5_FAKE_RENDER"] = "no-java"
        self.ok("install")
        self.propagate()
        (self.tmp / "carplay_java.log").write_text(self.LISTENER)
        result = self.run_action("arm", mode="no_dio")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("did not reach the Java listener", result.stdout + result.stderr)
        self.assertFalse((self.tmp / "mu1320-navhook-v1.arm").exists())
        self.assertFalse((self.tmp / "mu1320-f5-renderer.pid").exists())
        self.assertNotIn("80", self.dm_state()["contexts"], "no context declared when arm fails")

    def test_arm_fails_when_renderer_init_fails(self):
        os.environ["F5_FAKE_RENDER"] = "init-fail"
        self.ok("install")
        self.propagate()
        (self.tmp / "carplay_java.log").write_text(self.LISTENER)
        result = self.run_action("arm", mode="no_dio")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("renderer exited during init", result.stdout + result.stderr)
        self.assertFalse((self.tmp / "mu1320-navhook-v1.arm").exists())

    def test_arm_refuses_foreign_displayable_98_and_wrong_context_80(self):
        self.ok("install")
        self.propagate()
        (self.tmp / "carplay_java.log").write_text(self.LISTENER)
        foreign = subprocess.Popen(["sleep", "30"])
        self.addCleanup(foreign.wait)
        self.addCleanup(foreign.kill)
        st = self.dm_state()
        st["d98_pid"] = foreign.pid
        self.state.write_text(json.dumps(st))
        result = self.run_action("arm", mode="no_dio")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("displayable 98 exists without our renderer", result.stdout + result.stderr)
        st = self.dm_state()
        st["d98_pid"] = None
        st["contexts"]["80"] = [98, 33]
        self.state.write_text(json.dumps(st))
        result = self.run_action("arm", mode="no_dio")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("context 80 declared as [98 33]", result.stdout + result.stderr)
        self.assertIsNone(self.renderer_pid())

    def test_arm_refuses_when_cluster_already_on_80(self):
        self.ok("install")
        self.propagate()
        (self.tmp / "carplay_java.log").write_text(self.LISTENER)
        st = self.dm_state()
        st["contexts"]["80"] = [98, 102, 101, 33]
        st["cluster"] = "80"
        self.state.write_text(json.dumps(st))
        result = self.run_action("arm", mode="no_dio")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cluster already on context 80", result.stdout + result.stderr)

    def test_arm_accepts_context_80_already_declared_identically(self):
        st = self.dm_state()
        st["contexts"]["80"] = [98, 102, 101, 33]
        self.state.write_text(json.dumps(st))
        self.arm_ready()
        dc = [a for a in self.dm_state()["log"] if a[:1] == ["dc"]]
        self.assertEqual(dc, [], "no second declaration")

    def test_disarm_stops_renderer_and_restores_cluster_left_on_80(self):
        self.arm_ready()
        pid = self.renderer_pid()
        st = self.dm_state()
        st["cluster"] = "80"     # as if Java had presented and then died
        self.state.write_text(json.dumps(st))
        result = self.ok("disarm")
        self.assertIn("RENDERER_STOP: pid=%d" % pid, result.stdout)
        self.assertIn("CLUSTER_ON_80: switching to 74", result.stdout)
        self.assertIn("DISARM_CLUSTER_CONTEXT: 74 restored=1", result.stdout)
        self.assertEqual(self.dm_state()["cluster"], "74")
        time.sleep(0.3)
        self.assertFalse(self.alive(pid))
        self.assertIsNone(self.dm_state().get("d98_pid"))

    def test_disarm_without_renderer_leaves_stock_cluster_alone(self):
        self.ok("install")
        result = self.ok("disarm")
        self.assertIn("DISARM_CLUSTER_CONTEXT: 74", result.stdout)
        self.assertEqual([a for a in self.dm_state()["log"] if a[:1] == ["sc"]], [])

    def test_direct_rollback_works_with_read_only_sd_out(self):
        # After the wrapper the SD is usually read-only again; control.sh rollback is the documented fallback.
        self.arm_ready()
        pid = self.renderer_pid()
        out = self.f.sd / "out"
        out.chmod(0o555)
        self.addCleanup(out.chmod, 0o755)
        result = self.run_action("rollback", direct=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("RENDERER_STOP: pid=%d" % pid, result.stdout)
        self.assertIn("DISARM_CLUSTER_CONTEXT: 74 restored=1", result.stdout)
        self.assertFalse(self.new.exists())
        self.assertEqual(self.old.read_bytes(), self.old_bytes)
        self.assertEqual((self.root / "phase.txt").read_text(), "INSTALLATION_BASELINE_RESTORED\n")

    def test_disarm_fails_when_cluster_stays_on_80(self):
        self.arm_ready()
        st = self.dm_state()
        st["cluster"] = "80"
        st["hang"] = "sc"          # displaymanager ignores the switch back
        self.state.write_text(json.dumps(st))
        result = self.run_action("disarm")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("WARNING: cluster still on context 80", result.stdout)
        self.assertIn("cluster not confirmed off context 80", result.stdout + result.stderr)
        self.assertNotIn("F5_TRIAL_ACTION_PASSED", result.stdout)
        self.assertFalse((self.tmp / "mu1320-navhook-v1.arm").exists(), "token is still withdrawn")

    def test_disarm_fails_and_rollback_warns_when_displaymanager_is_silent(self):
        self.arm_ready()
        st = self.dm_state()
        st["hang"] = "gs"
        self.state.write_text(json.dumps(st))
        result = self.run_action("disarm")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("WARNING: cluster context UNKNOWN", result.stdout)
        result = self.run_action("rollback")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("WARNING: cluster not confirmed off context 80", result.stdout)
        self.assertFalse(self.new.exists())

    def test_silent_displaymanager_does_not_hang_status(self):
        st = self.dm_state()
        st["hang"] = "gs"
        self.state.write_text(json.dumps(st))
        started = time.time()
        result = self.run_action("status")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("DM_CLUSTER_CONTEXT: UNKNOWN", result.stdout)
        self.assertLess(time.time() - started, 24)

    # v2: the context helper the Java presenter runs.
    def sc(self, *args, timeout=60):
        return subprocess.run(["/bin/sh", str(self.root / "render/f5_sc.sh")] + list(args),
                              capture_output=True, text=True, timeout=timeout)

    def test_context_helper_switches_and_reads_back(self):
        self.arm_ready()
        self.assertEqual(self.sc("gs").returncode, 74)
        result = self.sc("80")
        self.assertEqual(result.returncode, 80, result)
        self.assertEqual(self.dm_state()["cluster"], "80")
        self.assertEqual(self.sc("gs").returncode, 80)
        self.assertEqual(self.sc("74").returncode, 74)
        self.assertEqual(self.dm_state()["cluster"], "74")
        log = (self.tmp / "mu1320-f5-sc.log").read_text()
        self.assertIn("ctx=80 rc=0 reads=1 cluster=80 list=[98 102 101 33]", log)
        self.assertEqual(result.stdout + result.stderr, "", "helper output goes to its log only")
        sc_calls = [a for a in self.dm_state()["log"] if a[:1] == ["sc"]]
        self.assertEqual(sc_calls, [["sc", "4", "80"], ["sc", "4", "74"]], "cluster = internal display 4")

    def test_context_helper_is_fast_with_sigterm_ignored(self):
        # F5 v2 car run: children of the HMI JVM inherit SIGTERM ignored; the dmdt watchdog
        # then survived "kill" and every dm call waited 10 s (20 s per native switch).
        self.arm_ready()
        ignore = lambda: signal.signal(signal.SIGTERM, signal.SIG_IGN)
        for arg, expected in [("80", 80), ("gs", 80), ("74", 74)]:
            started = time.time()
            result = subprocess.run(["/bin/sh", str(self.root / "render/f5_sc.sh"), arg],
                                    capture_output=True, text=True, timeout=60, preexec_fn=ignore)
            self.assertEqual(result.returncode, expected, arg)
            self.assertLess(time.time() - started, 5, "helper %s with SIGTERM ignored" % arg)

    def test_context_helper_reports_where_the_cluster_really_is(self):
        self.arm_ready()
        started = time.time()
        result = self.sc("77")                  # not declared: displaymanager ignores it
        self.assertEqual(result.returncode, 74)
        self.assertLess(time.time() - started, 1.5, "a definite other context returns at once (v4: 2 s of re-reads)")
        self.assertIn("ctx=77 rc=0 reads=1 cluster=74", (self.tmp / "mu1320-f5-sc.log").read_text())

    def test_context_helper_usage_and_timeouts(self):
        self.arm_ready()
        for bad in [[], ["x"], ["200"], ["-1"], ["80 74"]]:
            self.assertEqual(self.sc(*bad).returncode, 252, bad)
        st = self.dm_state()
        st["hang"] = "sc"
        self.state.write_text(json.dumps(st))
        started = time.time()
        self.assertEqual(self.sc("80").returncode, 251)
        self.assertLess(time.time() - started, 25)
        st = self.dm_state()
        st["hang"] = "gs"
        self.state.write_text(json.dumps(st))
        self.assertEqual(self.sc("gs").returncode, 251)
        self.assertIn("GS_TIMEOUT", (self.tmp / "mu1320-f5-sc.log").read_text())

    def test_context_helper_without_runtime_files(self):
        self.arm_ready()
        (self.root / "render/f5_dm.sh").unlink()
        self.assertEqual(self.sc("80").returncode, 252)
        self.assertEqual(self.dm_state()["cluster"], "74")

    def test_arm_refuses_a_tampered_runtime_helper(self):
        self.ok("install")
        self.propagate()
        (self.tmp / "carplay_java.log").write_text(self.LISTENER)
        helper = self.root / "render/f5_sc.sh"
        helper.write_text(helper.read_text() + "# changed\n")
        result = self.run_action("arm", mode="no_dio")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("runtime context helper checksum", result.stdout + result.stderr)
        self.assertIsNone(self.renderer_pid())

    def test_arm_refuses_a_missing_runtime_shim(self):
        self.ok("install")
        self.propagate()
        (self.tmp / "carplay_java.log").write_text(self.LISTENER)
        (self.root / "render/f4_unbuf.so").unlink()
        result = self.run_action("arm", mode="no_dio")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("runtime dmdt stdout shim checksum", result.stdout + result.stderr)
        self.assertFalse((self.tmp / "mu1320-navhook-v1.arm").exists())

    def test_scripts_never_screenshot_and_pin_helper(self):
        sc = (BASE / self.STAGE / "f5_sc.sh").read_text()
        self.assertIn("/mnt/app/root/%s/render/f5_dm.sh" % self.RUNTIME, sc.replace("$RENDER", "/mnt/app/root/%s/render" % self.RUNTIME))
        for name in ["control.sh", self.COLLECTOR, "f5_dm.sh", self.WRAPPER, "f5_sc.sh"]:
            text = (BASE / self.STAGE / name).read_text()
            self.assertNotRegex(text, r"\bdm [^\n]*\bts\b")
            self.assertNotRegex(text, r"exists [^\n;]*&&\s*fail")
        control = (BASE / self.STAGE / "control.sh").read_text()
        self.assertRegex(control, r"check \d+ \d+ \"\$stage_dir/f5_dm.sh\" \|\| fail")
        self.assertLess(control.index("f5_dm.sh\" || fail"), control.index('. "$stage_dir/f5_dm.sh"'))


if __name__ == "__main__":
    unittest.main()
