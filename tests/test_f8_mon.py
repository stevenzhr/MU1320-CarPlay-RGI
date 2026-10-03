"""F8 monitor (f8-src/f8_mon.sh) on a fake vehicle: real shell code under sh and
ksh, fake pidin/mount/sloginfo/df, the mount_state contract of the car helper
(prints ro|rw), 1 s samples.  Checks the record, the SD mount round trip and the
shared lock, the singleton, the stop conditions and the copy-if-changed mirror."""
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
SOURCE = BASE / "f8/f8_mon.sh"
FOLDER = "mu1320-f7-daily-v2.1"
SHELLS = [s for s in ["/bin/sh", "/bin/ksh"] if Path(s).exists()]

FAKE_PIDIN = r'''import os, sys
a = sys.argv[1:]
procs = [("1", "0", "proc/boot/procnto-instr"), ("101", "1", "./bin/apps/smartphone_integrator"),
         ("202", "101", "mnt/app/eso/bin/apps/dio_manager"), ("300", "1", "ifs/jre/bin/j9"),
         ("400", "1", "eso/bin/apps/displaymanager"), ("500", "1", "usr/bin/other")]
if os.environ.get("F8_NO_DIO"):
    procs = [p for p in procs if p[0] != "202"]
threads = {"101": 7, "202": 29, "300": 41, "400": 12}
if a == ["info"]:
    print("CPU:ARM Release:6.5.0  FreeMem:123Mb/1024Mb BootTime:Jan 01 00:00:00 UTC 1970")
    print("Processes: %d, Threads: 300" % len(procs)); sys.exit(0)
if a == ["times"]:
    print("     pid name               start time      utime      stime     cutime     cstime")
    for p, _, n in procs: print("%8s %-18s Jan 01 00:00   1.000     0.500     0.000     0.000" % (p, n[-18:]))
    sys.exit(0)
if "-F" in a and "-p" not in a:
    for p, pp, n in procs: print("%8s %7s %s " % (p, pp, n))  # the car pads the name
    sys.exit(0)
p = a[a.index("-p") + 1]
if "mem" in a:
    print("     pid tid name               prio STATE            code  data        stack")
    for t in range(1, threads.get(p, 1) + 1):
        print("%8s %3d n/apps/x  10r CONDVAR             0 1984K  8192(132K)" % (p, t))
    print("            libc.so.3          @fe000000             452K   12K"); sys.exit(0)
if "fds" in a:
    print("      pid name"); [print("  %d  /dev/null" % i) for i in range(4)]; sys.exit(0)
sys.exit(1)
'''
FAKE_MOUNT = r'''#!/bin/sh
echo "$*" >> "$F8_MOUNT_CALLS"
case "$1" in -uw) echo rw > "$F8_SD_FLAG" ;; -ur) echo ro > "$F8_SD_FLAG" ;; *) exit 1 ;; esac
'''


