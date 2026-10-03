"""Host tests for the MU1320 Toolbox v0 package (fake QNX tree, fake mounts and tools).

The package's green-menu scripts are "installed" the way upstream install_scripts.sh does it
(Toolbox/GEM/*.esd -> engdefs, Toolbox/scripts/* -> engdefs/scripts/mqb) into a fake unit
that also carries Lanye's 17 files, then run with absolute paths rewritten into the fixture.
"""
import os
import re
import shutil
import signal
import subprocess
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
STAGE = BASE / 'mu1320-toolbox-v0'
UPSTREAM = BASE.parent / 'mib2-toolbox'
LANYE = BASE.parent / 'MHI2Q-CarPlay-RGI-MMI-Mirror'
# TB_SHELL=/bin/ksh runs the scripts under ksh (the car's /bin/sh is a ksh).
SHELL = os.environ.get('TB_SHELL', '/bin/sh')
SCRIPTS = ['probe_ro.sh', 'probe_write.sh', 'bg_start.sh', 'bg_check.sh', 'lanye_check.sh', 'lanye_remove.sh']
LANYE_FILES = [line.split(' ', 2)[2] for line in
               (STAGE / 'Toolbox/scripts/mu1320/lanye_manifest.txt').read_text().splitlines()]


def cksum_pair(path):
    out = subprocess.check_output(['cksum', str(path)], text=True).split()
    return out[0], out[1]


def snapshot(root, skip=()):
    state = {}
    for p in sorted(root.rglob('*')):
        rel = str(p.relative_to(root))
        if any(rel == s or rel.startswith(s + '/') for s in skip):
            continue
        if p.is_symlink():
            state[rel] = ('link', os.readlink(p))
        elif p.is_dir():
            state[rel] = ('dir',)
        else:
            state[rel] = ('file', p.read_bytes())
    return state


