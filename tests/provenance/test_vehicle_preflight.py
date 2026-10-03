import sys
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / 'scripts'))
from audit_vehicle_preflight import parse_preflight, parse_recovery


class VehiclePreflightTest(unittest.TestCase):
    def setUp(self):
        self.script = "done <<'BASELINE_CKSUMS'\n1 2 /test/original\nBASELINE_CKSUMS\n"
        self.log = '\n'.join([
            'PASS: QNX 6.5 ARM platform string', 'PASS: /test/original',
            'PASS: config contents identical: dio_manager.json (does not prove path aliases)',
            'PASS: config contents identical: smartphone_integrator.json (does not prove path aliases)',
            'BASELINE_CHECK_PASSED: checks only', 'preflight_exit=0root@mmx:/fs/sda0>'])

    def test_pass_does_not_grant_installation_or_alias(self):
        result = parse_preflight(self.log, self.script)
        self.assertEqual(result['status'], 'PASS')
        self.assertFalse(result['installation_readiness_proven'])
        self.assertFalse(result['path_alias_proven'])

    def test_reject_missing_conflicting_and_failed_checks(self):
        for log in (self.log.replace('PASS: /test/original', ''),
                    self.log + '\nFAIL: unreadable /test/original',
                    self.log.replace('preflight_exit=0', 'preflight_exit=1'),
                    self.log.replace('preflight_exit=0', 'missing_exit=0'),
                    self.log + '\npreflight_exit=0'):
            with self.subTest(log=log):
                self.assertEqual(parse_preflight(log, self.script)['status'], 'FAIL_OR_INCOMPLETE')

    def test_missing_mount_not_inferred_from_config_text(self):
        recovery = parse_recovery('root@mmx:/fs/sda0> cat /etc/inetd.conf\n# mount\n')
        self.assertFalse(recovery['mount_output_present'])
        self.assertFalse(recovery['hmi_failure_recovery_verified'])
        self.assertTrue(parse_recovery('root@mmx:/fs/sda0> mount\n/dev/hd0 on /mnt/app\n')['mount_output_present'])


if __name__ == '__main__':
    unittest.main()
