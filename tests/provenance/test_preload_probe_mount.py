"""Exercise mount whitelist and ro/rw/error classification using actual C code."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
class PreloadMountTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(); root = Path(cls.temp.name)
        (root / 'sys').mkdir()
        (root / 'sys/statvfs.h').write_text('#define ST_RDONLY 1\nstruct statvfs { char f_basetype[16]; unsigned long f_flag; };\nint statvfs(const char *, struct statvfs *);\n')
        (root / 'mock.c').write_text('''#include <sys/statvfs.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
int statvfs(const char *p, struct statvfs *s) {
 const char *m=getenv("MODE");
 if (!strcmp(m,"error")) {errno=EIO;return -1;}
 strcpy(s->f_basetype,!strcmp(m,"wrong")?"unknown":!strcmp(m,"bare")?"dos":!strcmp(m,"fat16")?"dos (fat16)":(!strncmp(p,"/fs/",4)?"dos (fat32)":"qnx6"));
 s->f_flag=!strcmp(m,"ro")?ST_RDONLY:0;return 0;
}
''')
        cls.binary = root / 'helper'
        subprocess.run(['cc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', '-D__QNXNTO__', '-D__arm__', '-I' + str(root), str(BASE / 'preload-probe/mount_state.c'), str(root / 'mock.c'), '-o', str(cls.binary)], check=True, capture_output=True)
    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()
    def test_whitelist_states(self):
        for path in ['/mnt/app', '/mnt/system', '/fs/sda0', '/fs/sdb0']:
            for mode in ['ro', 'rw']:
                r = subprocess.run([str(self.binary), path], env=dict(os.environ, MODE=mode), capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr); self.assertEqual(r.stdout, mode + '\n')
    def test_unknown_path_fs_and_query_failure_never_infer_state(self):
        for args, mode in [([], 'ro'), (['/fs/sda1'], 'ro'), (['/fs/sda0/subdir'], 'ro'), (['/mnt/app', 'extra'], 'ro'), (['/fs/sda0'], 'wrong'), (['/fs/sda0'], 'bare'), (['/fs/sda0'], 'fat16'), (['/mnt/app'], 'bare'), (['/fs/sdb0'], 'error')]:
            r = subprocess.run([str(self.binary), *args], env=dict(os.environ, MODE=mode), capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0); self.assertEqual(r.stdout, '')