class Fixture:
    def __init__(self, test):
        self.root = Path(tempfile.mkdtemp(prefix='tbv0')).resolve()
        test.addCleanup(self.cleanup)
        v = self.v = self.root / 'unit'
        self.cmds = self.root / 'cmds'
        self.states = self.root / 'states'
        for d in (self.cmds, self.states, v / 'fs/sda0', v / 'tmp', v / 'mnt/app/root/.ssh',
                  v / 'mnt/app/eso/hmi/lsd/jars', v / 'mnt/system/etc/eso/production',
                  v / 'mnt/app/eso/bin/apps', v / 'etc/eso/production'):
            d.mkdir(parents=True, exist_ok=True)
        (v / 'eso').symlink_to(v / 'mnt/app/eso')
        (v / 'mnt/app/root/.profile').write_text('export X=1\n')
        (v / 'mnt/app/eso/hmi/lsd/jars/lsd.jar').write_bytes(b'jar')
        (v / 'mnt/system/etc/eso/production/smartphone_integrator.json').write_text('{}\n')
        self.eng = v / 'mnt/app/eso/hmi/engdefs'
        mqb = self.eng / 'scripts/mqb'
        mqb.mkdir(parents=True)
        # stock page + upstream toolbox + ssh tree, as on the car
        (self.eng / 'stock-debug.esd').write_text('screen stock\n')
        (self.eng / 'scripts/ssh/usr/sbin').mkdir(parents=True)
        (self.eng / 'scripts/ssh/usr/sbin/sshd').write_bytes(b'\x7fELF')
        for gem in (STAGE / 'Toolbox/GEM').glob('*.esd'):
            shutil.copyfile(gem, self.eng / gem.name)
        for item in (STAGE / 'Toolbox/scripts').iterdir():
            if item.is_dir():
                shutil.copytree(item, mqb / item.name, dirs_exist_ok=True)
            else:
                shutil.copyfile(item, mqb / item.name)
        for rel in LANYE_FILES:
            src = LANYE / 'Toolbox' / (('GEM/' + rel) if rel.endswith('.esd') and '/' not in rel
                                       else rel.replace('scripts/mqb/', 'scripts/', 1))
            shutil.copyfile(src, self.eng / rel)
        (mqb / 'sbin/._bc').write_bytes(b'\x00\x05\x16\x07apple')

        # fake mount helper and tools
        self.mu = mqb / 'mu1320'
        self.fake_at(self.mu / 'mount_state', '#!/bin/sh\nk=$(echo "$1" | tr / _)\n'
                     f'if [ -f "{self.states}/$k" ]; then cat "{self.states}/$k"; else echo ro; fi\n')
        self.fake('mount', f'#!/bin/sh\ncase "$1" in\n'
                  f'  -uw) k=$(echo "$2" | tr / _); case " $MOUNT_FAIL " in *" $2 "*) exit 1 ;; esac; echo rw > "{self.states}/$k" ;;\n'
                  f'  -ur) k=$(echo "$2" | tr / _); echo ro > "{self.states}/$k" ;;\n'
                  '  "") echo "fake mount table" ;;\n  *) exit 1 ;;\nesac\n')
        self.fake('id', '#!/bin/sh\necho 0\n')
        self.fake('uname', '#!/bin/sh\ncase "$1" in -n) echo mmx ;; *) echo "QNX mmx 6.5.0 x armle" ;; esac\n')
        self.fake('sloginfo', '#!/bin/sh\necho "Modes changed"\necho line2\n')
        self.fake('pidin', '#!/bin/sh\nif [ "$1" = -p ]; then pid=$2; shift 2\n'
                  '  if [ "$1" = signals ]; then echo "sig ignore=0"; exit 0; fi\n'
                  '  echo "     pid name"\n  c=$(ps -p "$pid" -o comm= 2>/dev/null) && echo "$pid   $c   "\n  exit 0\nfi\n'
                  'echo "pid name"; echo "1 procnto"; echo "2 usr/sbin/smartphone_integrator"; echo "3 dio_manager"\n')
        self.fake('sleep', '#!/bin/sh\ncase "$1" in 10) exec /bin/sleep 0.3 ;; 3) exec /bin/sleep 0.5 ;; '
                  '1) exec /bin/sleep 0.05 ;; *) exec /bin/sleep "$1" ;; esac\n')
        self.fake_at(v / 'mnt/app/eso/bin/apps/dmdt', '#!/bin/sh\necho "dmdt $1"\necho "displaymanager ok"\n')
        self.fake_at(v / 'mnt/app/eso/bin/apps/pc', '#!/bin/sh\necho 2\n')

        for name in ['lib.sh', *SCRIPTS]:
            p = self.mu / name
            p.write_text(self.rewrite(p.read_text()))
        lib = self.mu / 'lib.sh'
        ms = cksum_pair(self.mu / 'mount_state')
        lib.write_text(lib.read_text().replace('mu_check 2952412687 7302', f'mu_check {ms[0]} {ms[1]}'))
        self.state('/fs/sda0', 'ro')

    def cleanup(self):
        pids = self.v / 'tmp/mu1320-probe-bg.pids'
        if pids.exists():
            for line in pids.read_text().split('\n'):
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        os.kill(int(parts[1]), signal.SIGKILL)
                    except (ProcessLookupError, ValueError):
                        pass
        shutil.rmtree(self.root, True)

    def fake(self, name, text):
        self.fake_at(self.cmds / name, text)

    @staticmethod
    def fake_at(path, text):
        path.write_text(text)
        path.chmod(0o755)

    def rewrite(self, text):
        text = re.sub(r'^PATH=.*$', f'PATH={self.cmds}:/usr/bin:/bin', text, flags=re.M)
        return re.sub(r'(?<![\w/.])/(eso|mnt/app|mnt/system|fs/sda0|fs/sdb0|tmp|etc/eso|net|proc/boot)(?=/|\b)',
                      lambda m: f'{self.v}/{m.group(1)}', text)

    def state(self, mount, value):
        (self.states / str(self.v / mount.lstrip('/')).replace('/', '_')).write_text(value + '\n')

    def read_state(self, mount):
        p = self.states / str(self.v / mount.lstrip('/')).replace('/', '_')
        return p.read_text().strip() if p.exists() else 'ro'

    def run(self, name, env=None, ignore_term=False):
        script = str(self.mu / name)
        cmd = [SHELL, '-c', f"trap '' TERM; exec {SHELL} {script}"] if ignore_term else [SHELL, script]
        return subprocess.run(cmd, env=dict(os.environ, **(env or {})), capture_output=True, text=True, timeout=120)

    def run_dir(self, action):
        runs = sorted((self.v / 'fs/sda0/mu1320-toolbox-v0-out').glob(action + '-*'))
        assert len(runs) == 1, runs
        return runs[-1]


