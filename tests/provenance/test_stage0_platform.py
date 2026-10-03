"""Run the actual probe C code with mocked platform queries on the host.

On a 64-bit host, exit 4 is expected after the platform gate: it proves the
APQ board name was accepted without weakening the independent 32-bit ABI gate.
These tests do not claim to execute the QNX ELF or emulate its libraries.
"""
import os
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
MOCK = r'''
#include <sys/utsname.h>
#include <unistd.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>

static int scenario(const char *name) {
    const char *value = getenv("STAGE0_TEST_CASE");
    return value != NULL && strcmp(value, name) == 0;
}
int stage0_mock_uname(struct utsname *p) {
    memset(p, 0, sizeof(*p));
    if (scenario("uname_error")) { errno = EIO; return -1; }
    strcpy(p->sysname, scenario("wrong_os") ? "Linux" : "QNX");
    strcpy(p->release, scenario("wrong_release") ? "7.0.0" : "6.5.0");
    strcpy(p->machine, "APQ8064_65536_MMX2_Rev:1");
    strcpy(p->nodename, "PRIVATE_NODE_MUST_NOT_APPEAR");
    return 0;
}
size_t stage0_mock_confstr(int name, char *buffer, size_t length) {
    const char *value = scenario("wrong_arch") ? "x86" : "armle";
    size_t needed = strlen(value) + 1;
    if (name != 6 || scenario("arch_error")) { errno = EINVAL; return 0; }
    if (scenario("truncated_arch")) {
        memset(buffer, 'x', length);
        return length + 20;
    }
    if (length >= needed) memcpy(buffer, value, needed);
    return needed;
}
'''


@unittest.skipUnless(shutil.which('cc'), 'host C compiler is required')
class Stage0PlatformTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='mu1320-platform-regression-')
        root = Path(cls.temp.name)
        cls.binary = root / 'platform-check'
        mock = root / 'mock.c'
        mock.write_text(MOCK)
        result = subprocess.run([
            'cc', '-std=gnu99', '-Wall', '-Wextra', '-Werror',
            '-D__QNXNTO__=1', '-D__arm__=1', '-D_CS_ARCHITECTURE=6',
            '-Duname=stage0_mock_uname', '-Dconfstr=stage0_mock_confstr',
            str(BASE / 'stage0/native_smoke.c'), str(mock), '-o', str(cls.binary)
        ], capture_output=True, text=True)
        if result.returncode:
            cls.temp.cleanup()
            raise RuntimeError(result.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_case(self, scenario):
        return subprocess.run([str(self.binary)], capture_output=True, text=True, timeout=15,
                              env=dict(os.environ, STAGE0_TEST_CASE=scenario))

    def test_apq_hardware_name_and_armle_architecture_pass_platform_gate(self):
        result = self.run_case('valid')
        expected_exit = 4 if struct.calcsize('P') != 4 else 0
        self.assertEqual(result.returncode, expected_exit, result.stdout + result.stderr)
        self.assertIn('PASS: QNX OS and instruction-set architecture', result.stdout)
        self.assertIn('machine=APQ8064_65536_MMX2_Rev:1', result.stdout)
        self.assertIn('architecture=armle', result.stdout)
        self.assertNotIn('PRIVATE_NODE_MUST_NOT_APPEAR', result.stdout)

    def test_invalid_or_incomplete_platform_still_rejected(self):
        for scenario in ('uname_error', 'wrong_os', 'wrong_release', 'wrong_arch', 'arch_error', 'truncated_arch'):
            with self.subTest(scenario=scenario):
                result = self.run_case(scenario)
                self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
                self.assertNotIn('PASS: QNX OS and instruction-set architecture', result.stdout)
                self.assertNotIn('PRIVATE_NODE_MUST_NOT_APPEAR', result.stdout)


if __name__ == '__main__':
    unittest.main()
