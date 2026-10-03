"""Host control-flow tests for the constructor-free, process one-shot gate."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]

@unittest.skipUnless(shutil.which('cc'), 'host C compiler required')
class NavhookGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(); root = Path(cls.temp.name)
        cls.token = root / 'arm'; cls.prefix = str(root / 'receipt-')
        cls.harness = root / 'gate_test'
        harness_c = root / 'harness.c'
        harness_c.write_text('''#include <stdio.h>
#include <unistd.h>
#include <sys/wait.h>
#include "trial_gate.h"
int main(int argc, char **argv) {
 int active, status; pid_t child;
 (void)argc; (void)argv;
 active=trial_gate_active();
 printf("ACTIVE=%d AGAIN=%d PID=%d\\n", active, trial_gate_active(), (int)getpid());
 fflush(stdout);
 if (active) {
  child=fork(); if (child<0) return 3;
  if (child==0) _exit(trial_gate_active()?9:0);
  if (waitpid(child,&status,0)!=child || !WIFEXITED(status) || WEXITSTATUS(status)!=0) return 4;
 }
 return 0;
}
''')
        command = ['cc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', '-pthread',
                   '-DTRIAL_ASSUME_DIO=1', '-DTRIAL_REQUIRED_UID=' + str(os.getuid()),
                   '-DTRIAL_TOKEN_PATH=' + json.dumps(str(cls.token)),
                   '-DTRIAL_RECEIPT_PREFIX=' + json.dumps(cls.prefix),
                   '-I' + str(BASE / 'navhook-src'), str(harness_c),
                   str(BASE / 'navhook-src/trial_gate.c'), '-o', str(cls.harness)]
        subprocess.run(command, check=True, capture_output=True)
    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()
    def setUp(self):
        for p in Path(self.prefix).parent.glob('receipt-*'): p.unlink()
        if self.token.exists() or self.token.is_symlink(): self.token.unlink()
    def run_gate(self):
        result = subprocess.run([str(self.harness)], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        pid = result.stdout.split('PID=')[1].split()[0]
        receipt = Path(self.prefix + pid)
        self.assertTrue(receipt.is_file())
        return result.stdout, receipt.read_text()
    def token_file(self, content='MU1320-NAVHOOK-ONE-SHOT-V1\n', mode=0o600):
        self.token.write_text(content); self.token.chmod(mode)
    def test_exact_token_activates_once_consumes_and_fork_is_passive(self):
        self.token_file(); output, receipt = self.run_gate()
        self.assertIn('ACTIVE=1 AGAIN=1', output)
        self.assertIn('mode=ACTIVE_TOKEN_CONSUMED', receipt)
        self.assertFalse(self.token.exists())
    def test_absent_token_is_sticky_passive(self):
        output, receipt = self.run_gate()
        self.assertIn('ACTIVE=0 AGAIN=0', output); self.assertIn('mode=PASSIVE', receipt)
    def test_wrong_content_or_mode_is_preserved(self):
        for content, mode in [('wrong\n', 0o600), ('MU1320-NAVHOOK-ONE-SHOT-V1\n', 0o644)]:
            with self.subTest(content=content, mode=mode):
                self.token_file(content, mode); output, receipt = self.run_gate()
                self.assertIn('ACTIVE=0', output); self.assertIn('mode=PASSIVE', receipt)
                self.assertTrue(self.token.exists()); self.token.unlink()
    def test_symlink_token_is_preserved(self):
        target = self.token.parent / 'target'; target.write_text('MU1320-NAVHOOK-ONE-SHOT-V1\n'); target.chmod(0o600)
        self.token.symlink_to(target)
        output, _ = self.run_gate(); self.assertIn('ACTIVE=0', output)
        self.assertTrue(self.token.is_symlink()); self.token.unlink(); target.unlink()

if __name__ == '__main__': unittest.main()
