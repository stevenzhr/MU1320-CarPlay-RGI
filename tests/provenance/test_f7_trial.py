"""Host transaction tests for the F7 v1 SD folder.

The F5/F6 fake vehicle (navjava -> F3 -> F5 fixture chain) runs the real F7
shell code.  Transaction tests that do not involve arm are inherited as they
are; arm-only cases are retired (F7 has no arm) and replaced by keeper,
stop, persistent switch, purge and launcher cases.  f7_spawn is compiled for
the host from f7-src/f7_spawn.c.
"""
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

import test_f5_trial as f5

BASE = f5.BASE
STAGE_DIR = BASE / "mu1320-f7-daily-v1"
F6 = BASE / "mu1320-f6-accept-v2"
pair = f5.pair
SPAWN_PROBE = r'''#!/usr/bin/env python3
import os, signal, sys, json
fds = sorted(int(x) for x in os.listdir('/dev/fd'))
json.dump({"term": str(signal.getsignal(signal.SIGTERM)), "hup": str(signal.getsignal(signal.SIGHUP)),
           "fds": fds, "sid_is_pid": os.getsid(0) == os.getpid(), "cwd": os.getcwd(),
           "preload": os.environ.get("LD_PRELOAD"), "graphics": os.environ.get("GRAPHICS_ROOT"),
           "args": sys.argv[1:]}, open(os.environ["PROBE_OUT"], "w"))
'''


def host_spawn(directory):
    out = Path(directory) / "f7_spawn"
    subprocess.run(["cc", "-std=gnu99", "-Wall", "-Wextra", "-Werror", str(BASE / "f7-src/f7_spawn.c"),
                    "-o", str(out)], check=True, capture_output=True)
    return out