class F8MonitorTests(unittest.TestCase):
    SHELL = "/bin/sh"

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="f8mon"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.procs = []
        self.addCleanup(self.kill_all)
        d = self.dir
        self.v = d / "vehicle"
        self.tmp = self.v / "tmp"
        self.root = self.v / "mnt/app/root/mu1320-rgi-f7-v2"
        self.mon = self.root / "mon"
        self.jar = self.v / "mnt/app/eso/hmi/lsd/jars/CarPlayRGI-MU1320-F7DailyV2.jar"
        self.sd = d / "sda0"
        self.folder = self.sd / FOLDER
        self.cmd = d / "commands"
        for p in [self.tmp, self.mon, self.jar.parent, self.folder, self.cmd, self.v / "mnt/ota/system/logs"]:
            p.mkdir(parents=True, exist_ok=True)
        (self.root / "IDENTITY").write_text("MU1320-F7-DAILY-V2\n")
        self.jar.write_text("jar")
        (self.folder / "TOOLBOX-ENTRY").write_text("MU1320_F7_TOOLBOX_ENTRY 1\n")
        (self.v / "mnt/ota/system/logs/smartphone_integrator_error_17").write_text("dump")
        self.sdflag = d / "sdflag"
        self.sdflag.write_text("ro\n")
        self.calls = d / "mount_calls"
        self.calls.write_text("")
        for name, body in [("pidin", "#!" + sys.executable + "\n" + FAKE_PIDIN), ("mount", FAKE_MOUNT),
                           ("sloginfo", "#!/bin/sh\necho 'Jan 01 00:00:01 5 10000 0 slog line'\n"),
                           ("df", "#!/bin/sh\necho \"df $*\"\n")]:
            (self.cmd / name).write_text(body)
            (self.cmd / name).chmod(0o755)
        (self.mon / "mount_state").write_text('#!/bin/sh\ncat "$F8_SD_FLAG"\n')
        (self.mon / "mount_state").chmod(0o755)
        self.script = self.mon / "f8_mon.sh"
        self.script.write_text(self.rewrite(SOURCE.read_text()))
        (self.tmp / "carplay_java.log").write_text("[CP/W][NavJava] MU1320-F7-DAILY-V2 LISTENER_READY\n")
        (self.tmp / "mu1320-f5-bap.log").write_text("B i=1 START\n")
        (self.tmp / "mu1320-f7-gate-202").write_text("MU1320_F7_GATE mode=ACTIVE pid=202\n")

    def rewrite(self, text, **consts):
        text = re.sub(r"^PATH=.*$", "PATH=%s:/usr/bin:/bin" % self.cmd, text, flags=re.M)
        text = re.sub(r"/mnt/app|/mnt/ota|/tmp", lambda m: str(self.v) + m.group(), text)
        text = text.replace("SDS='/fs/sda0 /fs/sdb0'", "SDS='%s %s/sdb0'" % (self.sd, self.dir))
        values = dict(SAMPLE_S="1", FLUSH_EVERY="2", SLOG_EVERY="5")
        values.update(consts)
        for key, value in values.items():
            text, n = re.subn(r"^%s=\S+$" % key, "%s=%s" % (key, value), text, flags=re.M)
            assert n == 1, key
        return text

    def env(self, **extra):
        return dict(os.environ, F8_SD_FLAG=str(self.sdflag), F8_MOUNT_CALLS=str(self.calls), **extra)

    def start(self, **extra):
        p = subprocess.Popen([self.SHELL, str(self.script), "run"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, env=self.env(**extra))
        self.procs.append(p)
        return p

    def kill_all(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
            p.wait(5)
            if p.stdout:
                p.stdout.close()

    def wait_for(self, cond, timeout=15, what="condition"):
        end = time.time() + timeout
        while time.time() < end:
            if cond():
                return
            time.sleep(0.1)
        self.fail("timeout waiting for " + what)

    def flushed(self, n):
        """n flushes finished (the state line is written after the lock is given back)."""
        state = self.tmp / "mu1320-f8-mon.state"
        m = re.search(r"flushes=(\d+)", state.read_text()) if state.exists() else None
        return bool(m) and int(m.group(1)) >= n and not (self.tmp / "mu1320-f8-sd.lock").exists()

    def boots(self):
        f8 = self.folder / "out/f8"
        return sorted(p for p in f8.glob("boot-*")) if f8.exists() else []

    def samples(self, boot=None):
        boot = boot or self.boots()[0]
        return (boot / "samples.txt").read_text() if (boot / "samples.txt").exists() else ""

    def stop(self, p, how="off"):
        if how == "off":
            (self.tmp / "mu1320-f8-mon-off").write_text("")
        else:
            p.send_signal(signal.SIGTERM)
        out, _ = p.communicate(timeout=20)
        return out

    # ---- cases ---------------------------------------------------------------------------
    def test_record_flush_and_sd_round_trip(self):
        p = self.start()
        self.wait_for(lambda: self.flushed(1), what="first flush")
        boot = self.boots()[0]
        self.assertRegex(boot.name, r"^boot-1-\d+$")
        self.assertEqual((self.folder / "out/f8/SEQ").read_text(), "1\n")
        text = self.samples()
        self.assertIn("=== START pid=", text)
        self.assertIn("MU1320-F7-DAILY-V2", text)
        self.assertIn("FreeMem:123Mb/1024Mb", text)
        self.assertIn("P dio_manager pid=202 ppid=101 threads=29 fds_lines=5", text)
        self.assertIn("P smartphone_integrator pid=101", text)
        self.assertIn("P j9 pid=300 ppid=1 threads=41", text)
        self.assertIn("P displaymanager pid=400", text)
        self.assertNotIn("P other", text)
        self.assertRegex(text, r"F \d+ \S+/tmp/carplay_java.log")
        self.assertEqual((boot / "logs/carplay_java.log").read_text(), (self.tmp / "carplay_java.log").read_text())
        self.assertTrue((boot / "logs/mu1320-f7-gate-202").is_file())
        self.assertIn("slog line", (boot / "logs/sloginfo.txt").read_text())
        self.assertIn("smartphone_integrator_error_17", text)
        self.assertEqual(self.sdflag.read_text(), "ro\n", "SD put back to ro after the flush")
        calls = self.calls.read_text().split("\n")
        self.assertEqual(calls[0], "-uw %s" % self.sd)
        self.assertEqual(calls[1], "-ur %s" % self.sd)
        self.assertFalse((self.tmp / "mu1320-f8-sd.lock").exists(), "lock released")
        self.assertEqual(list(boot.glob("logs/*.pending")), [])
        state = (self.tmp / "mu1320-f8-mon.state").read_text()
        self.assertRegex(state, r"^MON pid=%d samples=\d+ flushes=\d+ sd_bytes=\d+ dir=\S+boot-1-\d+ mirror=1 end=running"
                         % p.pid)
        out = self.stop(p)
        self.assertIn("MON END pid=%d reason=off" % p.pid, out)
        self.assertIn("=== END reason=off", self.samples())
        self.assertFalse((self.tmp / "mu1320-f8-mon.run").exists())
        self.assertEqual(self.sdflag.read_text(), "ro\n")
        self.assertEqual(self.calls.read_text().count("-uw"), self.calls.read_text().count("-ur"))

    def test_rw_sd_is_left_alone(self):
        self.sdflag.write_text("rw\n")
        p = self.start()
        self.wait_for(lambda: bool(self.boots()) and "=== S 2" in self.samples(), what="flush")
        self.stop(p)
        self.assertEqual(self.calls.read_text(), "", "no remount of a rw card")
        self.assertEqual(self.sdflag.read_text(), "rw\n")

    def test_single_instance_per_boot(self):
        p = self.start()
        self.wait_for(lambda: (self.tmp / "mu1320-f8-mon.run").exists(), what="run file")
        second = self.start()
        out, _ = second.communicate(timeout=10)
        self.assertEqual(second.returncode, 0)
        self.assertIn("MON DUPLICATE pid=%d holder=%d" % (second.pid, p.pid), out)
        self.assertEqual((self.tmp / "mu1320-f8-mon.run").read_text(), "%d\n" % p.pid, "holder kept")
        self.stop(p)

    def test_stale_run_file_of_a_dead_pid_is_replaced(self):
        dead = subprocess.Popen(["true"])
        dead.wait()
        (self.tmp / "mu1320-f8-mon.run").write_text("%d\n" % dead.pid)
        p = self.start()
        self.wait_for(lambda: (self.tmp / "mu1320-f8-mon.run").read_text() == "%d\n" % p.pid, what="takeover")
        self.stop(p)

    def test_without_sd_samples_wait_in_the_buffer(self):
        shutil.rmtree(self.folder)
        p = self.start()
        time.sleep(3.5)
        self.assertEqual(self.calls.read_text(), "")
        self.assertIn("=== S 2", (self.tmp / "mu1320-f8-mon.buf").read_text())
        self.folder.mkdir(parents=True)
        (self.folder / "TOOLBOX-ENTRY").write_text("MU1320_F7_TOOLBOX_ENTRY 1\n")
        self.wait_for(lambda: bool(self.boots()) and "=== S 1 " in self.samples(), what="late flush")
        out = self.stop(p)
        self.assertIn("MON NO_SD", out)
        self.assertIn("=== START", self.samples())

    def test_folder_without_toolbox_entry_is_not_used(self):
        (self.folder / "TOOLBOX-ENTRY").unlink()
        p = self.start()
        time.sleep(3.5)
        self.stop(p)
        self.assertFalse((self.folder / "out").exists())

    def test_busy_lock_skips_the_flush_and_a_dead_holder_is_replaced(self):
        holder = subprocess.Popen(["sleep", "60"])
        self.procs.append(holder)
        (self.tmp / "mu1320-f8-sd.lock").write_text("%d\n" % holder.pid)
        p = self.start()
        time.sleep(2.5)  # first flush after sample 2 waits on the lock (up to 20 s)
        self.assertEqual(self.calls.read_text(), "", "no remount while f7.sh holds the lock")
        self.assertEqual(self.boots(), [])
        holder.kill()
        holder.wait()
        self.wait_for(lambda: bool(self.boots()) and "=== S 2" in self.samples(), timeout=25, what="flush after holder died")
        self.stop(p)
        self.assertFalse((self.tmp / "mu1320-f8-sd.lock").exists())

    def test_final_flush_waits_for_a_rollback_holding_the_lock(self):
        p = self.start()
        self.wait_for(lambda: self.flushed(1), what="first flush")
        holder = subprocess.Popen(["sleep", "60"])
        self.procs.append(holder)
        (self.tmp / "mu1320-f8-sd.lock").write_text("%d\n" % holder.pid)
        self.jar.unlink()
        time.sleep(8)  # longer than the old 5 s
        self.assertIsNone(p.poll(), "still waiting for the lock")
        holder.kill()
        holder.wait()
        out, _ = p.communicate(timeout=20)
        self.assertIn("reason=uninstalled", out)
        self.assertIn("=== END reason=uninstalled", self.samples())

    def test_uninstall_ends_the_monitor_with_a_final_flush(self):
        p = self.start()
        self.wait_for(lambda: "=== S 1 " in (self.tmp / "mu1320-f8-mon.buf").read_text()
                      if (self.tmp / "mu1320-f8-mon.buf").exists() else False, what="sample")
        self.jar.unlink()
        out, _ = p.communicate(timeout=20)
        self.assertIn("reason=uninstalled", out)
        self.assertIn("=== END reason=uninstalled", self.samples())
        self.assertEqual(self.sdflag.read_text(), "ro\n")

    def test_persistent_off_switch(self):
        (self.root / "off-monitor").write_text("")
        p = self.start()
        out, _ = p.communicate(timeout=15)
        self.assertIn("reason=off-persistent samples=0", out)

    def test_sigterm_flushes_and_ends(self):
        p = self.start()
        time.sleep(1.5)
        out = self.stop(p, how="term")
        self.assertIn("reason=term", out)
        self.assertIn("=== END reason=term", self.samples())
        self.assertFalse((self.tmp / "mu1320-f8-mon.run").exists())

    def test_unchanged_logs_are_not_copied_again(self):
        p = self.start()
        self.wait_for(lambda: bool(self.boots()) and (self.boots()[0] / "logs/mu1320-f5-bap.log").exists(), what="copy")
        boot = self.boots()[0]
        (boot / "logs/mu1320-f5-bap.log").unlink()
        n = self.calls.read_text().count("-uw")
        self.wait_for(lambda: self.calls.read_text().count("-uw") >= n + 1, what="next flush")
        time.sleep(0.5)
        self.assertFalse((boot / "logs/mu1320-f5-bap.log").exists(), "unchanged log copied again")
        time.sleep(1.1)  # ls -ln time has minute resolution on some systems: change the size too
        with (self.tmp / "mu1320-f5-bap.log").open("a") as f:
            f.write("B i=2 TEARDOWN\n")
        self.wait_for(lambda: (boot / "logs/mu1320-f5-bap.log").exists(), what="changed log copied")
        self.stop(p)

    def test_second_boot_gets_the_next_sequence(self):
        p = self.start()
        self.wait_for(lambda: bool(self.boots()), what="boot 1")
        self.stop(p)
        for f in self.tmp.glob("mu1320-f8-*"):
            f.unlink()  # a reboot clears /tmp
        p2 = self.start()
        self.wait_for(lambda: len(self.boots()) == 2, what="boot 2")
        self.stop(p2)
        self.assertEqual((self.folder / "out/f8/SEQ").read_text(), "2\n")
        self.assertTrue(any(b.name.startswith("boot-2-%d" % p2.pid) for b in self.boots()))

    def test_big_logs_wait_for_every_fifth_flush(self):
        self.script.write_text(self.rewrite(SOURCE.read_text(), BIG="100", BIG_EVERY="5"))
        (self.tmp / "mu1320-f5-state.log").write_text("x" * 500)
        p = self.start()
        self.wait_for(lambda: bool(self.boots()) and (self.boots()[0] / "logs/mu1320-f5-state.log").exists(),
                      what="big copy on flush 1")
        with (self.tmp / "mu1320-f5-state.log").open("a") as f:
            f.write("y" * 100)
        n = self.calls.read_text().count("-uw")
        self.wait_for(lambda: self.calls.read_text().count("-uw") >= n + 2, timeout=20, what="two flushes")
        self.assertEqual((self.boots()[0] / "logs/mu1320-f5-state.log").stat().st_size, 500, "big log waits")
        self.stop(p)
        self.assertEqual((self.boots()[0] / "logs/mu1320-f5-state.log").stat().st_size, 600, "final flush copies it")

    def test_sd_byte_cap_stops_log_mirroring_only(self):
        self.script.write_text(self.rewrite(SOURCE.read_text(), SD_CAP="10"))
        p = self.start()
        self.wait_for(lambda: bool(self.boots()) and "=== S 4" in self.samples(), timeout=20, what="two flushes")
        self.stop(p)
        self.assertIn("=== MIRROR_CAP", self.samples())
        self.assertIn("mirror=0", (self.tmp / "mu1320-f8-mon.state").read_text())

    def test_buffer_cap(self):
        shutil.rmtree(self.folder)
        self.script.write_text(self.rewrite(SOURCE.read_text(), BUF_CAP="200"))
        p = self.start()
        time.sleep(2.5)
        self.stop(p)
        self.assertIn("=== BUFFER_DROPPED cap=200", (self.tmp / "mu1320-f8-mon.buf").read_text())

    def test_no_writes_outside_tmp_and_sd(self):
        before = sorted(str(x) for x in (self.v / "mnt").rglob("*"))
        p = self.start()
        self.wait_for(lambda: bool(self.boots()) and "=== S 2" in self.samples(), what="flush")
        self.stop(p)
        self.assertEqual(sorted(str(x) for x in (self.v / "mnt").rglob("*")), before)

    def test_source_rules(self):
        text = SOURCE.read_text()
        code = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
        self.assertNotIn("set -e", code)
        self.assertNotIn("dmdt", code)
        self.assertNotRegex(code, r"exists [^\n;]*&&\s*fail")
        self.assertNotRegex(code, r"\bmv [^\n]*/tmp/", "no rename on /dev/shmem")
        self.assertIn("FOLDER=%s\n" % FOLDER, text)
        self.assertIn("ROOT=/mnt/app/root/mu1320-rgi-f7-v2\n", text)
        self.assertIn("LOCK=/tmp/mu1320-f8-sd.lock\n", text)


for _shell in SHELLS[1:]:
    _name = "F8MonitorTests_" + Path(_shell).name
    globals()[_name] = type(_name, (F8MonitorTests,), {"SHELL": _shell})


if __name__ == "__main__":
    unittest.main()
