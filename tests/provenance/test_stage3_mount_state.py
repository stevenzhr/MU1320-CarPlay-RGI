"""Actual helper control flow with mocked statvfs; target ABI audited separately."""
import os,shutil,subprocess,tempfile,unittest
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
@unittest.skipUnless(shutil.which('cc'),'host C compiler required')
class Stage3MountTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();root=Path(cls.tmp.name);(root/'sys').mkdir()
        (root/'sys/statvfs.h').write_text('#define ST_RDONLY 1\nstruct statvfs { char f_basetype[16]; unsigned long f_flag; };\nint statvfs(const char *, struct statvfs *);\n')
        (root/'mock.c').write_text('''#include <sys/statvfs.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
int statvfs(const char *p,struct statvfs *s) {
 const char *m=getenv("MODE");
 if ((strcmp(p,"/mnt/app") && strcmp(p,"/mnt/system")) || !strcmp(m,"error")) {errno=EIO;return -1;}
 strcpy(s->f_basetype,!strcmp(m,"wrong")?"dos":"qnx6");
 s->f_flag=!strcmp(m,"ro")?ST_RDONLY:0;return 0;
}
''')
        cls.bin=root/'helper'
        subprocess.run(['cc','-std=gnu99','-Wall','-Wextra','-Werror','-D__QNXNTO__','-D__arm__','-I'+str(root),str(BASE/'stage3/mount_state.c'),str(root/'mock.c'),'-o',str(cls.bin)],check=True,capture_output=True)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def test_both_mounts_ro_rw(self):
        for path in ['/mnt/app','/mnt/system']:
            for mode in ['ro','rw']:
                r=subprocess.run([str(self.bin),path],env=dict(os.environ,MODE=mode),capture_output=True,text=True)
                self.assertEqual(r.returncode,0);self.assertEqual(r.stdout,mode+'\n')
    def test_bad_arguments_and_failed_queries_have_no_state(self):
        for args,mode in [([], 'ro'),(['/etc'],'ro'),(['/mnt/app','extra'],'ro'),(['/mnt/system'],'wrong'),(['/mnt/app'],'error')]:
            r=subprocess.run([str(self.bin),*args],env=dict(os.environ,MODE=mode),capture_output=True,text=True)
            self.assertNotEqual(r.returncode,0);self.assertEqual(r.stdout,'')
