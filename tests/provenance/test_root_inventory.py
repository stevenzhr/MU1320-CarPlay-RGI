"""Host tests for the read-only /mnt/app/root inventory SD folder (fake QNX tree and tools)."""
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
STAGE = BASE / 'mu1320-root-inventory-v1'


def cksum_pair(path):
    out = subprocess.check_output(['cksum', str(path)], text=True).split()
    return out[0], out[1]


def snapshot(root):
    """Every path under root with its bytes / link target, to prove nothing changed."""
    state = {}
    for p in sorted(root.rglob('*')):
        rel = str(p.relative_to(root))
        if p.is_symlink():
            state[rel] = ('link', os.readlink(p))
        elif p.is_dir():
            state[rel] = ('dir', oct(p.stat().st_mode))
        else:
            state[rel] = ('file', p.read_bytes(), oct(p.stat().st_mode), p.stat().st_mtime_ns)
    return state


class Fixture:
    def __init__(self, test):
        self.root = Path(tempfile.mkdtemp(prefix='rinv')).resolve()
        test.addCleanup(shutil.rmtree, self.root, True)
        self.sd_root = self.root / 'fs/sda0'
        self.sd = self.sd_root / STAGE.name
        self.vehicle = self.root / 'vehicle'
        self.cmds = self.root / 'cmds'
        self.cmds.mkdir()
        shutil.copytree(STAGE, self.sd, ignore=shutil.ignore_patterns('out'))
        self.sdflag = self.root / 'sd.flag'
        self.sdflag.write_text('ro\n')

        v = self.vehicle
        files = {
            'mnt/app/root/lib-target/libfoo.so': b'stock lib\n',
            'mnt/app/root/.profile': b'export X=1\n',
            'mnt/app/root/mu1320-rgi-f3-v2/libcarplay_hook.so': b'hook\n' * 100,
            'mnt/app/root/mu1320-rgi-f3-v2/config/dio_manager.json': b'{}\n',
            'mnt/app/root/mu1320-rgi-f3-v2/quarantine/NavActiveIgnore.jar': b'NAI\n',
            'mnt/app/root/mu1320-env-probe-v2/backup/smartphone_integrator.json': b'{"si":1}\n',
            'mnt/app/root/mu1320-rgi-stage1-v2/backup/.hidden': b'h\n',
            'mnt/app/eso/hmi/lsd/jars/NavActiveIgnore.jar': b'NAI\n',
            'mnt/app/eso/hmi/lsd/jars/diag.jar': b'diag\n',
            'mnt/app/eso/hmi/lsd/jars/CarPlayRGI-MU1320-Stage2.jar.DISABLED': b'old\n',
            'mnt/system/etc/eso/production/smartphone_integrator.json': b'{"si":1}\n',
            'mnt/system/etc/eso/production/dio_manager.json': b'{"dio":1}\n',
            'mnt/system/etc/eso/production/.mu1320-f3-run.123': b'tmp\n',
            'mnt/system/etc/eso/production/other.json': b'{}\n',
            'etc/eso/production/smartphone_integrator.json': b'{"si":1}\n',
            'etc/eso/production/dio_manager.json': b'{"dio":1}\n',
        }
        for rel, data in files.items():
            path = v / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (v / 'mnt/app/root/bin-link').symlink_to('/etc')
        (v / 'mnt/app/root/mu1320-rgi-f1-v1').mkdir()
        (v / 'mnt/app/root/mu1320-rgi-f1-v1/escape').symlink_to(v / 'mnt/app/eso/hmi/lsd/jars')

        mount_state = self.sd / 'mount_state'
        mount_state.write_text('#!/bin/sh\ncat "$SD_FLAG"\n')
        mount_state.chmod(0o755)
        self.fake('id', '#!/bin/sh\necho 0\n')
        self.fake('uname', '#!/bin/sh\necho "QNX mmx 6.5.0 2018/02/05-11:11:12CET APQ8064_65536_MMX2_Rev:1 armle"\n')
        self.fake('pidin', '#!/bin/sh\necho "  1 procnto"\necho "  7 /bin/sh /fs/sda0/mu1320-root-inventory-v1/control.sh run"\n')
        self.fake('df', '#!/bin/sh\necho fake df\n')
        self.fake('mount', '#!/bin/sh\ncase "$1" in -uw) echo rw > "$SD_FLAG" ;; -ur) echo ro > "$SD_FLAG" ;; '
                           '"") echo "fake mount table" ;; *) exit 1 ;; esac\n')

        control = self.sd / 'control.sh'
        control.write_text(self.rewrite(control.read_text()))
        wrapper = self.sd / 'root_inventory.sh'
        text = self.rewrite(wrapper.read_text())
        text = text.replace('/fs/sda0/*) sd=/fs/sda0', f'{self.sd_root}/*) sd={self.sd_root}')
        ms = cksum_pair(mount_state)
        text = text.replace("'2952412687'", f"'{ms[0]}'").replace("'7302'", f"'{ms[1]}'")
        old = re.search(r"= '(\d+)' \] && \[ \"\$\{2:-\}\" = '(\d+)' \] \|\| fail 'control", text)
        new = cksum_pair(control)
        text = text.replace(f"'{old.group(1)}' ] && [ \"${{2:-}}\" = '{old.group(2)}'",
                            f"'{new[0]}' ] && [ \"${{2:-}}\" = '{new[1]}'")
        wrapper.write_text(text)
        self.wrapper = wrapper

    def fake(self, name, text):
        path = self.cmds / name
        path.write_text(text)
        path.chmod(0o755)

    def rewrite(self, text):
        text = re.sub(r'^PATH=.*$', f'PATH={self.cmds}:/usr/bin:/bin', text, flags=re.M)
        return re.sub(r'(?<![\w/])/(mnt/app|mnt/system|etc/eso|proc/boot)',
                      lambda m: str(self.vehicle) + '/' + m.group(1), text)

    def run(self, *args):
        env = dict(os.environ, SD_FLAG=str(self.sdflag))
        return subprocess.run(['/bin/sh', str(self.wrapper), *args], env=env,
                              capture_output=True, text=True, timeout=120)

    def inv_dir(self):
        runs = sorted((self.sd / 'out').glob('inv-*'))
        assert len(runs) == 1, runs
        return runs[0]