@unittest.skipUnless(shutil.which("cc"), "host C compiler required")
class F7TrialTests(f5.F5TrialTests):
    STAGE = "mu1320-f7-daily-v1"
    RUNTIME = "mu1320-rgi-f7-v1"
    NEW_JAR = "CarPlayRGI-MU1320-F7DailyV1.jar"
    PAYLOAD_JAR = "carplay_mu1320_f7_daily_v1.jar.DISABLED"
    WRAPPER = "f7.sh"
    COLLECTOR = "collect_f7.sh"
    LISTENER = ("[CP/W][NavJava] MU1320-F7-DAILY-V1 LISTENER_READY bap-yield+render; "
                "NavActiveIgnore quarantined; renderer 98 via ctx 80; keeper auto\n")

    @staticmethod
    def label(member):
        return member.replace("F5_", "F7_") if isinstance(member, str) else member

    def assertIn(self, member, container, msg=None):
        super().assertIn(self.label(member), container, msg)

    def assertNotIn(self, member, container, msg=None):
        super().assertNotIn(self.label(member), container, msg)

    def setUp(self):
        super().setUp()
        sd = self.f.sd
        vehicle = str(self.f.vehicle)
        keeper, spawn = sd / "f7_render.sh", sd / "f7_spawn"
        old = {"keeper": pair(keeper), "spawn": pair(spawn), "helper": pair(sd / "f5_dm.sh")}
        text = re.sub(r"/mnt/app|/tmp", lambda m: vehicle + m.group(), keeper.read_text())
        # The fixture replaced the helper, renderer and dmdt: pin what the keeper checks.
        for name in ["maneuver_render", "f5_dm.sh"]:
            text = re.sub(r"check \d+ \d+ (\"\$RENDER/%s\")" % re.escape(name),
                          lambda m, n=name: "check %s %s %s" % (pair(sd / n) + (m.group(1),)), text)
        tmpdir = Path(tempfile.mkdtemp(prefix="f7spawn"))
        self.addCleanup(shutil.rmtree, tmpdir, True)
        shutil.copyfile(host_spawn(tmpdir), spawn)
        spawn.chmod(0o755)
        text = re.sub(r'check \d+ \d+ ("\$RENDER/f7_spawn")', lambda m: "check %s %s %s" % (pair(spawn) + (m.group(1),)), text)
        keeper.write_text(text)
        keeper.chmod(0o755)
        control = sd / "control.sh"
        before = pair(control)
        text = control.read_text()
        for key, path in [("keeper", keeper), ("spawn", spawn)]:
            self.assertIn(" ".join(old[key]), text, key)
            text = text.replace(" ".join(old[key]), " ".join(pair(path)))
        control.write_text(text)
        wrapper = sd / self.WRAPPER
        wrapper.write_text(wrapper.read_text().replace(
            "'%s' ] && [ \"${2:-}\" = '%s' ] || fail 'control checksum'" % before,
            "'%s' ] && [ \"${2:-}\" = '%s' ] || fail 'control checksum'" % pair(control)))

    # ---- helpers -------------------------------------------------------------
    def keeper_env(self):
        # The keeper prepends the vehicle PATH; the fake pidin must still be found.
        return dict(os.environ, PATH="%s:%s" % (self.f.commands, os.environ["PATH"]),
                    ACTIVE_FILE=str(self.active), ENV_MARKER=self.ENV_MARKER, RUNTIME_ROOT=str(self.root),
                    PID_MODE="", DIO_PID="202")

    def keep(self, timeout=90):
        return subprocess.run(["/bin/sh", str(self.root / "render/f7_render.sh"), "up"], capture_output=True,
                              text=True, timeout=timeout, env=self.keeper_env())

    def keeper_log(self):
        path = self.tmp / "mu1320-f7-keeper.log"
        return path.read_text() if path.exists() else ""

    def arm_ready(self):
        """F7 has no arm: install, reboot (propagate) and let the keeper bring the renderer up."""
        self.ok("install")
        self.propagate()
        (self.tmp / "carplay_java.log").write_text(self.LISTENER)
        result = self.keep()
        self.assertEqual(result.returncode, 0, self.keeper_log())
        return result

    def assert_java_evidence(self, stdout):
        # F5 evidence checks with the F7 collect phase "live" instead of "armed".
        out = self.f.sd / "out"
        live = [p for p in out.iterdir() if p.name.startswith("live-")]
        for p in live:
            p.rename(out / p.name.replace("live-", "armed-"))
        try:
            super().assert_java_evidence(stdout)
        finally:
            for p in out.iterdir():
                if p.name.startswith("armed-"):
                    p.rename(out / p.name.replace("armed-", "live-"))

    # ---- retired arm-only cases (F7 has no arm) --------------------------------
    test_arm_requires_java_listener_marker = None
    test_arm_detects_dio_with_vehicle_padded_pidin_name = None
    test_arm_refuses_when_navactiveignore_is_back_in_scan_tree = None
    test_navjava_and_f2_listener_markers_do_not_arm_f3 = None
    test_v1_listener_marker_does_not_arm_v2 = None
    test_f3_listener_markers_do_not_arm_f5 = None
    test_arm_refuses_when_cluster_already_on_80 = None
    test_disarm_stops_renderer_and_restores_cluster_left_on_80 = None
    test_disarm_without_renderer_leaves_stock_cluster_alone = None
    test_disarm_fails_when_cluster_stays_on_80 = None
    test_disarm_fails_and_rollback_warns_when_displaymanager_is_silent = None
    test_arm_fails_and_stops_renderer_without_java_link = None
    test_arm_fails_when_renderer_init_fails = None
    test_arm_refuses_foreign_displayable_98_and_wrong_context_80 = None
    test_arm_refuses_a_tampered_runtime_helper = None
    test_arm_refuses_a_missing_runtime_shim = None

    # ---- replaced / adapted -----------------------------------------------------
    def test_install_arm_parse_collect_and_rollback(self):
        """install -> reboot -> keeper (instead of arm) -> collect live -> rollback -> collect restored."""
        install = self.ok("install")
        self.assertIn("write runtime renderer launcher", install.stdout)
        self.assertIn("write runtime renderer keeper", install.stdout)
        self.assertTrue(self.new.is_file())
        self.assert_quarantined()
        for name in ["maneuver_render", "flag_atlas.rgba", "f5_sc.sh", "f5_dm.sh", "f4_unbuf.so", "f7_spawn", "f7_render.sh"]:
            self.assertEqual((self.root / "render" / name).read_bytes(), (self.f.sd / name).read_bytes(), name)
        for name in ["maneuver_render", "f5_sc.sh", "f7_spawn", "f7_render.sh"]:
            self.assertEqual((self.root / "render" / name).stat().st_mode & 0o777, 0o755, name)
        status = self.ok("status").stdout
        for line in ["JAVA_ARCHIVE: F7_INSTALLED", "F7_RENDERER: ABSENT", "DM_CONTEXT_80: ABSENT", "SWITCH_native: on",
                     "RENDER_HOLD: ABSENT", "GATE_STRIKES: ABSENT", "JAVA_LISTENER: ABSENT", "KEEPER_LAST: NONE"]:
            self.assertIn(line, status)
        self.assertNotIn("TOKEN:", status)
        self.assertNotEqual(self.run_action("arm").returncode, 0, "arm is gone")

        self.propagate()
        (self.tmp / "carplay_java.log").write_text(self.LISTENER)
        up = self.keep()
        self.assertEqual(up.returncode, 0, self.keeper_log())
        self.assertEqual(up.stdout + up.stderr, "", "keeper output goes to its log only")
        log = self.keeper_log()
        self.assertRegex(log, r"KEEP READY pid=\d+ d98=\S+ \S+ started=1 ctx80=now")
        pid = self.renderer_pid()
        self.assertTrue(pid and self.alive(pid))
        self.assertIn("atlas=True graphics=/proc/boot", (self.tmp / "mu1320-f5-renderer.log").read_text())
        st = self.dm_state()
        self.assertEqual(st["contexts"]["80"], [98, 102, 101, 33])
        self.assertEqual(st["cluster"], "74", "the keeper never switches the cluster")
        again = self.keep()
        self.assertEqual(again.returncode, 0)
        self.assertIn("KEEP ALIVE pid=%d" % pid, self.keeper_log())
        self.assertIn("started=0 ctx80=existing", self.keeper_log())
        self.assertEqual(self.renderer_pid(), pid)
        self.assertEqual(len([a for a in self.dm_state()["log"] if a[:1] == ["dc"]]), 1)

        (self.tmp / "mu1320-f7-gate-202").write_text(
            "MU1320_F7_GATE mode=ACTIVE reason=ON pid=202 ppid=101 strikes=0 prev=0 prev_alive=0\n")
        (self.tmp / "mu1320-f7-gate.last").write_text("202 1000\n")
        (self.tmp / "mu1320-f7-gate.strikes").write_text("0\n")
        (self.tmp / "carplay_hook.log").write_text("Registered module 'routeguidance'\nUpdate: state=6\n")
        self.write_java_evidence()
        with (self.tmp / "mu1320-f5-render.log").open("a") as r:
            r.write("R i=1 t=10 KEEPER_UP why=hello run=1 failures=0\nR i=1 t=900 KEEPER_READY run=1\n")
        status = self.ok("status").stdout
        self.assertIn("JAVA_LISTENER: F7_READY", status)
        self.assertIn("GATE_LAST: 202 1000", status)
        self.assertRegex(status, r"KEEPER_LAST: KEEP READY pid=%d" % pid)
        live = self.ok("collect", "live")
        self.assertIn("GLOBAL_GATE_RECEIPT_COUNT=1", live.stdout)
        self.assertIn("mode=ACTIVE reason=ON pid=202", live.stdout)
        self.assertIn("GATE_RECORD: %s/tmp/mu1320-f7-gate.last 202 1000" % self.f.vehicle, live.stdout)
        self.assertIn("F7_KEEPER_COUNT[KEEP READY]=2", live.stdout)
        self.assertIn("F7_RENDER_COUNT[ KEEPER_READY]=1", live.stdout)
        self.assertIn("F7_SWITCH[native]=on", live.stdout)
        self.assert_java_evidence(live.stdout)
        self.assertIn("F7_RENDERER: RUNNING pid=%d" % pid, live.stdout)
        self.assertIn("DIO_ENV_MARKER=1 DIO_ENV_PRELOAD=1", live.stdout)
        self.assertNotEqual(self.run_action("collect", "armed").returncode, 0, "phase armed is gone")

        rollback = self.ok("rollback")
        self.assertIn("RENDERER_STOP: pid=%d" % pid, rollback.stdout)
        time.sleep(0.3)
        self.assertFalse(self.alive(pid))
        self.assertTrue((self.tmp / "mu1320-f7-render-hold").exists())
        self.assertTrue((self.tmp / "mu1320-f7-native-off").exists())
        self.assertFalse(self.new.exists())
        self.assertEqual(self.old.read_bytes(), self.old_bytes)
        self.assertEqual((self.root / "phase.txt").read_text(), "INSTALLATION_BASELINE_RESTORED\n")
        held = self.keep()
        self.assertEqual(held.returncode, 10, "the still-loaded Java keeper must not restart the renderer")
        self.assertIsNone(self.renderer_pid())
        self.propagate()
        for path in list(self.tmp.iterdir()):
            if path.is_file() or path.is_symlink():
                path.unlink()
        restored = self.ok("collect", "restored", dio_pid="303")
        self.assertIn("DIO_ENV_MARKER=0 DIO_ENV_PRELOAD=0", restored.stdout)
        self.assertIn("F7_RENDERER: ABSENT", restored.stdout)
        self.assert_mounts()

    def test_scripts_keep_globbing_for_global_receipts_and_avoid_and_fail(self):
        collector = (BASE / self.STAGE / self.COLLECTOR).read_text()
        self.assertNotRegex(collector, r"(?m)^set -f$")
        self.assertIn("for f in /tmp/mu1320-f7-gate-*", collector)
        for name in ["control.sh", "f7_render.sh", self.WRAPPER]:
            self.assertNotRegex((BASE / self.STAGE / name).read_text(), r"exists [^\n;]*&&\s*fail")

    def test_scripts_never_screenshot_and_pin_helper(self):
        super().test_scripts_never_screenshot_and_pin_helper()
        keeper = (BASE / self.STAGE / "f7_render.sh").read_text()
        self.assertNotRegex(keeper, r"\bdm [^\n]*\bts\b")
        self.assertLess(keeper.index('"$RENDER/f5_dm.sh" || fail'), keeper.index('. "$RENDER/f5_dm.sh"'))

    def test_v1_runtime_workspace_is_not_touched(self):
        others = [self.f.app / "root" / n for n in ["mu1320-rgi-f5-v5", "mu1320-rgi-f6-v2", "mu1320-rgi-f3-v2"]]
        for other in others:
            other.mkdir(parents=True, mode=0o700)
            (other / "phase.txt").write_text("INSTALLATION_BASELINE_RESTORED\n")
        self.ok("install")
        self.ok("rollback", direct=True)
        for other in others:
            self.assertEqual((other / "phase.txt").read_text(), "INSTALLATION_BASELINE_RESTORED\n")

    # ---- keeper ---------------------------------------------------------------------
    def installed(self):
        self.ok("install")
        self.propagate()
        (self.tmp / "carplay_java.log").write_text(self.LISTENER)

    def test_keeper_fails_and_stops_renderer_without_java_link(self):
        os.environ["F5_FAKE_RENDER"] = "no-java"
        self.installed()
        self.assertEqual(self.keep().returncode, 12, self.keeper_log())
        self.assertIn("did not reach the Java listener", self.keeper_log())
        self.assertIsNone(self.renderer_pid())
        self.assertNotIn("80", self.dm_state()["contexts"], "no context declared when the keeper fails")

    def test_keeper_reports_renderer_init_failure(self):
        os.environ["F5_FAKE_RENDER"] = "init-fail"
        self.installed()
        self.assertEqual(self.keep().returncode, 11)
        self.assertIn("renderer exited during init", self.keeper_log())
        self.assertIsNone(self.renderer_pid())

    def test_keeper_refuses_foreign_98_and_a_different_context_80(self):
        self.installed()
        foreign = subprocess.Popen(["sleep", "30"])
        self.addCleanup(foreign.wait)
        self.addCleanup(foreign.kill)
        st = self.dm_state()
        st["d98_pid"] = foreign.pid
        self.state.write_text(json.dumps(st))
        self.assertEqual(self.keep().returncode, 16)
        self.assertIsNone(self.renderer_pid())
        st = self.dm_state()
        st["d98_pid"] = None
        st["contexts"]["80"] = [98, 33]
        self.state.write_text(json.dumps(st))
        self.assertEqual(self.keep().returncode, 14)
        self.assertIn("context 80 declared as [98 33]", self.keeper_log())
        self.assertIsNone(self.renderer_pid(), "a renderer the keeper started is stopped again")

    def test_keeper_refuses_tampered_runtime_files(self):
        self.installed()
        for name, message in [("f5_dm.sh", "displaymanager helper checksum"), ("f4_unbuf.so", "dmdt stdout shim checksum"),
                              ("f7_spawn", "launcher checksum"), ("maneuver_render", "renderer checksum")]:
            path = self.root / "render" / name
            data = path.read_bytes()
            path.write_bytes(data + b"#")
            self.assertEqual(self.keep().returncode, 17, name)
            self.assertIn(message, self.keeper_log())
            path.write_bytes(data)
        self.assertIsNone(self.renderer_pid())

    def test_keeper_is_held_by_hold_off_render_or_missing_archive(self):
        self.installed()
        (self.tmp / "mu1320-f7-render-hold").write_text("")
        self.assertEqual(self.keep().returncode, 10)
        (self.tmp / "mu1320-f7-render-hold").unlink()
        (self.root / "off-render").write_text("")
        self.assertEqual(self.keep().returncode, 10)
        (self.root / "off-render").unlink()
        self.new.rename(self.root / "moved.jar")
        self.assertEqual(self.keep().returncode, 10)
        self.assertEqual(self.keeper_log().count("KEEP HELD"), 3)
        self.assertIsNone(self.renderer_pid())
        self.assertEqual(self.dm_state().get("log", []), [], "a held keeper never talks to displaymanager")

    def test_keeper_with_jvm_signal_state_starts_a_clean_renderer(self):
        # F5 v3: children of the HMI JVM inherit SIGTERM ignored.  The keeper still
        # finishes quickly and its renderer gets default SIGTERM (stop works).
        self.installed()
        ignore = lambda: signal.signal(signal.SIGTERM, signal.SIG_IGN)
        started = time.time()
        result = subprocess.run(["/bin/sh", str(self.root / "render/f7_render.sh"), "up"],
                                capture_output=True, text=True, timeout=60, preexec_fn=ignore, env=self.keeper_env())
        self.assertEqual(result.returncode, 0, self.keeper_log())
        self.assertLess(time.time() - started, 15)
        pid = self.renderer_pid()
        stop = self.ok("stop")
        self.assertIn("RENDERER_STOP: pid=%d" % pid, stop.stdout)
        self.assertIn("caught SIGTERM", (self.tmp / "mu1320-f5-renderer.log").read_text(),
                      "SIGTERM reached the renderer: the JVM's ignore disposition was reset")

    def test_keeper_truncates_its_own_log(self):
        self.installed()
        (self.tmp / "mu1320-f7-keeper.log").write_text("x" * 300000)
        self.keep()
        log = self.keeper_log()
        self.assertLess(len(log), 10000)
        self.assertIn("KEEP LOG_TRUNCATED bytes=300000", log)

    def test_keeper_usage(self):
        self.installed()
        for args in [[], ["down"], ["up", "x"]]:
            result = subprocess.run(["/bin/sh", str(self.root / "render/f7_render.sh")] + args,
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 252, args)

    # ---- stop, switches, purge -------------------------------------------------------
    def test_stop_holds_until_reboot_and_restores_cluster_left_on_80(self):
        self.arm_ready()
        pid = self.renderer_pid()
        st = self.dm_state()
        st["cluster"] = "80"
        self.state.write_text(json.dumps(st))
        result = self.ok("stop")
        self.assertIn("RENDERER_STOP: pid=%d" % pid, result.stdout)
        self.assertIn("CLUSTER_ON_80: switching to 74", result.stdout)
        self.assertIn("F7_STOPPED", result.stdout)
        self.assertEqual(self.dm_state()["cluster"], "74")
        self.assertTrue((self.tmp / "mu1320-f7-render-hold").exists())
        self.assertTrue((self.tmp / "mu1320-f7-native-off").exists())
        self.assertEqual(self.keep().returncode, 10)
        status = self.ok("status").stdout
        self.assertIn("RENDER_HOLD: PRESENT", status)
        self.assertIn("NATIVE_RUNTIME_OFF: PRESENT", status)

    def test_stop_fails_when_cluster_stays_on_80(self):
        self.arm_ready()
        st = self.dm_state()
        st["cluster"] = "80"
        st["hang"] = "sc"
        self.state.write_text(json.dumps(st))
        result = self.run_action("stop")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("WARNING: cluster still on context 80", result.stdout)
        self.assertNotIn("F7_ACTION_PASSED", result.stdout)

    def test_rollback_warns_when_displaymanager_is_silent(self):
        self.arm_ready()
        st = self.dm_state()
        st["hang"] = "gs"
        self.state.write_text(json.dumps(st))
        result = self.run_action("rollback")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("WARNING: cluster not confirmed off context 80", result.stdout)
        self.assertFalse(self.new.exists())

    def test_persistent_switches_on_and_off(self):
        self.ok("install")
        for component in ["native", "render", "bap", "touchpad"]:
            result = self.ok("off", component)
            self.assertIn("F7_SWITCH: %s=OFF persistent" % component, result.stdout)
            self.assertIn("F7_off_FILES_PASSED", result.stdout)
            target = self.root / ("off-" + component)
            self.assertTrue(target.is_file())
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertIn("SWITCH_%s: OFF_PERSISTENT" % component, self.ok("status").stdout)
            self.ok("off", component)  # idempotent
            self.assert_mounts()
        self.assertIn("from the next DIO start", self.ok("off", "native").stdout)
        self.assertIn("within 2 s", self.ok("off", "bap").stdout)
        for component in ["native", "render", "bap", "touchpad"]:
            self.ok("on", component)
            self.assertFalse((self.root / ("off-" + component)).exists())
            self.ok("on", component)  # idempotent
        self.assert_mounts()

    def test_switches_need_an_installation_and_a_known_component(self):
        self.assertNotEqual(self.run_action("off", "native").returncode, 0)
        self.assertFalse(self.root.exists())
        self.ok("install")
        for args in [("off", "hook"), ("off",), ("on", "java"), ("off", "native", "x")]:
            self.assertNotEqual(self.run_action(*args).returncode, 0, args)
        self.ok("rollback")
        self.assertNotEqual(self.run_action("off", "native").returncode, 0, "rolled back: no switches")

    def test_rollback_keeps_switch_files_and_reinstall_reuses_them(self):
        self.ok("install")
        self.ok("off", "touchpad")
        self.ok("rollback")
        self.assertTrue((self.root / "off-touchpad").exists())
        self.ok("install")
        self.assertIn("SWITCH_touchpad: OFF_PERSISTENT", self.ok("status").stdout)

    def test_purge_after_rollback_and_reboot_only(self):
        self.assertNotEqual(self.run_action("purge").returncode, 0, "nothing to purge")
        self.ok("install")
        self.propagate()
        result = self.run_action("purge")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("purge needs a completed rollback", result.stdout + result.stderr)
        self.ok("rollback")
        result = self.run_action("purge")
        self.assertNotEqual(result.returncode, 0, "active SI is still F7 until the reboot")
        self.assertIn("reboot after rollback", result.stdout + result.stderr)
        self.propagate()
        self.old.write_bytes(self.old_bytes + b"x")
        self.assertNotEqual(self.run_action("purge").returncode, 0)
        self.old.write_bytes(self.old_bytes)
        result = self.ok("purge")
        self.assertIn("F7_PURGED", result.stdout)
        self.assertFalse(self.root.exists())
        self.assert_mounts()
        again = self.ok("install")
        self.assertNotIn("RESUME_WORKSPACE", again.stdout)
        self.assertTrue(self.new.is_file())

    def test_wrapper_rejects_old_and_unknown_actions(self):
        for args in [("arm",), ("disarm",), ("collect", "armed"), ("off", "hook"), ("stop", "now")]:
            result = self.run_action(*args)
            self.assertEqual(result.returncode, 2, args)
            self.assertIn("usage: f7.sh", result.stdout)

    def test_no_f6_or_arm_labels_in_output(self):
        self.ok("install")
        self.propagate()
        (self.tmp / "carplay_java.log").write_text(self.LISTENER)
        for out in [self.ok("status").stdout, self.ok("collect", "snapshot").stdout, self.ok("rollback").stdout]:
            for line in out.splitlines():
                if re.search(r"F6|ARMED|TOKEN", line.replace("MU1320-F5-VCHUD-V5", "")):
                    self.fail("stale label: " + line)


