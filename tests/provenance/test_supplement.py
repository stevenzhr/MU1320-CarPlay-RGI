import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE/'scripts'))
from audit_supplement import parse_displays


class SupplementTests(unittest.TestCase):
    def test_actual_display_sizes(self):
        d = parse_displays((BASE.parent/'resource/private/vehicle-dump/dmdt_gd.txt').read_text())
        self.assertEqual((d['101']['width'], d['101']['height']), (210, 153))
        self.assertEqual(d['101'], d['102'])
        self.assertNotIn('98', d)  # Stock snapshot: expected before launching custom renderer.

    def run_checker(self, mode):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)
            template = (BASE/'scripts/preflight.sh.in').read_text()
            source = template.replace('@CHECKSUM_ROWS@', '123 10 /example/fixture')
            # Only the test copy uses mocks; production has a fixed system PATH.
            source = source.replace('PATH=/proc/boot:', 'PATH='+str(folder)+':/proc/boot:')
            utilities = {
                'uname': "echo 'QNX mmx 6.5.0 build APQ8064 armle'",
                'cksum': 'case "$MOCK_MODE" in unreadable) exit 1;; mismatch) echo "456 10 $1";; *) echo "123 10 $1";; esac',
                'cmp': '[ "$MOCK_MODE" != different_config ]',
                'pidin': "echo '100 /ifs/jre/bin/j9 -DmyAudi.VIN=PRIVATE_SENTINEL'; echo '200 /mnt/app/eso/bin/apps/dio_manager'",
            }
            for name, body in utilities.items():
                f = folder/name
                f.write_text('#!/bin/sh\n'+body+'\n')
                f.chmod(0o755)
            env = dict(os.environ, MOCK_MODE=mode)
            return subprocess.run(['/bin/sh'], input=source, text=True, capture_output=True, env=env)

    def test_pass_is_explicitly_not_install_approval_and_no_private_arguments(self):
        r = self.run_checker('ok')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('NOT permission or proof for installation', r.stdout)
        self.assertNotIn('PRIVATE_SENTINEL', r.stdout)
        self.assertIn('100 /ifs/jre/bin/j9', r.stdout)

    def test_changed_or_missing_input_fails(self):
        for mode in ['mismatch', 'unreadable', 'different_config']:
            r = self.run_checker(mode)
            self.assertEqual(r.returncode, 1, (mode, r.stdout, r.stderr))
            self.assertIn('BASELINE_CHECK_FAILED', r.stdout)


if __name__ == '__main__': unittest.main()
