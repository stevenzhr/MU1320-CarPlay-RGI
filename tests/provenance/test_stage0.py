import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]


class Stage0WrapperTest(unittest.TestCase):
    def exercise(self, mode):
        script = (BASE / 'stage0/run_stage0.sh').read_text()
        checks = re.findall(r'^check_file (\d+) (\d+) (.+) \|\| exit 1$', script, re.M)
        self.assertEqual(len(checks), 3)
        with tempfile.TemporaryDirectory(prefix='mu1320-stage0-wrapper-') as td:
            root = Path(td)
            commands = root / 'commands'
            commands.mkdir()
            # Only the test copy's PATH changes. No real QNX binary is executed on the host.
            script = re.sub(r'^PATH=.*$', 'PATH=' + str(commands) + ':/usr/bin:/bin', script, count=1, flags=re.M)
            (root / 'run_stage0.sh').write_text(script)
            cases = []
            for crc, size, path in checks:
                match = '*/native_smoke' if path.startswith('"') else path
                key = 'binary' if path.startswith('"') else ('libc' if 'libc.' in path else 'socket')
                cases.append(f'{match}) [ "$MODE" != "bad_{key}" ] || exit 1; echo "{crc} {size} $1" ;;')
            bodies = {
                'uname': '#!/bin/sh\n[ "$MODE" != bad_platform ] || { echo Darwin; exit 0; }\necho "QNX mmx 6.5.0 test armle"\n',
                'cksum': '#!/bin/sh\ncase "$1" in\n' + '\n'.join(cases) + '\n*) exit 1 ;;\nesac\n',
                'mount': '#!/bin/sh\necho "TEST_MOUNT_OUTPUT"\n',
            }
            for name, text in bodies.items():
                p = commands / name
                p.write_text(text)
                p.chmod(0o755)
            helper = root / 'native_smoke'
            helper.write_text('#!/bin/sh\necho "$LD_LIBRARY_PATH|${LD_PRELOAD:-}" > "$MARKER"\n'
                              '[ "$MODE" != child_failure ] || exit 7\n'
                              'echo "TEST_NATIVE_PASSED"\n')
            helper.chmod(0o755)
            marker = root / 'called'
            env = dict(os.environ, MODE=mode, MARKER=str(marker))
            run = subprocess.run(['/bin/sh', str(root / 'run_stage0.sh')],
                                 env=env, capture_output=True, text=True)
            return run, marker.read_text() if marker.exists() else None

    def test_pass_records_mount_and_confines_library_environment(self):
        run, called = self.exercise('pass')
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn('TEST_MOUNT_OUTPUT', run.stdout)
        self.assertIn('STAGE0_NATIVE_CHECK_PASSED:', run.stdout)
        self.assertEqual(called, '/proc/boot:/lib|\n')

    def test_bad_inputs_never_execute_helper(self):
        for mode in ('bad_binary', 'bad_libc', 'bad_socket', 'bad_platform'):
            with self.subTest(mode=mode):
                run, called = self.exercise(mode)
                self.assertNotEqual(run.returncode, 0)
                self.assertIsNone(called)
                self.assertNotIn('STAGE0_NATIVE_CHECK_PASSED:', run.stdout)

    def test_native_failure_propagates(self):
        run, called = self.exercise('child_failure')
        self.assertEqual(run.returncode, 7)
        self.assertIsNotNone(called)
        self.assertIn('native_smoke_exit=7', run.stdout)
        self.assertNotIn('STAGE0_NATIVE_CHECK_PASSED:', run.stdout)


if __name__ == '__main__':
    unittest.main()
