"""Host tests for the read-only Toolbox inventory SD folder (fake QNX tree and tools)."""
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
STAGE = BASE / 'mu1320-toolbox-inventory-v1'
# TB_SHELL=/bin/ksh runs the scripts under ksh (the car's /bin/sh is a ksh).
SHELL = os.environ.get('TB_SHELL', '/bin/sh')


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
        self.root = Path(tempfile.mkdtemp(prefix='tbinv')).resolve()
        test.addCleanup(shutil.rmtree, self.root, True)
        self.sd_root = self.root / 'fs/sda0'
        self.sd = self.sd_root / STAGE.name
        self.vehicle = self.root / 'vehicle'
        self.cmds = self.root / 'cmds'
        self.cmds.mkdir()
        shutil.copytree(STAGE, self.sd, ignore=shutil.ignore_patterns('out'))
        (self.sd_root / 'Toolbox/GEM').mkdir(parents=True)
        self.sdflag = self.root / 'sd.flag'
        self.sdflag.write_text('ro\n')

        e = 'mnt/app/eso/hmi/engdefs/'
        files = {
            e + 'mqb-main.esd': b'# Version:      4.2A\nscreen main\n',
            e + 'mqb-various.esd': b'screen various\n',
            e + 'stock-debug.esd': b'screen stock\n',
            e + 'scripts/mqb/util_mountsd.sh': b'#!/bin/ksh\n',
            e + 'scripts/mqb/sbin/bc': b'\x7fELF' + b'x' * 64,
            e + 'scripts/ssh/usr/sbin/sshd': b'\x7fELFsshd',
            e + 'scripts/ssh/etc/ssh_host_rsa_key': b'PRIVATE KEY\n',
            'mnt/app/root/.profile': b'export PATH=/x\n',
            'mnt/app/root/scp': b'#!/bin/sh\n',
            'mnt/app/root/.ssh/authorized_keys': b'ssh-rsa AAAA\n',
            'mnt/app/root/lib-target/libfoo.so': b'stock lib\n',
            'mnt/system/etc/inetd.conf': b'telnet stream tcp\n'
                                         b'ssh stream tcp nowait root /net/mmx/mnt/app/eso/hmi/engdefs/scripts/ssh/usr/sbin/start_sshd in.sshd\n',
            'mnt/system/etc/inetd.conf.bu': b'telnet stream tcp\n',
            'mnt/system/etc/pf.mlan0.conf': b'pass in quick on $wlan_if proto tcp from any to ($wlan_if) port 22 keep state\n',
            'mnt/system/etc/pf.mlan0.conf.bu': b'block all\n',
            'mnt/system/etc/pf.conf': b'block all\n',
            'mnt/system/etc/hosts': b'127.0.0.1 localhost\n',
            'net/rcc/mnt/efs-persist/SWDL/FileCopyInfo/Toolbox.info': b'Version=4.11\n',
            'net/rcc/dev/shmem/version.txt': b'Current train = "MHI2Q_ER_AUG22_K1316"\n',
        }
        for rel, data in files.items():
            path = self.vehicle / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (self.vehicle / (e + 'scripts/mqb/link-out')).symlink_to('/etc')

        mount_state = self.sd / 'mount_state'
        mount_state.write_text('#!/bin/sh\ncat "$SD_FLAG"\n')
        mount_state.chmod(0o755)
        self.fake('id', '#!/bin/sh\necho 0\n')
        self.fake('uname', '#!/bin/sh\necho "QNX mmx 6.5.0 2018/02/05-11:11:12CET APQ8064_65536_MMX2_Rev:1 armle"\n')
        self.fake('pidin', '#!/bin/sh\necho "  1 procnto"\necho "  9 inetd"\n'
                           'echo "  7 /bin/sh /fs/sda0/mu1320-toolbox-inventory-v1/control.sh run"\n')
        self.fake('df', '#!/bin/sh\necho fake df\n')
        self.fake('mount', '#!/bin/sh\ncase "$1" in -uw) echo rw > "$SD_FLAG" ;; -ur) echo ro > "$SD_FLAG" ;; '
                           '"") echo "fake mount table" ;; *) exit 1 ;; esac\n')

        control = self.sd / 'control.sh'
        text = self.rewrite(control.read_text())
        text = text.replace('for sd in /fs/sda0 /fs/sdb0', f'for sd in {self.sd_root} {self.root}/fs/sdb0')
        control.write_text(text)
        wrapper = self.sd / 'toolbox_inventory.sh'
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
        return re.sub(r'(?<![\w/])/(mnt/app|mnt/system|net/rcc|proc/boot)',
                      lambda m: str(self.vehicle) + '/' + m.group(1), text)

    def run(self, *args):
        env = dict(os.environ, SD_FLAG=str(self.sdflag))
        return subprocess.run([SHELL, str(self.wrapper), *args], env=env,
                              capture_output=True, text=True, timeout=120)

    def inv_dir(self):
        runs = sorted((self.sd / 'out').glob('tbinv-*'))
        assert len(runs) == 1, runs
        return runs[0]


