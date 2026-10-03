"""Host tests for the /mnt/app/root cleanup SD folder.

The fake vehicle tree is rebuilt from the root inventory's byte copies, so every checksum the
cleanup verifies is the one recorded on the car.
"""
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
STAGE = BASE / 'mu1320-root-cleanup-v1'
INV = BASE.parent / 'resource/private/vehicle-dump/root-inventory-v1/inv-3317899'
WHITELIST = ['mu1320-env-probe-v2', 'mu1320-preload-probe-v1', 'mu1320-rgi-stage1-v2', 'mu1320-rgi-stage2-v2',
             'mu1320-rgi-stage3-v1', 'mu1320-rgi-navhook-v1', 'mu1320-rgi-navjava-v1', 'mu1320-rgi-f1-v1',
             'mu1320-rgi-f1-v2', 'mu1320-rgi-f2-v1', 'mu1320-rgi-f3-v1', 'mu1320-rgi-f3-v2']
# RC_SHELL=/bin/ksh runs the scripts under ksh (the car's /bin/sh is a ksh).
SHELL = os.environ.get('RC_SHELL', '/bin/sh')
KEEP = ['.profile', '.ssh', 'bin-target', 'hooks', 'scp', 'scpr']


def cksum_pair(path):
    out = subprocess.check_output(['cksum', str(path)], text=True).split()
    return out[0], out[1]


def snapshot(root):
    state = {}
    for p in sorted(root.rglob('*')):
        rel = str(p.relative_to(root))
        if p.is_symlink():
            state[rel] = ('link', os.readlink(p))
        elif p.is_dir():
            state[rel] = ('dir',)
        else:
            state[rel] = ('file', p.read_bytes())
    return state


