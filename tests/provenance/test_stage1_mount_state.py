"""Mock only statvfs to test the actual C query's output/error decisions on host.
The mock struct is not a test of the QNX ABI; target ELF is separately audited.
"""
import os,shutil,subprocess,tempfile,unittest
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
@unittest.skipUnless(shutil.which('cc'),'host compiler required')
class MountStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();root=Path(cls.temp.name)
        (root/'sys').mkdir()
        (root/'sys/statvfs.h').write_text('#define ST_RDONLY 1\nstruct statvfs { char f_basetype[16]; unsigned long f_flag; };\nint statvfs(const char *, struct statvfs *);\n')
        (root/'mock.c').write_text('''#include <sys/statvfs.h>
#include <string.h>
#include <stdlib.h>
#include <errno.h>
int statvfs(const char *p, struct statvfs *s) {
 const char *m=getenv("MODE");
 if(strcmp(p,"/mnt/app") || !strcmp(m,"error")) {errno=EIO;return -1;}
 strcpy(s->f_basetype,!strcmp(m,"wrong_fs")?"dos":"qnx6");
 s->f_flag=!strcmp(m,"ro")?ST_RDONLY:0;
 return 0;
}
''')
        cls.binary=root/'test'
        subprocess.run(['cc','-std=gnu99','-Wall','-Wextra','-Werror','-D__QNXNTO__','-D__arm__','-I'+str(root),str(BASE/'stage1/mount_state.c'),str(root/'mock.c'),'-o',str(cls.binary)],check=True,capture_output=True)
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def test_readonly_and_writable(self):
        for mode in ['ro','rw']:
            r=subprocess.run([str(self.binary)],env=dict(os.environ,MODE=mode),capture_output=True,text=True)
            self.assertEqual(r.returncode,0);self.assertEqual(r.stdout,mode+'\n')
    def test_error_or_wrong_filesystem_has_no_usable_output(self):
        for mode in ['error','wrong_fs']:
            r=subprocess.run([str(self.binary)],env=dict(os.environ,MODE=mode),capture_output=True,text=True)
            self.assertNotEqual(r.returncode,0);self.assertEqual(r.stdout,'')
if __name__=='__main__':unittest.main()
