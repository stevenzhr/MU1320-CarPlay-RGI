"""Host tests for the MU1320 Toolbox v1 package (the F7 green menu).

The overlay is "installed" into a fake engdefs tree with absolute paths rewritten into the
fixture, and run the way the HMI starts GEM scripts (Toolbox v0 on the car: PATH and
LD_LIBRARY_PATH begin with ".", umask 000, cwd /mnt/app/eso).  f7.sh on the fake SD is a
stub that records how it was called and replays real F7 v1.1 car output (status, install,
stop, collect, rollback) with the wrapper's trailer lines.
TB_SHELL=/bin/ksh runs the scripts under ksh (the car's /bin/sh is a ksh).
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
STAGE = BASE / 'mu1320-toolbox-v1'
UPSTREAM = BASE.parent / 'mib2-toolbox'
DUMP = BASE.parent / 'resource/private/vehicle-dump/f7-daily-v1.1'
SHELL = os.environ.get('TB_SHELL', '/bin/sh')
BUTTONS = {'status': ['status'], 'install': ['install'], 'uninstall': ['rollback'],
           'collect': ['collect', 'snapshot'], 'stop': ['stop']}
ENGDEFS_DIR = '/eso/hmi/engdefs/scripts/mqb/mu1320'

FAKE_F7 = r'''#!/bin/sh
# fake f7.sh: record the call, replay canned output, emit the wrapper trailer
here=${0%/*}
{
  echo "ARGS=$*"; echo "CWD=$(pwd)"; echo "UMASK=$(umask)"
  echo "LD=${LD_LIBRARY_PATH-unset}"; echo "PRELOAD=${LD_PRELOAD-unset}"; echo "PATH=$PATH"
} > "$here/called.txt"
mode=$(cat "$here/mode" 2>/dev/null)
[ -z "$FAKE_SLEEP" ] || sleep "$FAKE_SLEEP"
[ ! -f "$here/canned.txt" ] || cat "$here/canned.txt"
case "$mode" in
  fail) echo 'STOP: baseline SI required at both paths' >&2
        echo "ACTION_LOG_ON_SD: $here/out/action-$1-4242.txt"; echo 'CONTROL_EXIT: 1'; echo 'OUTER_EXIT: 1'; exit 1 ;;
  nolog) echo 'STOP: effective UID must be 0' >&2; exit 1 ;;
esac
echo "SD_MOUNT_RESTORED: /fs/sda0=ro"
echo "ACTION_LOG_ON_SD: $here/out/action-$1-4242.txt"
echo 'CONTROL_EXIT: 0'; echo 'OUTER_EXIT: 0'
echo 'EVIDENCE_NOTE: save this terminal tail with the SD action log; final SD state occurs after the log is closed.'
echo 'F7_ACTION_PASSED'
'''


def canned(name):
    return (DUMP / name).read_text()


class Fixture:
    def __init__(self, test):
        self.root = Path(tempfile.mkdtemp(prefix='tbv1')).resolve()
        test.addCleanup(shutil.rmtree, self.root, True)
        self.sda, self.sdb = self.root / 'fs/sda0', self.root / 'fs/sdb0'
        self.tmp = self.root / 'tmp'
        self.eng = self.root / 'engdefs/mu1320'
        self.cwd = self.root / 'mnt/app/eso'
        for d in (self.sda, self.tmp, self.eng, self.cwd):
            d.mkdir(parents=True)
        src = STAGE / 'Toolbox/scripts/mu1320'
        for p in src.iterdir():
            text = p.read_text()
            text = text.replace(ENGDEFS_DIR, str(self.eng))
            text = text.replace("F7M_SDS='/fs/sda0 /fs/sdb0'", "F7M_SDS='%s %s'" % (self.sda, self.sdb))
            text = text.replace('/tmp/', str(self.tmp) + '/')
            (self.eng / p.name).write_text(text)
            (self.eng / p.name).chmod(0o755)

    def folder(self, name='mu1320-f7-daily-v2', sd=None, entry='MU1320_F7_TOOLBOX_ENTRY 1\nbuild=X\nwrapper=f7.sh\n',
               mode='', output=''):
        d = (sd or self.sda) / name
        d.mkdir(parents=True)
        if entry is not None:
            (d / 'TOOLBOX-ENTRY').write_text(entry)
        (d / 'f7.sh').write_text(FAKE_F7)
        (d / 'mode').write_text(mode)
        (d / 'canned.txt').write_text(output)
        return d

    def press(self, button, env_extra=None, timeout=60):
        env = {'PATH': '.:/usr/bin:/bin', 'LD_LIBRARY_PATH': '.:/proc/boot:/root/lib-target:rel/lib:/ifs/jre/bin',
               'LD_PRELOAD': '/x/evil.so', 'HOME': '/var', 'TERM': 'vt100'}
        env.update(env_extra or {})
        return subprocess.run([SHELL, '-c', 'umask 000; cd "$1" && exec %s "$2"' % SHELL, 'gem', str(self.cwd),
                               str(self.eng / ('f7_%s.sh' % button))],
                              capture_output=True, text=True, timeout=timeout, env=env)


class DispatcherTests(unittest.TestCase):
    def setUp(self):
        self.f = Fixture(self)

    def called(self, d):
        return dict(line.split('=', 1) for line in (d / 'called.txt').read_text().splitlines())

    def assert_screen(self, out):
        lines = out.splitlines()
        self.assertLessEqual(len(lines), 10, out)
        for line in lines:
            self.assertLessEqual(len(line), 60, line)
        return lines

    def test_each_button_runs_its_f7_action_in_a_clean_environment(self):
        d = self.f.folder()
        for button, args in BUTTONS.items():
            r = self.f.press(button)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            c = self.called(d)
            self.assertEqual(c['ARGS'], ' '.join(args), button)
            self.assertEqual(c['CWD'], '/')
            self.assertEqual(c['UMASK'], '0022')
            self.assertEqual(c['LD'], '/proc/boot:/root/lib-target:/ifs/jre/bin')
            self.assertEqual(c['PRELOAD'], 'unset')
            self.assertTrue(c['PATH'].startswith('/proc/boot:/bin:'), c['PATH'])
            self.assertNotIn('.:', c['PATH'])
            lines = self.assert_screen(r.stdout)
            self.assertEqual(lines[0], 'MU1320 F7: %s' % button)
            self.assertEqual(lines[1], 'Folder: mu1320-f7-daily-v2')
            self.assertEqual(lines[-1], 'RESULT: OK')
            self.assertIn('Log: out/action-%s-4242.txt' % args[0], lines)
        self.assertEqual(sorted(p.name for p in self.f.tmp.iterdir()), [], 'lock and output removed')

    def test_only_relative_library_entries_are_dropped(self):
        d = self.f.folder()
        self.f.press('status', {'LD_LIBRARY_PATH': '.:lib'})
        self.assertEqual(self.called(d)['LD'], 'unset')

    def test_status_summary_from_a_real_car_status(self):
        d = self.f.folder(output=canned('action-status-10838158.txt'))
        r = self.f.press('status')
        lines = self.assert_screen(r.stdout)
        self.assertEqual(lines[2], 'SI: F7_TRIAL/F7_TRIAL')
        self.assertEqual(lines[3], 'JAVA: F7_INSTALLED  NAVIGNORE: QUARANTINED')
        self.assertRegex(lines[4], r'^LISTENER: F7_READY  RENDER: (RUNNING|ABSENT)$')
        self.assertRegex(lines[5], r'^CLUSTER: \d+  HOLD: (ABSENT|PRESENT)  BAPOFF: (ABSENT|PRESENT)$')
        self.assertRegex(lines[6], r'^GATE: strikes=\S+ last=\S+$')
        self.assertRegex(lines[7], r'^OFF \(persistent\):')
        self.assertEqual(lines[-2:], ['Log: out/action-status-4242.txt', 'RESULT: OK'])
        self.assertEqual(r.returncode, 0)
        self.assertTrue(self.called(d))

    def test_status_summary_for_a_baseline_unit_with_the_v2_gate_fields(self):
        text = canned('action-status-10838158.txt')
        text = re.sub(r'(?m)^SYSTEM_CONFIG: .*$', 'SYSTEM_CONFIG: BASELINE', text)
        text = re.sub(r'(?m)^ACTIVE_CONFIG: .*$', 'ACTIVE_CONFIG: BASELINE', text)
        text = re.sub(r'(?m)^GATE_STRIKES: .*$', 'GATE_STRIKES: 3', text)
        text = re.sub(r'(?m)^GATE_LAST: .*$', 'GATE_LAST: 13115511 684000', text)
        text = re.sub(r'(?m)^SWITCH_touchpad: .*$', 'SWITCH_touchpad: OFF_PERSISTENT', text)
        self.f.folder(output=text)
        lines = self.assert_screen(self.f.press('status').stdout)
        self.assertEqual(lines[2], 'SI: BASELINE/BASELINE')
        self.assertEqual(lines[6], 'GATE: strikes=3 last=13115511')
        self.assertEqual(lines[7], 'OFF (persistent): touchpad')

    def test_install_and_uninstall_ask_for_a_restart(self):
        self.f.folder(output=canned('action-install-9203780.txt'))
        lines = self.assert_screen(self.f.press('install').stdout)
        self.assertIn('F7_install_FILES_PASSED: no restart performed', lines)
        self.assertEqual(lines[-2:], ['NEXT: full restart of the MMI', 'RESULT: OK'])
        shutil.rmtree(self.f.sda / 'mu1320-f7-daily-v2')
        self.f.folder(output=canned('action-rollback-17952887.txt'))
        lines = self.assert_screen(self.f.press('uninstall').stdout)
        self.assertEqual(lines[-2:], ['NEXT: full restart of the MMI', 'RESULT: OK'])
        self.assertTrue(any(l.startswith('F7_rollback_FILES_PASSED') or l.startswith('ROLLBACK_ALREADY')
                            for l in lines), lines)

    def test_stop_shows_the_java_release(self):
        text = canned('action-stop-20070542.txt').replace(
            'RENDERER_STOP:', 'JAVA_RELEASE: BAP_OFF\nJAVA_CLUSTER_CONTEXT: 74 waited=1s\nRENDERER_STOP:', 1)
        text = text.replace("F7_STOPPED: renderer stopped and held, next DIO passive, until the next reboot; "
                            "an already-active DIO stays active until USB is disconnected",
                            "F7_STOPPED: BAP off (VC/HUD stock), renderer stopped and held, next DIO passive, "
                            "until the next reboot; touchpad unchanged")
        self.f.folder(output=text)
        lines = self.assert_screen(self.f.press('stop').stdout)
        self.assertEqual(lines[2:6], ['JAVA_RELEASE: BAP_OFF', 'JAVA_CLUSTER_CONTEXT: 74 waited=1s',
                                      'DISARM_CLUSTER_CONTEXT: 74 restored=1',
                                      'F7_STOPPED: BAP off (VC/HUD stock), renderer stopped and hel'])
        self.assertEqual(lines[-1], 'RESULT: OK')
        self.assertNotIn('NEXT: full restart of the MMI', lines)

    def test_collect_names_the_saved_directory(self):
        self.f.folder(output=canned('action-collect-3817615.txt'))
        lines = self.assert_screen(self.f.press('collect').stdout)
        self.assertIn('COLLECT_EXIT=0', lines)
        self.assertIn('Saved: out/live-3907729', lines)
        self.assertIn('DIO_PROCESSES_OBSERVED=1', lines)
        self.assertFalse(any(l.startswith('F7_SWITCH') or l.startswith('(+') for l in lines), lines)
        self.assertEqual(lines[-1], 'RESULT: OK')

    def test_failures_show_the_stop_line_and_the_exit_code(self):
        self.f.folder(mode='fail', output='SYSTEM_CONFIG: UNKNOWN\n')
        r = self.f.press('install')
        lines = self.assert_screen(r.stdout)
        self.assertEqual(r.returncode, 1)
        self.assertIn('STOP: baseline SI required at both paths', lines)
        self.assertEqual(lines[-2:], ['Log: out/action-install-4242.txt', 'RESULT: FAILED (1)'])
        self.assertNotIn('NEXT: full restart of the MMI', lines)
        shutil.rmtree(self.f.sda / 'mu1320-f7-daily-v2')
        self.f.folder(mode='nolog')
        lines = self.assert_screen(self.f.press('status').stdout)
        self.assertIn('STOP: effective UID must be 0', lines)
        self.assertEqual(lines[-2:], ['Log: none (see the lines above)', 'RESULT: FAILED (1)'])
        self.assertFalse(any(l.startswith('SI: ') for l in lines), 'no summary without a status')

    def test_many_warnings_are_capped(self):
        self.f.folder(output=''.join('WARNING: w%d\n' % i for i in range(9)) + 'F7_STOPPED: x\n')
        lines = self.assert_screen(self.f.press('stop').stdout)
        self.assertEqual(lines[2:7], ['WARNING: w0', 'WARNING: w1', 'WARNING: w2', 'WARNING: w3',
                                      '(+6 more lines in the log)'])

    def test_folder_discovery(self):
        r = self.f.press('status')
        self.assertEqual(r.returncode, 2)
        self.assertIn('NO F7 FOLDER', r.stdout)
        self.assertEqual(r.stdout.splitlines()[-1], 'RESULT: FAILED')
        # older folders (no TOOLBOX-ENTRY), a wrong entry and a symlink do not count
        self.f.folder('mu1320-f7-daily-v1.1', entry=None)
        self.f.folder('mu1320-f7-daily-vX', entry='SOMETHING ELSE\n')
        other = self.f.folder('elsewhere', sd=self.f.root)
        (self.f.sda / 'mu1320-f7-link').symlink_to(other)
        self.assertIn('NO F7 FOLDER', self.f.press('status').stdout)
        d = self.f.folder()
        r = self.f.press('status')
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertTrue((d / 'called.txt').exists())
        for n in ['mu1320-f7-daily-v1.1', 'mu1320-f7-daily-vX', 'elsewhere']:
            self.assertFalse((self.f.sda / n / 'called.txt').exists() or (self.f.root / n / 'called.txt').exists())
        # a second valid folder on the other card is ambiguous
        self.f.sdb.mkdir(parents=True)
        self.f.folder(sd=self.f.sdb)
        r = self.f.press('status')
        self.assertEqual(r.returncode, 2)
        self.assertIn('2 F7 FOLDERS', r.stdout)
        # the folder on sdb0 alone is found
        shutil.rmtree(d)
        r = self.f.press('status')
        self.assertEqual(r.returncode, 0)
        self.assertTrue((self.f.sdb / 'mu1320-f7-daily-v2/called.txt').exists())

    def test_missing_wrapper(self):
        d = self.f.folder()
        (d / 'f7.sh').unlink()
        r = self.f.press('status')
        self.assertEqual(r.returncode, 2)
        self.assertIn('FAIL: mu1320-f7-daily-v2/f7.sh missing', r.stdout)

    def test_one_button_at_a_time(self):
        d = self.f.folder()
        lock = self.f.tmp / 'mu1320-f7-menu.lock'
        lock.write_text('%d\n' % os.getpid())  # a live holder
        r = self.f.press('install')
        self.assertEqual(r.returncode, 3)
        self.assertIn('BUSY: another MU1320 button is still running', r.stdout)
        self.assertFalse((d / 'called.txt').exists())
        self.assertEqual(lock.read_text(), '%d\n' % os.getpid(), 'a foreign lock is never removed')
        dead = subprocess.Popen(['true'])
        dead.wait()
        lock.write_text('%d\n' % dead.pid)  # stale
        r = self.f.press('install')
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertFalse(lock.exists())
        # a concurrent press while one runs
        slow = subprocess.Popen([SHELL, str(self.f.eng / 'f7_install.sh')], stdout=subprocess.PIPE, text=True,
                                env={'PATH': '/usr/bin:/bin', 'FAKE_SLEEP': '2'})
        for _ in range(50):
            if lock.exists():
                break
            import time
            time.sleep(0.05)
        r = self.f.press('status')
        self.assertIn('BUSY', r.stdout)
        out, _ = slow.communicate(timeout=30)
        self.assertEqual(slow.returncode, 0, out)
        self.assertFalse(lock.exists())

    def test_the_menu_writes_nothing_on_the_sd(self):
        d = self.f.folder(output=canned('action-status-10838158.txt'))
        before = sorted(str(p.relative_to(self.f.sda)) for p in self.f.sda.rglob('*'))
        self.f.press('status')
        after = sorted(str(p.relative_to(self.f.sda)) for p in self.f.sda.rglob('*'))
        self.assertEqual(sorted(set(after) - set(before)), ['mu1320-f7-daily-v2/called.txt'])
        self.assertTrue(d.exists())


class PackageTests(unittest.TestCase):
    def test_upstream_is_byte_identical_and_overlay_is_small(self):
        report = json.loads((BASE / 'reports/toolbox-v1-prepare.json').read_text())
        upstream = subprocess.check_output(['git', '-C', str(UPSTREAM), 'ls-files', 'Toolbox', 'metainfo2.txt'],
                                           text=True).split()
        for rel in upstream:
            self.assertEqual((STAGE / rel).read_bytes(), (UPSTREAM / rel).read_bytes(), rel)
        files = sorted(str(p.relative_to(STAGE)) for p in STAGE.rglob('*') if p.is_file())
        extra = sorted(set(files) - set(upstream))
        self.assertEqual(extra, sorted(['LICENSE-mib2-toolbox.txt', 'MU1320-README.md', 'MU1320-SHA256SUMS',
                                        'Toolbox/GEM/mqb-mu1320.esd'] +
                                       ['Toolbox/scripts/mu1320/' + n for n in
                                        ['f7menu.sh'] + ['f7_%s.sh' % b for b in BUTTONS]]))
        self.assertEqual(sorted(report['overlay']), sorted(e for e in extra if e.startswith('Toolbox/')))
        v0 = BASE / 'mu1320-toolbox-v0'
        self.assertEqual((STAGE / 'metainfo2.txt').read_bytes(), (v0 / 'metainfo2.txt').read_bytes())
        for p in (v0 / 'Toolbox/final').iterdir():
            self.assertEqual((STAGE / 'Toolbox/final' / p.name).read_bytes(), p.read_bytes())
        self.assertFalse(any(p.name.startswith('._') or p.name == '.DS_Store' for p in STAGE.rglob('*')))

    def test_sums(self):
        rows = [l.split('  ', 1) for l in (STAGE / 'MU1320-SHA256SUMS').read_text().splitlines()]
        names = sorted(str(p.relative_to(STAGE)) for p in STAGE.rglob('*') if p.is_file() and p.name != 'MU1320-SHA256SUMS')
        self.assertEqual(sorted(n for _, n in rows), names)
        for digest, name in rows:
            self.assertEqual(hashlib.sha256((STAGE / name).read_bytes()).hexdigest(), digest, name)

    def test_page_replaces_v0_and_runs_exactly_the_five_stubs(self):
        esd = (STAGE / 'Toolbox/GEM/mqb-mu1320.esd').read_text()
        self.assertIn('screen "MU1320 RGI" Customization', esd)
        scripts = re.findall(r'value\s+sys 1 0x0100 "([^"]+)"', esd)
        self.assertEqual(scripts, ['%s/f7_%s.sh' % (ENGDEFS_DIR, b) for b in
                                   ['status', 'install', 'uninstall', 'collect', 'stop']])
        v0 = (BASE / 'mu1320-toolbox-v0/Toolbox/GEM/mqb-mu1320.esd').exists()
        self.assertTrue(v0, 'same file name as the v0 page, so SWDL replaces it')
        v0_scripts = {p.name for p in (BASE / 'mu1320-toolbox-v0/Toolbox/scripts/mu1320').iterdir()}
        v1_scripts = {p.name for p in (STAGE / 'Toolbox/scripts/mu1320').iterdir()}
        self.assertEqual(v0_scripts & v1_scripts, set())
        for label in re.findall(r'label\s+"([^"]*)"', esd):
            self.assertLessEqual(len(label), 64, label)
            self.assertTrue(all(ord(c) < 128 for c in label), label)

    def test_scripts_parse_and_never_touch_displaymanager(self):
        for p in (STAGE / 'Toolbox/scripts/mu1320').iterdir():
            for shell in ('/bin/sh', '/bin/ksh'):
                if Path(shell).exists():
                    subprocess.run([shell, '-n', str(p)], check=True)
            text = p.read_text()
            self.assertNotIn('dmdt', '\n'.join(l for l in text.splitlines() if not l.lstrip().startswith('#')))
            self.assertNotIn('mount -u', text, 'the dispatcher leaves the SD to f7.sh')
            self.assertEqual(p.stat().st_mode & 0o777, 0o755)

    def test_readme(self):
        readme = (STAGE / 'MU1320-README.md').read_text()
        for word in ['af244e7', 'TOOLBOX-ENTRY', 'mu1320-f7-daily-v2', 'dot_clean', 'BUSY', 'NO F7 FOLDER',
                     '1 Status', '5 EMERGENCY STOP', 'SSH']:
            self.assertIn(word, readme)


if __name__ == '__main__':
    unittest.main()