class Base(unittest.TestCase):
    def setUp(self):
        if not (INV / 'manifest.txt').exists():
            self.skipTest('vehicle inventory not present')
        self.tmp = Path(tempfile.mkdtemp(prefix='rcln')).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.sd_root = self.tmp / 'fs/sda0'
        self.sd = self.sd_root / STAGE.name
        self.v = self.tmp / 'vehicle'
        self.cmds = self.tmp / 'cmds'
        self.cmds.mkdir()
        shutil.copytree(STAGE, self.sd, ignore=shutil.ignore_patterns('out'))
        shutil.copytree(INV / 'copy/mnt', self.v / 'mnt')
        prod = self.v / 'mnt/system/etc/eso/production'
        (self.v / 'etc/eso').mkdir(parents=True)
        shutil.copytree(prod, self.v / 'etc/eso/production')
        for d in ('mu1320-rgi-f1-v1/quarantine', 'mu1320-rgi-f1-v2/quarantine', 'mu1320-rgi-f3-v1/quarantine',
                  'mu1320-rgi-f3-v2/quarantine'):
            (self.root / d).mkdir(exist_ok=True)
        (self.root / 'bin-target').mkdir()
        (self.root / 'bin-target/io-pkt-v4').write_bytes(b'stock\n')
        (self.root / 'hooks').mkdir()
        (self.root / '.ssh').mkdir()
        (self.root / '.ssh/authorized_keys').write_text('ssh-rsa AAA\n')
        for name in ('.profile', 'scp', 'scpr'):
            (self.root / name).write_text(name + '\n')

        self.sdflag = self.tmp / 'sd.flag'
        self.sdflag.write_text('ro\n')
        self.appflag = self.tmp / 'app.flag'
        self.appflag.write_text('ro\n')
        mount_state = self.sd / 'mount_state'
        mount_state.write_text(f'#!/bin/sh\ncase "$1" in {self.sd_root}) cat "$SD_FLAG" ;; *) cat "$APP_FLAG" ;; esac\n')
        mount_state.chmod(0o755)
        self.fake('id', '#!/bin/sh\necho 0\n')
        self.fake('uname', '#!/bin/sh\necho "QNX mmx 6.5.0 2016/06/01-12:10:31EDT APQ8064_65536_MMX2_Rev:1 armle"\n')
        self.fake('pidin', '#!/bin/sh\necho "  1 procnto"\necho "${PIDIN_EXTRA:-}"\n')
        self.fake('mount', '#!/bin/sh\ncase "$1:$2" in '
                           f'-uw:{self.sd_root}) echo rw > "$SD_FLAG" ;; -ur:{self.sd_root}) echo ro > "$SD_FLAG" ;; '
                           f'-uw:{self.v}/mnt/app) echo rw > "$APP_FLAG" ;; -ur:{self.v}/mnt/app) echo ro > "$APP_FLAG" ;; '
                           '*) echo "bad mount $*" >&2; exit 1 ;; esac\necho "$*" >> "$MOUNT_LOG"\n')
        self.fake('rm', '#!/bin/sh\nfor a; do case "$a" in *"${RM_FAIL:-@none@}") exit 1 ;; esac; done\n'
                        'case "$APP_FLAG_CHECK" in 1) [ "$(cat "$APP_FLAG")" = rw ] || { echo "rm on ro app" >&2; exit 1; } ;; esac\n'
                        'exec /bin/rm "$@"\n')
        self.mount_log = self.tmp / 'mount.log'
        self.mount_log.touch()

        control = self.sd / 'control.sh'
        text = self.rewrite(control.read_text())
        ms = cksum_pair(mount_state)
        text = text.replace('check 2952412687 7302 "$stage_dir/mount_state"', f'check {ms[0]} {ms[1]} "$stage_dir/mount_state"')
        control.write_text(text)
        wrapper = self.sd / 'root_cleanup.sh'
        text = self.rewrite(wrapper.read_text())
        text = text.replace('/fs/sda0/*) sd=/fs/sda0', f'{self.sd_root}/*) sd={self.sd_root}')
        text = text.replace("'2952412687'", f"'{ms[0]}'").replace("'7302'", f"'{ms[1]}'")
        old = re.search(r"= '(\d+)' \] && \[ \"\$\{2:-\}\" = '(\d+)' \] \|\| fail 'control", text)
        new = cksum_pair(control)
        text = text.replace(f"'{old.group(1)}' ] && [ \"${{2:-}}\" = '{old.group(2)}'",
                            f"'{new[0]}' ] && [ \"${{2:-}}\" = '{new[1]}'")
        wrapper.write_text(text)
        self.wrapper = wrapper

    @property
    def root(self):
        return self.v / 'mnt/app/root'

    def fake(self, name, text):
        path = self.cmds / name
        path.write_text(text)
        path.chmod(0o755)

    def rewrite(self, text):
        text = re.sub(r'^PATH=.*$', f'PATH={self.cmds}:/usr/bin:/bin', text, flags=re.M)
        text = text.replace('/bin/sh "$stage_dir/control.sh"', SHELL + ' "$stage_dir/control.sh"')
        return re.sub(r'(?<![\w/])/(mnt/app|mnt/system|etc/eso|proc/boot)',
                      lambda m: str(self.v) + '/' + m.group(1), text)

    def run_sd(self, *args, **extra):
        env = dict(os.environ, SD_FLAG=str(self.sdflag), APP_FLAG=str(self.appflag), MOUNT_LOG=str(self.mount_log),
                   APP_FLAG_CHECK='1')
        env.update(extra)
        res = subprocess.run([SHELL, str(self.wrapper), *args], env=env, capture_output=True, text=True,
                             timeout=300)
        res.all = res.stdout + res.stderr
        return res

    def others(self):
        """Snapshot of the vehicle outside the whitelisted directories."""
        snap = snapshot(self.v)
        return {k: val for k, val in snap.items()
                if not any(k == f'mnt/app/root/{w}' or k.startswith(f'mnt/app/root/{w}/') for w in WHITELIST)}

    def assertMountsRestored(self):
        self.assertEqual(self.appflag.read_text().strip(), 'ro')
        self.assertEqual(self.sdflag.read_text().strip(), 'ro')