class ToolboxV0Tests(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture(self)
        self.unit_skip = ('fs', 'tmp')

    def assert_done(self, res):
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn('RESULT: DONE', res.stdout)
        self.assertIn('SD back to ro', res.stdout)
        self.assertEqual(self.fx.read_state('/fs/sda0'), 'ro')

    def test_probe_ro_is_read_only_and_summarises(self):
        before = snapshot(self.fx.v, ('fs',))
        res = self.fx.run('probe_ro.sh')
        self.assert_done(res)
        self.assertEqual(snapshot(self.fx.v, ('fs',)), before)
        out = res.stdout
        self.assertIn('node=mmx uid=0', out)
        self.assertIn('child SIGTERM: works', out)
        self.assertIn('missing commands: on use', out)
        self.assertIn('absent paths: ' + str(self.fx.v) + '/fs/sdb0', out)
        self.assertIn(f'mounts: {self.fx.v}/mnt/app=ro {self.fx.v}/mnt/system=ro', out)
        self.assertIn('SI=yes dio=yes', out)
        self.assertIn('sloginfo rc=0 lines=2', out)
        self.assertIn('dmdt gs rc=0 lines=2, gd rc=0 lines=2', out)
        self.assertIn('/tmp write: ok', out)
        run = self.fx.run_dir('probe-ro')
        for name in ('summary.txt', 'env.txt', 'proc.txt', 'cmds.txt', 'paths.txt', 'pidin.txt',
                     'sloginfo.txt', 'dmdt-gs.txt', 'dmdt-gd.txt', 'mount.txt'):
            self.assertTrue((run / name).exists(), name)
        self.assertIn('RESULT: DONE', (run / 'summary.txt').read_text())

    def test_probe_ro_reports_ignored_sigterm(self):
        res = self.fx.run('probe_ro.sh', ignore_term=True)
        self.assert_done(res)
        self.assertIn('child SIGTERM: IGNORED', res.stdout)

    def test_probe_write_leaves_unit_unchanged_and_restores_mounts(self):
        before = snapshot(self.fx.v, self.unit_skip)
        res = self.fx.run('probe_write.sh')
        self.assert_done(res)
        self.assertEqual(snapshot(self.fx.v, self.unit_skip), before)
        self.assertEqual(res.stdout.count('write=ok remove=ok'), 3)
        self.assertIn('mkdir/rmdir ' + str(self.fx.v) + '/mnt/app/root: ok', res.stdout)
        self.assertIn(f'RESTORED {self.fx.v}/mnt/system=ro', res.stdout)
        self.assertIn(f'RESTORED {self.fx.v}/mnt/app=ro', res.stdout)
        self.assertEqual(self.fx.read_state('/mnt/app'), 'ro')
        self.assertEqual(self.fx.read_state('/mnt/system'), 'ro')

    def test_probe_write_failed_remount_is_reported_and_other_mount_restored(self):
        (self.fx.v / 'mnt/system/etc/eso/production').chmod(0o555)
        self.addCleanup((self.fx.v / 'mnt/system/etc/eso/production').chmod, 0o755)
        res = self.fx.run('probe_write.sh', env={'MOUNT_FAIL': str(self.fx.v / 'mnt/system')})
        self.assertNotEqual(res.returncode, 0)
        self.assertIn('rw FAILED', res.stdout)
        self.assertIn('/mnt/system/etc/eso/production: write=fail', res.stdout)
        self.assertIn('RESULT: FAILED', res.stdout)
        self.assertEqual(self.fx.read_state('/mnt/app'), 'ro')
        self.assertEqual(self.fx.read_state('/fs/sda0'), 'ro')

    def test_background_start_then_check(self):
        res = self.fx.run('bg_start.sh')
        self.assert_done(res)
        self.assertEqual(len(re.findall(r'tick \d+s', res.stdout)), 6)
        self.assertRegex(res.stdout, r'after 60 s: plain=\S*(sleep|ksh) nohup=\S*sleep')
        rows = [line.split() for line in (self.fx.v / 'tmp/mu1320-probe-bg.pids').read_text().splitlines()]
        self.assertEqual([r[0] for r in rows], ['plain', 'nohup'])
        for row in rows:
            self.assertEqual(len(row), 3, row)
            os.kill(int(row[1]), 0)
        again = self.fx.run('bg_start.sh')
        self.assertIn('run button 4 first', again.stdout)

        res = self.fx.run('bg_check.sh')
        self.assert_done(res)
        self.assertIn('plain pid=', res.stdout)
        self.assertEqual(res.stdout.count('alive=yes stopped=yes'), 2)
        self.assertFalse((self.fx.v / 'tmp/mu1320-probe-bg.pids').exists())
        res = self.fx.run('bg_check.sh')
        self.assertIn('no background test recorded', res.stdout)

    def test_background_check_without_names_stops_nothing(self):
        victim = subprocess.Popen(['/bin/sleep', '30'])
        self.addCleanup(victim.kill)
        (self.fx.v / 'tmp/mu1320-probe-bg.pids').write_text(f'plain {victim.pid}\n')
        res = self.fx.run('bg_check.sh')
        self.assert_done(res)
        self.assertIn(f'plain pid={victim.pid} alive=unknown', res.stdout)
        self.assertIsNone(victim.poll())
        self.assertFalse((self.fx.v / 'tmp/mu1320-probe-bg.pids').exists())

    def test_lanye_check_is_read_only(self):
        before = snapshot(self.fx.v, ('fs',))
        res = self.fx.run('lanye_check.sh')
        self.assert_done(res)
        self.assertEqual(snapshot(self.fx.v, ('fs',)), before)
        self.assertIn('match=17 changed=0 absent=0; ._ files=1', res.stdout)
        self.assertIn('button 6 would remove 18 files', res.stdout)

    def test_lanye_remove_deletes_only_verified_files_with_backup(self):
        changed = self.fx.eng / 'scripts/mqb/install_carplay_rgi.sh'
        changed.write_text(changed.read_text() + '# local edit\n')
        originals = {rel: (self.fx.eng / rel).read_bytes() for rel in LANYE_FILES}
        keep = snapshot(self.fx.v, ('fs', 'eso', 'mnt/app/eso/hmi/engdefs'))
        keep_eng = {k: v for k, v in snapshot(self.fx.eng).items()
                    if k not in LANYE_FILES and k != 'scripts/mqb/sbin/._bc'}

        res = self.fx.run('lanye_remove.sh')
        self.assert_done(res)
        self.assertIn('before: match=16 changed=1 absent=0 ._=1', res.stdout)
        self.assertIn('backed up 17 files to SD', res.stdout)
        self.assertIn('removed=17 left=0; after: match=0 changed=1 ._=0', res.stdout)
        self.assertIn(f'RESTORED {self.fx.v}/mnt/app=ro', res.stdout)
        self.assertEqual(self.fx.read_state('/mnt/app'), 'ro')
        for rel in LANYE_FILES:
            self.assertEqual((self.fx.eng / rel).exists(), rel == 'scripts/mqb/install_carplay_rgi.sh', rel)
        self.assertFalse((self.fx.eng / 'scripts/mqb/sbin/._bc').exists())
        # everything else (upstream toolbox, our page, ssh, root, system) untouched
        self.assertEqual(snapshot(self.fx.v, ('fs', 'eso', 'mnt/app/eso/hmi/engdefs')), keep)
        self.assertEqual({k: v for k, v in snapshot(self.fx.eng).items()
                          if k not in LANYE_FILES}, keep_eng)
        backup = self.fx.run_dir('lanye-remove') / 'backup'
        for rel in LANYE_FILES:
            if rel != 'scripts/mqb/install_carplay_rgi.sh':
                self.assertEqual((backup / rel).read_bytes(), originals[rel], rel)
        self.assertFalse((backup / 'scripts/mqb/install_carplay_rgi.sh').exists())

        res = self.fx.run('lanye_check.sh')
        self.assertIn('match=0 changed=1 absent=16; ._ files=0', res.stdout)
        res = self.fx.run('lanye_remove.sh')
        self.assertIn('nothing to remove', res.stdout)

    def test_tampered_manifest_deletes_nothing(self):
        manifest = self.fx.mu / 'lanye_manifest.txt'
        manifest.write_text(manifest.read_text() + '1 1 mqb-main.esd\n')
        before = snapshot(self.fx.v, ('fs',))
        res = self.fx.run('lanye_remove.sh')
        self.assertNotEqual(res.returncode, 0)
        self.assertIn('FAIL: Lanye manifest checksum', res.stdout)
        self.assertEqual(snapshot(self.fx.v, ('fs',)), before)
        self.assertEqual(self.fx.read_state('/fs/sda0'), 'ro')

    def test_missing_sd_or_bad_helper_fails_cleanly(self):
        shutil.rmtree(self.fx.v / 'fs/sda0')
        res = self.fx.run('probe_ro.sh')
        self.assertEqual(res.returncode, 1)
        self.assertIn('FAIL: no SD card', res.stdout)
        (self.fx.v / 'fs/sda0').mkdir()
        with (self.fx.mu / 'mount_state').open('a') as stream:
            stream.write('# tampered\n')
        res = self.fx.run('probe_ro.sh')
        self.assertEqual(res.returncode, 1)
        self.assertIn('FAIL: mount helper checksum', res.stdout)
        self.assertFalse((self.fx.v / 'fs/sda0/mu1320-toolbox-v0-out').exists())


class ToolboxV0StaticTests(unittest.TestCase):
    def test_package_is_reproducible_and_upstream_metadata_unchanged(self):
        files = sorted(str(p.relative_to(STAGE)) for p in STAGE.rglob('*') if p.is_file())
        res = subprocess.run(['shasum', '-a', '256', '-c', 'MU1320-SHA256SUMS'], cwd=STAGE, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stdout[-2000:])
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'stage'
            subprocess.check_call(['python3', str(BASE / 'scripts/prepare_toolbox_v0.py'), '--output', str(out),
                                   '--report', str(Path(tmp) / 'r.json')], stdout=subprocess.DEVNULL)
            rebuilt = sorted(str(p.relative_to(out)) for p in out.rglob('*') if p.is_file())
            self.assertEqual(rebuilt, files)
            for name in files:
                self.assertEqual((out / name).read_bytes(), (STAGE / name).read_bytes(), name)
        self.assertEqual((STAGE / 'metainfo2.txt').read_bytes(), (UPSTREAM / 'metainfo2.txt').read_bytes())
        for f in (UPSTREAM / 'Toolbox/final').iterdir():
            self.assertEqual((STAGE / 'Toolbox/final' / f.name).read_bytes(), f.read_bytes(), f.name)
        self.assertFalse([p for p in STAGE.rglob('*') if p.name.startswith('._') or p.name == '.DS_Store'])

    def test_page_buttons_point_at_shipped_scripts(self):
        esd = (STAGE / 'Toolbox/GEM/mqb-mu1320.esd').read_text()
        self.assertIn('screen "MU1320 RGI" Customization', esd)
        targets = re.findall(r'value\s+sys 1 0x0100 "([^"]+)"', esd)
        self.assertEqual([t.rsplit('/', 1)[1] for t in targets], SCRIPTS)
        for t in targets:
            self.assertTrue(t.startswith('/eso/hmi/engdefs/scripts/mqb/mu1320/'), t)
            self.assertTrue((STAGE / 'Toolbox/scripts/mu1320' / t.rsplit('/', 1)[1]).exists(), t)

    def test_vehicle_scripts_avoid_known_qnx_traps(self):
        for name in ['lib.sh', *SCRIPTS]:
            text = (STAGE / 'Toolbox/scripts/mu1320' / name).read_text()
            self.assertNotIn('\r', text, name)
            if name != 'lib.sh':
                self.assertTrue(text.startswith('#!/bin/sh\n'), name)
                self.assertIn('. /eso/hmi/engdefs/scripts/mqb/mu1320/lib.sh\n', text, name)
                self.assertIn("trap mu_end 0;", text, name)
            for number, line in enumerate(text.splitlines(), 1):
                code = '' if line.lstrip().startswith('#') else line
                if code.lstrip().startswith('for u in '):
                    continue
                if '&&' in code and '||' not in code and not re.match(r'\s*(if|elif|while)\b', code):
                    self.fail(f'{name}:{number}: bare && : {line}')
                self.assertNotIn('IFS= read', code, f'{name}:{number}')
                self.assertNotIn("grep -c ''", code, f'{name}:{number}')
                self.assertNotRegex(code, r'dmdt\S*"? +ts\b|\bdmdt ts\b', f'{name}:{number}')
                self.assertNotRegex(code, r'\b(awk|sed|slay|shutdown|reboot|cp|mv)\b', f'{name}:{number}')
                for target in re.findall(r'\brm -f (\S+)', code):
                    self.assertRegex(target, r'^"\$\{[A-Za-z_]+:\?\}', f'{name}:{number}: unguarded rm')
                self.assertNotRegex(code, r'\brm -r', f'{name}:{number}')


if __name__ == '__main__':
    unittest.main()
