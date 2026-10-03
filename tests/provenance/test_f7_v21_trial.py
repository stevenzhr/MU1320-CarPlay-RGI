"""F7 v2.1 SD folder (F8 candidate): the whole F7 v2 transaction suite rerun on the
v2.1 folder (the monitor switched off with /tmp/mu1320-f8-mon-off so the inherited
mount assertions stay exact), plus the F8 additions on the same fake vehicle:
the keeper starting the monitor once per boot, the monitor flushing into the
SD folder and ending at rollback, the persistent monitor switch, the SD lock
f7.sh shares with the monitor, the purge reboot guard, status and collect."""
import hashlib
import json
import os
import re
import subprocess
import threading
import time
import unittest

import test_f7_trial as v1
import test_f7_v2_trial as v2

BASE = v1.BASE
STAGE = BASE / "mu1320-f7-daily-v2.1"
V2 = BASE / "mu1320-f7-daily-v2"
pair = v1.pair


class F7V21TrialTests(v2.F7V2TrialTests):
    STAGE = "mu1320-f7-daily-v2.1"

    def setUp(self):
        super().setUp()
        sd = self.f.sd
        vehicle = str(self.f.vehicle)
        mon = sd / "f8_mon.sh"
        old_mon = pair(mon)
        text = re.sub(r"^PATH=.*$", "PATH=%s:/usr/bin:/bin" % self.f.commands, mon.read_text(), flags=re.M)
        text = re.sub(r"/mnt/app|/mnt/ota|/tmp", lambda m: vehicle + m.group(), text)
        # The fixture SD folder is f.sd itself: the monitor looks for <sd>/<FOLDER>.
        text = text.replace("SDS='/fs/sda0 /fs/sdb0'", "SDS='%s'" % sd.parent)
        text = text.replace("FOLDER=mu1320-f7-daily-v2.1\n", "FOLDER=%s\n" % sd.name)
        text = re.sub(r"^SAMPLE_S=\S+$", "SAMPLE_S=1", text, flags=re.M)
        mon.write_text(text)
        mon.chmod(0o755)
        new_mon = pair(mon)
        keeper, control, wrapper = sd / "f7_render.sh", sd / "control.sh", sd / "f7.sh"
        old_keeper = pair(keeper)
        ktext = keeper.read_text()
        self.assertIn(" ".join(old_mon), ktext)
        ktext = ktext.replace(" ".join(old_mon), " ".join(new_mon))
        # the fixture replaced mount_state (control.sh was re-pinned by the fixture)
        ktext = ktext.replace("2952412687 7302", " ".join(pair(sd / "mount_state")))
        keeper.write_text(ktext)
        old_control = pair(control)
        ctext = control.read_text()
        for old, new in [(old_mon, new_mon), (old_keeper, pair(keeper))]:
            self.assertIn(" ".join(old), ctext)
            ctext = ctext.replace(" ".join(old), " ".join(new))
        control.write_text(ctext)
        wrapper.write_text(wrapper.read_text().replace(
            "'%s' ] && [ \"${2:-}\" = '%s' ] || fail 'control checksum'" % tuple(old_control),
            "'%s' ] && [ \"${2:-}\" = '%s' ] || fail 'control checksum'" % tuple(pair(control))))
        self.mon_off = self.tmp / "mu1320-f8-mon-off"
        self.mon_off.write_text("")  # inherited cases: no monitor (exact mount assertions)
        self.addCleanup(self.kill_monitor)

    # ---- helpers -----------------------------------------------------------------------
    def keeper_env(self):
        env = super().keeper_env()
        env.update(MOUNT_FLAG=str(self.f.flag), SYSTEM_FLAG=str(self.env.s3.sysflag), SD_FLAG=str(self.sdflag),
                   MOUNT_CALLS=str(self.f.calls))
        return env

    def monitor_pid(self):
        run = self.tmp / "mu1320-f8-mon.run"
        text = run.read_text().strip() if run.exists() else ""
        return int(text) if text.isdigit() else None

    def kill_monitor(self):
        pid = self.monitor_pid()
        if pid and self.alive(pid):
            os.kill(pid, 9)

    def wait_for(self, cond, timeout=20, what="condition"):
        end = time.time() + timeout
        while time.time() < end:
            if cond():
                return
            time.sleep(0.1)
        self.fail("timeout waiting for " + what)

    def boots(self):
        f8 = self.f.sd / "out/f8"
        return sorted(f8.glob("boot-*")) if f8.exists() else []

    def flushed(self):
        state = self.tmp / "mu1320-f8-mon.state"
        m = re.search(r"flushes=(\d+)", state.read_text()) if state.exists() else None
        return bool(m) and int(m.group(1)) >= 1 and not (self.tmp / "mu1320-f8-sd.lock").exists()

    def monitored(self):
        """install, reboot, keeper with the monitor allowed."""
        self.mon_off.unlink()
        self.arm_ready()
        self.wait_for(lambda: self.monitor_pid() is not None, what="monitor start")
        return self.monitor_pid()

    # ---- F8 monitor ------------------------------------------------------------------------
    def test_install_puts_the_monitor_into_the_workspace(self):
        out = self.ok("install").stdout
        self.assertIn("write runtime monitor", out)
        self.assertIn("write runtime monitor mount helper", out)
        for name in ["f8_mon.sh", "mount_state"]:
            path = self.root / "mon" / name
            self.assertEqual(path.read_bytes(), (self.f.sd / name).read_bytes(), name)
            self.assertEqual(path.stat().st_mode & 0o777, 0o755, name)
        status = self.ok("status").stdout
        for line in ["F8_MONITOR: ABSENT", "F8_MONITOR_STATE: NONE", "SWITCH_monitor: on", "OTHER_WORKSPACES: "]:
            self.assertIn(line, status)
        self.assertNotRegex(status, r"OTHER_WORKSPACES:.*%s" % re.escape(self.RUNTIME + " "))
        (self.root / "mon/f8_mon.sh").write_text("tampered\n")
        result = self.run_action("off", "monitor")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("runtime monitor checksum", result.stdout + result.stderr)

    def test_keeper_starts_one_monitor_that_flushes_and_ends_at_rollback(self):
        pid = self.monitored()
        self.assertTrue(self.alive(pid))
        self.assertRegex(self.keeper_log(), r"KEEP MON SPAWNED pid=%d" % pid)
        self.assertEqual(self.keep().returncode, 0)
        self.assertEqual(self.keeper_log().count("MON SPAWNED"), 1, "one monitor per boot")
        self.wait_for(self.flushed, what="first flush")
        boot = self.boots()[0]
        samples = (boot / "samples.txt").read_text()
        self.assertIn("=== START pid=%d" % pid, samples)
        self.assertIn("MU1320-F7-DAILY-V2", samples)
        self.assertRegex(samples, r"P dio_manager pid=202 ppid=101 threads=\d+")
        self.assertTrue((boot / "logs/carplay_java.log").is_file())
        self.assertTrue((boot / "logs/mu1320-f7-keeper.log").is_file())
        self.assertEqual(self.sdflag.read_text(), "ro\n")
        status = self.ok("status").stdout
        self.assertIn("F8_MONITOR: RUNNING pid=%d" % pid, status)
        self.assertRegex(status, r"F8_MONITOR_STATE: MON pid=%d samples=\d+ flushes=\d+" % pid)
        collect = self.ok("collect", "snapshot")
        self.assertIn("COPIED: %s/mu1320-f8-mon.state" % self.tmp, collect.stdout)
        self.assertIn("F7_SWITCH[monitor]=on", collect.stdout)
        result = self.ok("rollback")
        self.assertIn("F7_ACTION_PASSED", result.stdout)
        self.wait_for(lambda: not self.alive(pid), what="monitor end after rollback")
        self.assertIn("=== END reason=uninstalled", (boot / "samples.txt").read_text())
        self.assertIn("MON END pid=%d reason=uninstalled" % pid, (self.tmp / "mu1320-f8-mon.log").read_text())
        self.assertEqual(self.sdflag.read_text(), "ro\n")
        self.assertFalse((self.tmp / "mu1320-f8-sd.lock").exists())
        status = self.ok("status").stdout
        self.assertIn("F8_MONITOR: ENDED", status)
        self.assertRegex(status, r"F8_MONITOR_STATE: MON pid=%d .* end=uninstalled" % pid)

    def test_monitor_starts_even_when_the_keeper_is_held(self):
        self.mon_off.unlink()
        self.ok("install")
        self.propagate()
        (self.tmp / "carplay_java.log").write_text(self.LISTENER)
        (self.tmp / "mu1320-f7-render-hold").write_text("")
        self.assertEqual(self.keep().returncode, 10)
        self.assertIn("KEEP HELD hold", self.keeper_log())
        self.wait_for(lambda: self.monitor_pid() is not None, what="monitor")
        self.assertIn("KEEP MON SPAWNED", self.keeper_log())

    def test_monitor_switches(self):
        self.mon_off.unlink()
        self.ok("install")
        self.propagate()
        out = self.ok("off", "monitor").stdout
        self.assertIn("F7_SWITCH: monitor=OFF persistent, effective off: within 60 s", out)
        self.assertTrue((self.root / "off-monitor").exists())
        self.assertIn("SWITCH_monitor: OFF_PERSISTENT", self.ok("status").stdout)
        (self.tmp / "carplay_java.log").write_text(self.LISTENER)
        self.assertEqual(self.keep().returncode, 0)
        self.assertIn("KEEP MON off", self.keeper_log())
        self.assertIsNone(self.monitor_pid())
        self.ok("on", "monitor")
        self.assertFalse((self.root / "off-monitor").exists())
        self.assertEqual(self.keep().returncode, 0)
        self.wait_for(lambda: self.monitor_pid() is not None, what="monitor after on")

    def test_monitor_tampered_in_the_workspace_is_not_started(self):
        self.mon_off.unlink()
        self.ok("install")
        self.propagate()
        (self.root / "mon/f8_mon.sh").write_text("#!/bin/sh\necho evil\n")
        (self.tmp / "carplay_java.log").write_text(self.LISTENER)
        self.assertEqual(self.keep().returncode, 0, "the keeper itself is not failed by the monitor")
        self.assertIn("KEEP MON_FAIL monitor checksum", self.keeper_log())
        self.assertIsNone(self.monitor_pid())

    # ---- shared SD lock -----------------------------------------------------------------------
    def test_wrapper_waits_for_the_sd_lock_and_releases_it(self):
        lock = self.tmp / "mu1320-f8-sd.lock"
        holder = subprocess.Popen(["sleep", "30"])
        self.addCleanup(holder.kill)
        lock.write_text("%d\n" % holder.pid)
        threading.Timer(2.0, lambda: (holder.kill(), lock.unlink())).start()
        out = self.ok("status").stdout
        self.assertRegex(out, r"SD_LOCK_WAITED: [1-4]s")
        self.assertIn("F7_ACTION_PASSED", out)
        self.assertFalse(lock.exists(), "released after the action")

    def test_wrapper_replaces_a_dead_lock_holder(self):
        dead = subprocess.Popen(["true"])
        dead.wait()
        lock = self.tmp / "mu1320-f8-sd.lock"
        lock.write_text("%d\n" % dead.pid)
        out = self.ok("status").stdout
        self.assertNotIn("SD_LOCK_WAITED", out)
        self.assertFalse(lock.exists())

    def test_wrapper_gives_up_on_a_busy_sd_without_touching_it(self):
        holder = subprocess.Popen(["sleep", "60"])
        self.addCleanup(holder.kill)
        lock = self.tmp / "mu1320-f8-sd.lock"
        lock.write_text("%d\n" % holder.pid)
        calls = self.f.calls.read_text() if self.f.calls.exists() else ""
        result = subprocess.run(["/bin/sh", str(self.f.sd / "f7.sh"), "status"], capture_output=True, text=True,
                                timeout=60, env=self.keeper_env())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SD busy for 30 s", result.stdout + result.stderr)
        self.assertEqual(self.f.calls.read_text() if self.f.calls.exists() else "", calls, "no remount")
        self.assertEqual(lock.read_text(), "%d\n" % holder.pid, "foreign lock kept")
        self.assertEqual(self.sdflag.read_text(), "ro\n")

    # ---- purge reboot guard ----------------------------------------------------------------------
    def test_purge_refuses_in_the_rollback_boot(self):
        self.ok("install")
        self.propagate()
        (self.tmp / "carplay_java.log").write_text(self.LISTENER)
        self.ok("rollback")
        self.propagate()  # the car's /etc copy follows at once (F7 v2 R4)
        result = self.run_action("purge")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("F7 Java ran in this boot: reboot after rollback, then purge", result.stdout + result.stderr)
        self.assertTrue(self.root.exists())
        (self.tmp / "carplay_java.log").unlink()
        (self.tmp / "carplay_java.log.1").write_text(self.LISTENER)
        self.assertNotEqual(self.run_action("purge").returncode, 0, "rotated log counts too")
        (self.tmp / "carplay_java.log.1").unlink()
        self.ok("purge")
        self.assertFalse(self.root.exists())
        self.assert_mounts()

    def test_purge_refuses_while_the_monitor_runs(self):
        self.ok("install")
        self.propagate()
        self.ok("rollback")
        self.propagate()
        sleeper = subprocess.Popen(["sleep", "30"])
        self.addCleanup(sleeper.kill)
        (self.tmp / "mu1320-f8-mon.run").write_text("%d\n" % sleeper.pid)
        result = self.run_action("purge")
        self.assertIn("F8 monitor still running", result.stdout + result.stderr)
        sleeper.kill()
        sleeper.wait()
        self.ok("purge")

    def test_purge_refuses_while_a_hooked_dio_runs(self):
        self.ok("install")
        self.propagate()
        candidate = self.tmp.parent / "candidate-si.json"
        candidate.write_bytes(self.active.read_bytes())  # what the still-running DIO was started with
        self.ok("rollback")
        self.propagate()
        env = self.keeper_env()
        env["ACTIVE_FILE"] = str(candidate)
        result = subprocess.run(["/bin/sh", str(self.f.sd / "f7.sh"), "purge"], capture_output=True, text=True,
                                timeout=25, env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DIO 202 carries the F7 hook", result.stdout + result.stderr)
        self.assertTrue(self.root.exists())
        self.ok("purge")

    # ---- status: other workspaces --------------------------------------------------------------
    def test_status_lists_other_workspaces(self):
        for name in ["mu1320-rgi-f7-v1.1", "mu1320-rgi-f6-v3"]:
            (self.f.app / "root" / name).mkdir(parents=True)
        (self.f.app / "root" / "unrelated").mkdir(parents=True)
        self.ok("install")
        status = self.ok("status").stdout
        line = [l for l in status.splitlines() if l.startswith("OTHER_WORKSPACES:")][0].split()[1:]
        expect = sorted(p.name for p in (self.f.app / "root").iterdir() if p.name.startswith("mu1320-rgi-") and p != self.root)
        self.assertEqual(line, expect)
        self.assertIn("mu1320-rgi-f7-v1.1", line)
        self.assertNotIn("unrelated", line)

    def test_wrapper_usage_names_the_monitor(self):
        result = self.run_action("off", "everything")
        self.assertEqual(result.returncode, 2)
        self.assertIn("native|render|bap|touchpad|monitor", result.stdout)


class F7V21FolderTests(unittest.TestCase):
    def sums(self, folder):
        return dict(reversed(line.split("  ", 1)) for line in (folder / "SHA256SUMS").read_text().splitlines())

    def test_sums_match_files(self):
        sums = self.sums(STAGE)
        self.assertEqual(sorted(sums), sorted(p.name for p in STAGE.iterdir() if p.is_file() and p.name != "SHA256SUMS"))
        for name, digest in sums.items():
            self.assertEqual(hashlib.sha256((STAGE / name).read_bytes()).hexdigest(), digest, name)

    def test_f7_v2_folder_is_untouched(self):
        issued = json.loads((BASE / "reports/f7-v2-prepare.json").read_text())["files"]
        for name, digest in issued.items():
            if name == "OBSERVATIONS-F7.txt":
                continue
            self.assertEqual(hashlib.sha256((V2 / name).read_bytes()).hexdigest(), digest, name)

    def test_runtime_binaries_and_configs_are_the_car_run_v2_bytes(self):
        old, new = self.sums(V2), self.sums(STAGE)
        for name in ["libcarplay_hook.so", "carplay_mu1320_f7_daily_v2.jar.DISABLED", "maneuver_render", "flag_atlas.rgba",
                     "f7_spawn", "f4_unbuf.so", "mount_state", "loader_check", "smartphone_integrator.json",
                     "dio_manager.json", "IDENTITY", "f5_sc.sh", "f5_dm.sh", "f7_mark.sh", "trial_gate.c"]:
            self.assertEqual(new[name], old[name], name)

    def test_scripts_are_v2_plus_the_reviewed_hunks(self):
        import prepare_f7_v21_daily as prep
        def norm(text):
            text = re.sub(r"'\d{6,10}' \] && \[ \"\$\{2:-\}\" = '\d+'", "PIN", text)
            return re.sub(r"\b\d{6,10} \d{1,7}\b", "CRC SIZE", text)
        for name in prep.PATCHED:
            old = norm((V2 / name).read_text())
            for a, b in prep.HUNKS[name]:
                b = b.replace("@MON@", "1234567 1").replace("@MOUNT@", "1234567 1")
                self.assertEqual(old.count(norm(a)), 1, (name, a[:50]))
                old = old.replace(norm(a), norm(b))
            self.assertEqual(old, norm((STAGE / name).read_text()), name)

    def test_monitor_is_pinned_everywhere(self):
        out = subprocess.check_output(["cksum", str(STAGE / "f8_mon.sh")], text=True).split()
        pin = "%s %s" % (out[0], out[1])
        control = (STAGE / "control.sh").read_text()
        self.assertEqual(control.count(pin), 3, "payload, runtime, put_file")
        self.assertEqual((STAGE / "f7_render.sh").read_text().count(pin), 1)
        self.assertIn("FOLDER=mu1320-f7-daily-v2.1\n", (STAGE / "f8_mon.sh").read_text())

    def test_toolbox_entry_and_single_menu_folder(self):
        lines = (STAGE / "TOOLBOX-ENTRY").read_text().splitlines()
        self.assertEqual(lines, ["MU1320_F7_TOOLBOX_ENTRY 1", "build=MU1320-F7-DAILY-V2.1", "wrapper=f7.sh"])

    def test_readme_and_sheet(self):
        readme = (STAGE / "README.md").read_text()
        for word in ["/fs/sda0/mu1320-f7-daily-v2.1/f7.sh status", "Customization > MU1320 RGI", "TOOLBOX-ENTRY",
                     "mu1320-f7-daily-v2/", "out/f8/", "f7.sh off monitor", "mu1320-f7-daily-v1.1/f7.sh purge",
                     "OTHER_WORKSPACES", "F8_MONITOR", "B10", "B14"]:
            self.assertIn(word, readme)
        self.assertNotRegex(readme, r"dmdt ts\b(?!`)")
        sheet = (STAGE / "OBSERVATIONS-F8.txt").read_text()
        for step in ["L1", "M1", "N1", "S1", "X1", "U1"]:
            self.assertRegex(sheet, r"(?m)^%s(  |$)" % step)
        self.assertNotRegex(sheet, r"[A-Za-z]{4,} [a-z]{3,} [a-z]{3,}", "sheet is Chinese")


if __name__ == "__main__":
    unittest.main()