class CleanupTests(Base):
    def test_status_is_read_only(self):
        before = snapshot(self.v)
        res = self.run_sd('status')
        self.assertEqual(res.returncode, 0, res.all)
        self.assertIn('VERIFIED: 115 of 115 inventoried entries present, 0 unexpected', res.all)
        self.assertIn('CLEANUP_STATE: NOT_STARTED', res.all)
        self.assertIn('ROOT_CLEANUP_status_PASSED', res.all)
        for name in KEEP:
            self.assertIn(f'KEEP {name}', res.all)
        self.assertEqual(snapshot(self.v), before)
        self.assertNotIn('/mnt/app', self.mount_log.read_text().replace(str(self.v), ''))
        self.assertMountsRestored()

    def test_delete_removes_exactly_the_whitelist(self):
        others = self.others()
        res = self.run_sd('delete')
        self.assertEqual(res.returncode, 0, res.all)
        self.assertIn('REMOVED: 115', res.all)
        self.assertIn('ROOT_CLEANUP_COMPLETE', res.all)
        self.assertIn('APP_MOUNT_RESTORED: /mnt/app=ro'.replace('/mnt/app', f'{self.v}/mnt/app'), res.all)
        self.assertIn('ROOT_CLEANUP_delete_PASSED', res.all)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), KEEP)
        self.assertEqual(self.others(), others)
        self.assertMountsRestored()
        again = self.run_sd('status')
        self.assertEqual(again.returncode, 0, again.all)
        self.assertIn('CLEANUP_STATE: DONE', again.all)
        for name in WHITELIST:
            self.assertIn(f'TRIAL_ABSENT {name}', again.all)

    def test_delete_leaves_an_unlisted_trial_dir_alone(self):
        f5 = self.root / 'mu1320-rgi-f5-v1'
        f5.mkdir()
        (f5 / 'libcarplay_hook.so').write_bytes(b'f5\n')
        res = self.run_sd('delete')
        self.assertEqual(res.returncode, 0, res.all)
        self.assertIn('KEEP mu1320-rgi-f5-v1', res.all)
        self.assertEqual((f5 / 'libcarplay_hook.so').read_bytes(), b'f5\n')

    def assertRefused(self, res, message):
        self.assertNotEqual(res.returncode, 0, res.all)
        self.assertIn(message, res.all)
        self.assertNotIn('ROOT_CLEANUP_COMPLETE', res.all)
        self.assertMountsRestored()

    def test_extra_file_stops_before_any_removal(self):
        (self.root / 'mu1320-rgi-f3-v2/backup/new.txt').write_text('x\n')
        before = snapshot(self.v)
        res = self.run_sd('delete')
        self.assertRefused(res, 'UNEXPECTED F ')
        self.assertIn('nothing deleted', res.all)
        self.assertEqual(snapshot(self.v), before)

    def test_changed_file_stops_before_any_removal(self):
        (self.root / 'mu1320-rgi-stage1-v2/backup/system-si.json').write_text('{}\n')
        before = snapshot(self.v)
        self.assertRefused(self.run_sd('delete'), 'nothing deleted')
        self.assertEqual(snapshot(self.v), before)

    def test_symlink_inside_whitelist_is_never_followed(self):
        (self.root / 'mu1320-rgi-f2-v1/escape').symlink_to(self.root / 'bin-target')
        before = snapshot(self.v)
        res = self.run_sd('delete')
        self.assertRefused(res, 'UNEXPECTED L ')
        self.assertEqual(snapshot(self.v), before)

    def test_installed_trial_config_blocks_delete(self):
        si = self.v / 'mnt/system/etc/eso/production/smartphone_integrator.json'
        si.write_text(si.read_text() + ' ')
        before = snapshot(self.v)
        self.assertRefused(self.run_sd('delete'), 'not the inventoried baseline')
        self.assertEqual(snapshot(self.v), before)

    def test_changed_navactiveignore_blocks_delete(self):
        (self.v / 'mnt/app/eso/hmi/lsd/jars/NavActiveIgnore.jar').unlink()
        self.assertRefused(self.run_sd('delete'), 'NavActiveIgnore.jar is not the inventoried baseline')

    def test_process_reference_blocks_delete(self):
        before = snapshot(self.v)
        res = self.run_sd('delete', PIDIN_EXTRA=f'  99 dio_manager LD_PRELOAD={self.root}/mu1320-rgi-f3-v2/libcarplay_hook.so')
        self.assertRefused(res, 'a running process references')
        self.assertEqual(snapshot(self.v), before)

    def test_interrupted_delete_restores_mount_and_resumes(self):
        res = self.run_sd('delete', RM_FAIL='mu1320-rgi-f2-v1/libcarplay_hook.so')
        self.assertRefused(res, 'rm failed')
        self.assertIn('DELETE_INCOMPLETE', res.all)
        status = self.run_sd('status')
        self.assertEqual(status.returncode, 0, status.all)
        self.assertIn('CLEANUP_STATE: PARTIAL', status.all)
        res = self.run_sd('delete')
        self.assertEqual(res.returncode, 0, res.all)
        self.assertIn('ROOT_CLEANUP_COMPLETE', res.all)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), KEEP)

    def test_app_left_rw_if_it_started_rw(self):
        self.appflag.write_text('rw\n')
        res = self.run_sd('delete')
        self.assertEqual(res.returncode, 0, res.all)
        self.assertEqual(self.appflag.read_text().strip(), 'rw')
        self.assertNotIn(f'-uw {self.v}/mnt/app', self.mount_log.read_text())
        self.assertNotIn(f'-ur {self.v}/mnt/app', self.mount_log.read_text())

    def test_usage_and_tampering(self):
        self.assertEqual(self.run_sd().returncode, 2)
        self.assertEqual(self.run_sd('run').returncode, 2)
        with (self.sd / 'control.sh').open('a') as stream:
            stream.write('# tampered\n')
        res = self.run_sd('delete')
        self.assertNotEqual(res.returncode, 0)
        self.assertIn('STOP: control checksum', res.all)
        self.assertEqual(len(list(self.root.iterdir())), len(WHITELIST) + len(KEEP))