class RootInventoryTests(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture(self)

    def test_run_is_read_only_and_copies_only_trial_files(self):
        before = snapshot(self.fx.vehicle)
        res = self.fx.run('run')
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(snapshot(self.fx.vehicle), before)
        self.assertIn('ROOT_INVENTORY_COMPLETE', res.stdout)
        self.assertIn('ROOT_INVENTORY_PASSED', res.stdout)
        self.assertEqual(self.fx.sdflag.read_text().strip(), 'ro')
        self.assertIn('TOP_COUNT=7 TRIAL_COUNT=4', res.stdout)
        self.assertIn('TOP OTHER link bin-link', res.stdout)

        inv = self.fx.inv_dir()
        v = str(self.fx.vehicle)
        copied = sorted(('/' + str(p.relative_to(inv / 'copy')))[len(v):] for p in (inv / 'copy').rglob('*')
                        if p.is_file())
        self.assertEqual(copied, [
            '/mnt/app/eso/hmi/lsd/jars/CarPlayRGI-MU1320-Stage2.jar.DISABLED',
            '/mnt/app/eso/hmi/lsd/jars/NavActiveIgnore.jar',
            '/mnt/app/root/mu1320-env-probe-v2/backup/smartphone_integrator.json',
            '/mnt/app/root/mu1320-rgi-f3-v2/config/dio_manager.json',
            '/mnt/app/root/mu1320-rgi-f3-v2/libcarplay_hook.so',
            '/mnt/app/root/mu1320-rgi-f3-v2/quarantine/NavActiveIgnore.jar',
            '/mnt/app/root/mu1320-rgi-stage1-v2/backup/.hidden',
            '/mnt/system/etc/eso/production/.mu1320-f3-run.123',
            '/mnt/system/etc/eso/production/dio_manager.json',
            '/mnt/system/etc/eso/production/smartphone_integrator.json',
        ])
        self.assertIn('COPIED=10 COPY_ERRORS=0 COPY_SKIPPED=0', res.stdout)

        manifest = (inv / 'manifest.txt').read_text()
        # stock content is listed with checksums but never copied; symlinks are not followed
        self.assertIn(f'{v}/mnt/app/root/lib-target/libfoo.so', manifest)
        self.assertIn(f'{v}/mnt/app/root/.profile', manifest)
        self.assertIn(f'LINK {v}/mnt/app/root/mu1320-rgi-f1-v1/escape', manifest)
        self.assertNotIn(f'{v}/mnt/app/root/mu1320-rgi-f1-v1/escape/diag.jar', manifest)
        self.assertRegex(manifest, r'FILE \d+ 500 ' + re.escape(v) + '/mnt/app/root/mu1320-rgi-f3-v2/libcarplay_hook.so')
        self.assertIn('no mu1320', res.stdout)
        self.assertTrue((inv / 'pidin_ar.txt').exists())

    def test_sd_left_writable_if_it_started_writable(self):
        self.fx.sdflag.write_text('rw\n')
        res = self.fx.run('run')
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(self.fx.sdflag.read_text().strip(), 'rw')

    def test_live_config_reference_is_reported(self):
        si = self.fx.vehicle / 'mnt/system/etc/eso/production/smartphone_integrator.json'
        si.write_text('"LD_PRELOAD=/mnt/app/root/mu1320-rgi-f3-v2/libcarplay_hook.so"\n')
        res = self.fx.run('run')
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn('1:"LD_PRELOAD=', res.stdout)

    def test_usage_and_tampered_worker_are_rejected(self):
        self.assertEqual(self.fx.run().returncode, 2)
        self.assertEqual(self.fx.run('delete').returncode, 2)
        with (self.fx.sd / 'control.sh').open('a') as stream:
            stream.write('# tampered\n')
        res = self.fx.run('run')
        self.assertNotEqual(res.returncode, 0)
        self.assertIn('STOP: control checksum', res.stdout + res.stderr)
        self.assertFalse((self.fx.sd / 'out').exists())


class RootInventoryStaticTests(unittest.TestCase):
    def test_staged_folder_matches_manifest_and_prepare(self):
        files = sorted(p.name for p in STAGE.iterdir() if p.is_file())
        self.assertEqual(files, ['README.md', 'SHA256SUMS', 'control.sh', 'mount_state', 'mount_state.c',
                                 'root_inventory.sh'])
        res = subprocess.run(['shasum', '-a', '256', '-c', 'SHA256SUMS'], cwd=STAGE, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stdout)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'stage'
            subprocess.check_call(['python3', str(BASE / 'scripts/prepare_root_inventory.py'), '--output', str(out),
                                   '--report', str(Path(tmp) / 'r.json')], stdout=subprocess.DEVNULL)
            for name in files:
                self.assertEqual((out / name).read_bytes(), (STAGE / name).read_bytes(), name)
        self.assertEqual((STAGE / 'mount_state').read_bytes(), (BASE / 'mu1320-f3-bap-v2/mount_state').read_bytes())

    def test_vehicle_scripts_avoid_known_qnx_traps_and_vehicle_writes(self):
        for name in ('control.sh', 'root_inventory.sh'):
            text = (STAGE / name).read_text()
            for number, line in enumerate(text.splitlines(), 1):
                code = line.split('#', 1)[0] if not line.lstrip().startswith('#') else ''
                if '&&' in code and '||' not in code and not re.match(r'\s*(if|while|elif)\b', code) \
                        and 'cd "$stage_dir" && pwd' not in code:
                    self.fail(f'{name}:{number}: bare && : {line}')
                self.assertNotIn('IFS= read', code, f'{name}:{number}')
                self.assertNotRegex(code, r'\b(awk|sed|tee|rm|mv|cp|chmod|chown|kill|slay|shutdown|dmdt)\b',
                                    f'{name}:{number}')
                self.assertNotRegex(code, r'mount -u[wr] /mnt', f'{name}:{number}')
        control = (STAGE / 'control.sh').read_text()
        code = [l for l in control.splitlines() if not l.lstrip().startswith('#')]
        # the only redirections that create files point into $run (SD) or the candidate list
        for line in code:
            for target in re.findall(r'>>?\s*("?[^\s;)]+)', line):
                if target in ('/dev/null', '&1'):
                    continue
                self.assertRegex(target, r'^"\$(run|man|cands|dst)', line)


if __name__ == '__main__':
    unittest.main()