@unittest.skipUnless(shutil.which("cc"), "host C compiler required")
class F7SpawnTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="f7spawn"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.spawn = host_spawn(self.dir)
        self.probe = self.dir / "probe.py"
        self.probe.write_text(SPAWN_PROBE)
        self.probe.chmod(0o755)
        self.work = self.dir / "work"
        self.work.mkdir()

    def launch(self, preexec=None, extra_env=None, pass_fds=()):
        out = self.dir / "probe.json"
        env = dict(os.environ, PROBE_OUT=str(out), LD_PRELOAD="/nonexistent/hook.so", GRAPHICS_ROOT="/elsewhere")
        env.update(extra_env or {})
        result = subprocess.run([str(self.spawn), str(self.dir / "pid"), str(self.dir / "log"), str(self.work),
                                 str(self.probe), "a", "b"], env=env, preexec_fn=preexec, pass_fds=pass_fds,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        for _ in range(100):
            if out.exists() and out.stat().st_size:
                break
            time.sleep(0.05)
        return json.loads(out.read_text()), int((self.dir / "pid").read_text())

    def test_child_is_detached_with_default_signals_and_no_leaked_descriptors(self):
        leak = os.open(str(self.dir / "leak"), os.O_CREAT | os.O_WRONLY)
        self.addCleanup(os.close, leak)

        def jvm_like():
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
        info, pid = self.launch(preexec=jvm_like, pass_fds=(leak,))
        self.assertIn("SIG_DFL", info["term"])
        self.assertIn("SIG_IGN", info["hup"])
        self.assertTrue(info["sid_is_pid"])
        self.assertLessEqual(max(info["fds"]), 3, info["fds"])  # 0-2 plus the listdir handle
        self.assertEqual(os.path.realpath(info["cwd"]), os.path.realpath(str(self.work)))
        self.assertIsNone(info["preload"])
        self.assertEqual(info["graphics"], "/proc/boot")
        self.assertEqual(info["args"], ["a", "b"])
        self.assertEqual((self.dir / "pid").stat().st_mode & 0o777, 0o600)

    def test_usage_and_missing_program(self):
        result = subprocess.run([str(self.spawn), "x"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        result = subprocess.run([str(self.spawn), str(self.dir / "pid"), str(self.dir / "log"), str(self.work),
                                 str(self.dir / "missing")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, "the launcher returns before the exec")
        pid = int((self.dir / "pid").read_text())
        time.sleep(0.3)
        self.assertNotEqual(subprocess.run(["kill", "-0", str(pid)], capture_output=True).returncode, 0)


class F7FolderTests(unittest.TestCase):
    def test_sums_match_files(self):
        sums = dict(reversed(l.split("  ", 1)) for l in (STAGE_DIR / "SHA256SUMS").read_text().splitlines())
        names = sorted(p.name for p in STAGE_DIR.iterdir() if p.is_file() and p.name != "SHA256SUMS")
        self.assertEqual(sorted(sums), names)
        import hashlib
        for name in names:
            self.assertEqual(hashlib.sha256((STAGE_DIR / name).read_bytes()).hexdigest(), sums[name], name)

    def test_carried_files_are_f6_v2_and_no_arm_token(self):
        import hashlib
        f6 = dict(reversed(l.split("  ", 1)) for l in (F6 / "SHA256SUMS").read_text().splitlines())
        for name in ["loader_check", "mount_state", "dio_manager.json", "maneuver_render", "flag_atlas.rgba", "f4_unbuf.so"]:
            self.assertEqual(hashlib.sha256((STAGE_DIR / name).read_bytes()).hexdigest(), f6[name], name)
        self.assertFalse((STAGE_DIR / "ARM-TOKEN").exists())
        for name in ["control.sh", "collect_f7.sh", "f7.sh", "f7_render.sh", "f5_sc.sh", "f5_dm.sh"]:
            text = (STAGE_DIR / name).read_text()
            self.assertNotIn("mu1320-rgi-f6-v2", text, name)
            self.assertNotIn("navhook-v1", text, name)

    def test_scripts_name_only_the_f7_workspace(self):
        for name in ["control.sh", "collect_f7.sh", "f7_render.sh", "f5_sc.sh", "f5_dm.sh", "smartphone_integrator.json"]:
            roots = set(re.findall(r"/mnt/app/root/(mu1320[\w.-]*)", (STAGE_DIR / name).read_text()))
            self.assertEqual(roots, {"mu1320-rgi-f7-v1"}, name)

    def test_readme_documents_the_daily_actions(self):
        readme = (STAGE_DIR / "README.md").read_text()
        for word in ["f7.sh install", "f7.sh rollback", "f7.sh stop", "f7.sh off native", "f7.sh purge",
                     "collect live", "不需要 arm"]:
            self.assertIn(word, readme)


if __name__ == "__main__":
    unittest.main()