class CleanupStaticTests(unittest.TestCase):
    def test_staged_folder_matches_manifest_and_prepare(self):
        if not (INV / 'manifest.txt').exists():
            self.skipTest('vehicle inventory not present')
        names = sorted(p.name for p in STAGE.iterdir() if p.is_file())
        self.assertEqual(names, ['README.md', 'SHA256SUMS', 'control.sh', 'mount_state', 'mount_state.c',
                                 'root_cleanup.sh'])
        res = subprocess.run(['shasum', '-a', '256', '-c', 'SHA256SUMS'], cwd=STAGE, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stdout)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'stage'
            subprocess.check_call(['python3', str(BASE / 'scripts/prepare_root_cleanup.py'), '--output', str(out),
                                   '--report', str(Path(tmp) / 'r.json')], stdout=subprocess.DEVNULL)
            for name in names:
                self.assertEqual((out / name).read_bytes(), (STAGE / name).read_bytes(), name)

    def test_delete_primitives_are_narrow(self):
        control = (STAGE / 'control.sh').read_text()
        code = [l.split('#', 1)[0] for l in control.splitlines() if not l.lstrip().startswith('#')]
        joined = '\n'.join(code)
        self.assertNotRegex(joined, r'\brm\s+-[a-zA-Z]*[rR]')
        self.assertEqual(re.findall(r'\brm -f [^\n]*', joined), ['rm -f "$3" < /dev/null || fail "rm failed: $3"'])
        self.assertEqual(len(re.findall(r'\brmdir "', joined)), 1)
        self.assertNotRegex(joined, r'mount -u[wr] /mnt/system')
        self.assertNotRegex(joined, r'\b(mv|cp|chmod|chown|kill|slay|shutdown|awk|sed|tee)\b')
        steps = [l for l in code if l.startswith('del_') and "'" in l]
        self.assertEqual(len(steps), 115)
        for step in steps:
            path = step.rsplit("'", 2)[1]
            self.assertRegex(path, r'^/mnt/app/root/(' + '|'.join(map(re.escape, WHITELIST)) + r')(/|$)')
            self.assertNotIn('*', path)
            self.assertNotIn('..', path)
        # directories after all files, deepest first
        kinds = [s.split()[0] for s in steps]
        self.assertEqual(kinds, ['del_file'] * 77 + ['del_dir'] * 38)
        depths = [s.count('/') for s in steps if s.startswith('del_dir')]
        self.assertEqual(depths, sorted(depths, reverse=True))
        for name in ('control.sh', 'root_cleanup.sh'):
            for number, line in enumerate((STAGE / name).read_text().splitlines(), 1):
                c = line.split('#', 1)[0] if not line.lstrip().startswith('#') else ''
                if '&&' in c and '||' not in c and not re.match(r'\s*(if|while|elif|for)\b', c) \
                        and 'cd "$stage_dir" && pwd' not in c:
                    self.fail(f'{name}:{number}: bare &&: {line}')
                self.assertNotIn('IFS= read', c)
                self.assertNotIn("grep -c ''", c)


if __name__ == '__main__':
    unittest.main()
