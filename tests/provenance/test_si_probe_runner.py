"""Exercise the actual runner with fake QNX commands, never native ARM code."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

BASE = Path(__file__).resolve().parents[1]

class RunnerTest(unittest.TestCase):
    def run_case(self, bad_checksum=False, reader_exit=0):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cmds = root/'cmds'; cmds.mkdir()
            package = root/'package'; package.mkdir()
            vehicle = root/'vehicle'; vehicle.mkdir()
            def executable(path, text):
                path.write_text('#!/bin/sh\n'+text+'\n'); path.chmod(0o700)
            executable(cmds/'uname', 'case "$1" in -s) echo QNX ;; -r) echo 6.5.0 ;; esac')
            executable(cmds/'id', "printf ' 0\\n'")
            executable(cmds/'pidin', 'echo IPL_CONFIG_DIR_SMARTPHONE_INTEGRATOR=/etc/eso/production')
            executable(cmds/'cksum', '''case "$1" in
*config_probe) echo '3541562137 8821 file' ;;
*stage3-candidate.json) echo '1647593759 7379 file' ;;
*smartphone_integrator) echo '3518254750 798799 file' ;;
*libutil.so) echo '2157200870 954368 file' ;;
*libosal.so) echo '1582895343 524288 file' ;;
*) echo '535418540 7359 file' ;;
esac'''.replace('2157200870', '0' if bad_checksum else '2157200870'))
            executable(package/'config_probe', f'echo FAKE_READER_CALLED\nexit {reader_exit}')
            (package/'stage3-candidate.json').write_text('{}')
            source = (BASE/'si-probe/run_probe.sh').read_text()
            source = source.replace('PATH=/proc/boot:/bin:/usr/bin:/sbin:/usr/sbin', f'PATH={cmds}:/bin:/usr/bin')
            source = source.replace('work=/tmp/mu1320-si-probe.$$', f'work={root}/trial.$$')
            import re
            targets = set(re.findall(r'/(?:mnt/app|mnt/system|etc/eso|ramdisk/var)/[^\s;]+', source))
            for i,target in enumerate(sorted(targets, key=len, reverse=True)):
                if target.endswith('.pid'):
                    continue
                path = vehicle/f'{i}-{Path(target).name}'
                path.write_text('baseline')
                source = source.replace(target, str(path))
            before = {p.name:p.read_bytes() for p in vehicle.iterdir()}
            (package/'run_probe.sh').write_text(source)
            result = subprocess.run(['/bin/sh',str(package/'run_probe.sh')],capture_output=True,text=True,
                                    env={k:v for k,v in os.environ.items() if not k.startswith('LD_')})
            self.assertEqual(before,{p.name:p.read_bytes() for p in vehicle.iterdir()})
            self.assertFalse(list(root.glob('trial.*')),result.stdout+result.stderr)
            return result

    def test_success_and_whitespace_uid(self):
        r = self.run_case()
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertEqual(r.stdout.count('FAKE_READER_CALLED'),2)
        self.assertIn('candidate_reader_exit=0',r.stdout)
        self.assertIn('SI_CONFIG_PROBE_END',r.stdout)

    def test_baseline_mismatch_stops_before_execution(self):
        r = self.run_case(bad_checksum=True)
        self.assertEqual(r.returncode,2,r.stdout+r.stderr)
        self.assertIn('libutil baseline',r.stdout)
        self.assertNotIn('FAKE_READER_CALLED',r.stdout)

    def test_reader_failure_is_preserved_and_cleanup_runs(self):
        r = self.run_case(reader_exit=4)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertIn('stock_reader_exit=4',r.stdout)
        self.assertIn('candidate_reader_exit=4',r.stdout)
        self.assertIn('SI_CONFIG_PROBE_END',r.stdout)

if __name__ == '__main__':
    unittest.main()