class ToolboxInventoryTests(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture(self)

    def test_run_is_read_only_and_never_copies_ssh_keys(self):
        before = snapshot(self.fx.vehicle)
        res = self.fx.run('run')
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(snapshot(self.fx.vehicle), before)
        out = res.stdout
        self.assertIn('TOOLBOX_INVENTORY_COMPLETE', out)
        self.assertIn('TOOLBOX_INVENTORY_PASSED', out)
        self.assertEqual(self.fx.sdflag.read_text().strip(), 'ro')

        self.assertIn('ESD_TOTAL=3 ESD_MQB=2', out)
        self.assertIn('PAGE mqb-main.esd', out)
        self.assertIn('1:# Version:      4.2A', out)
        v = str(self.fx.vehicle)
        self.assertIn(f'DIR_PRESENT {v}/mnt/app/eso/hmi/engdefs/scripts/ssh', out)
        self.assertIn('2:ssh stream tcp nowait root', out)
        self.assertIn('1:pass in quick on $wlan_if', out)
        self.assertIn('no port 22 rule', out)
        self.assertIn(f'PRESENT {v}/mnt/app/root/.ssh/authorized_keys', out)
        self.assertIn('no sshd process', out)
        self.assertIn('9 inetd', out)
        self.assertIn('INFO Toolbox.info', out)
        self.assertIn('Current train = "MHI2Q_ER_AUG22_K1316"', out)
        self.assertIn(f'-- {self.fx.sd_root}', out)
        self.assertIn('SD_ABSENT', out)

        inv = self.fx.inv_dir()
        copied = sorted(('/' + str(p.relative_to(inv / 'copy')))[len(v):] for p in (inv / 'copy').rglob('*')
                        if p.is_file())
        self.assertEqual(copied, [
            '/mnt/app/eso/hmi/engdefs/mqb-main.esd',
            '/mnt/app/eso/hmi/engdefs/mqb-various.esd',
            '/mnt/app/eso/hmi/engdefs/scripts/mqb/sbin/bc',
            '/mnt/app/eso/hmi/engdefs/scripts/mqb/util_mountsd.sh',
            '/mnt/app/eso/hmi/engdefs/stock-debug.esd',
            '/mnt/app/root/.profile',
            '/mnt/app/root/scp',
            '/mnt/system/etc/inetd.conf',
            '/mnt/system/etc/inetd.conf.bu',
            '/mnt/system/etc/pf.conf',
            '/mnt/system/etc/pf.mlan0.conf',
            '/mnt/system/etc/pf.mlan0.conf.bu',
            '/net/rcc/dev/shmem/version.txt',
            '/net/rcc/mnt/efs-persist/SWDL/FileCopyInfo/Toolbox.info',
        ])
        self.assertIn('COPIED=14 COPY_ERRORS=0 COPY_SKIPPED=0', out)

        manifest = (inv / 'manifest.txt').read_text()
        # the sshd tree and ~/.ssh are listed with checksums but never copied; links are not followed
        self.assertRegex(manifest, r'FILE \d+ 12 ' + re.escape(v) + '/mnt/app/eso/hmi/engdefs/scripts/ssh/etc/ssh_host_rsa_key')
        self.assertIn(f'{v}/mnt/app/root/.ssh/authorized_keys', manifest)
        self.assertIn(f'LINK {v}/mnt/app/eso/hmi/engdefs/scripts/mqb/link-out', manifest)
        self.assertNotIn(f'{v}/mnt/app/root/lib-target/libfoo.so', manifest)
        self.assertTrue((inv / 'pidin_ar.txt').exists())

    def test_missing_toolbox_is_reported_not_fatal(self):
        shutil.rmtree(self.fx.vehicle / 'mnt/app/eso/hmi/engdefs')
        shutil.rmtree(self.fx.vehicle / 'net/rcc/mnt/efs-persist/SWDL/FileCopyInfo')
        res = self.fx.run('run')
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn('ESD_TOTAL=0 ESD_MQB=0', res.stdout)
        self.assertIn('DIR_ABSENT', res.stdout)
        self.assertIn('FCI_ABSENT', res.stdout)
        self.assertIn('MISSING', (self.fx.inv_dir() / 'manifest.txt').read_text())

    def test_sd_left_writable_if_it_started_writable(self):
        self.fx.sdflag.write_text('rw\n')
        res = self.fx.run('run')
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(self.fx.sdflag.read_text().strip(), 'rw')

    def test_usage_and_tampered_worker_are_rejected(self):
        self.assertEqual(self.fx.run().returncode, 2)
        self.assertEqual(self.fx.run('install').returncode, 2)
        with (self.fx.sd / 'control.sh').open('a') as stream:
            stream.write('# tampered\n')
        res = self.fx.run('run')
        self.assertNotEqual(res.returncode, 0)
        self.assertIn('STOP: control checksum', res.stdout + res.stderr)
        self.assertFalse((self.fx.sd / 'out').exists())


class ToolboxInventoryStaticTests(unittest.TestCase):
    def test_staged_folder_matches_manifest_and_prepare(self):
        files = sorted(p.name for p in STAGE.iterdir() if p.is_file())
        self.assertEqual(files, ['README.md', 'SHA256SUMS', 'control.sh', 'mount_state', 'mount_state.c',
                                 'toolbox_inventory.sh'])
        res = subprocess.run(['shasum', '-a', '256', '-c', 'SHA256SUMS'], cwd=STAGE, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stdout)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'stage'
            subprocess.check_call(['python3', str(BASE / 'scripts/prepare_toolbox_inventory.py'), '--output', str(out),
                                   '--report', str(Path(tmp) / 'r.json')], stdout=subprocess.DEVNULL)
            for name in files:
                self.assertEqual((out / name).read_bytes(), (STAGE / name).read_bytes(), name)
        self.assertEqual((STAGE / 'mount_state').read_bytes(), (BASE / 'mu1320-f3-bap-v2/mount_state').read_bytes())

    def test_vehicle_scripts_avoid_known_qnx_traps_and_vehicle_writes(self):
        for name in ('control.sh', 'toolbox_inventory.sh'):
            text = (STAGE / name).read_text()
            for number, line in enumerate(text.splitlines(), 1):
                code = line.split('#', 1)[0] if not line.lstrip().startswith('#') else ''
                if '&&' in code and '||' not in code and not re.match(r'\s*(if|while|elif)\b', code) \
                        and 'cd "$stage_dir" && pwd' not in code:
                    self.fail(f'{name}:{number}: bare && : {line}')
                self.assertNotIn('IFS= read', code, f'{name}:{number}')
                self.assertNotIn("grep -c ''", code, f'{name}:{number}')
                self.assertNotRegex(code, r'\b(awk|sed|tee|tar|head|rm|mv|cp|chmod|chown|kill|slay|shutdown|dmdt)\b',
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
