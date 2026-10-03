"""Actual loader-check control flow with mocked dynamic-loader APIs on host."""
import os,shutil,subprocess,tempfile,unittest
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
MOCK=r'''
#include <dlfcn.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
static const char *error;
static int match(const char *v) { const char *m=getenv("MODE"); return m && strcmp(m,v)==0; }
static void forbidden(void) { puts("ERROR: hook symbol was invoked"); exit(99); }
void *test_open(const char *name,int flags) {
    if(strcmp(name,"/fixture/hook.so") || flags!=(RTLD_NOW|RTLD_LOCAL)) exit(98);
    if(match("open_fail")) { error="mock open failure";return NULL; }
    return (void *)1;
}
void *test_sym(void *h,const char *name) {
    if(h!=(void *)1 || !name) exit(97);
    if(match("sym_fail")) { error="mock missing symbol";return NULL; }
    return (void *)forbidden;
}
char *test_error(void) { const char *p=error;error=NULL;return (char *)p; }
int test_close(void *h) {
    if(h!=(void *)1) exit(96);
    puts("MOCK_CLOSE_CALLED");
    if(match("close_fail")) { error="mock close failure";return -1; }
    return 0;
}
'''
@unittest.skipUnless(shutil.which('cc'),'host C compiler required')
class Stage1LoaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='mu1320-loader-test-');root=Path(cls.temp.name)
        cls.binary=root/'test';(root/'mock.c').write_text(MOCK)
        subprocess.run(['cc','-std=gnu99','-Wall','-Wextra','-Werror','-D__QNXNTO__','-D__arm__','-Ddlopen=test_open','-Ddlsym=test_sym','-Ddlclose=test_close','-Ddlerror=test_error',str(BASE/'stage1/loader_check.c'),str(root/'mock.c'),'-o',str(cls.binary)],check=True,capture_output=True)
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def run_case(self,mode,path='/fixture/hook.so'):
        return subprocess.run([str(self.binary),path],capture_output=True,text=True,timeout=20,env=dict(os.environ,MODE=mode))
    def test_success_resolves_without_calling_and_closes(self):
        r=self.run_case('pass');self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertEqual(r.stdout.count('(not called)'),5);self.assertIn('MOCK_CLOSE_CALLED',r.stdout)
    def test_failed_loader_calls_and_bad_argument_fail_closed(self):
        for mode,code in [('open_fail',4),('sym_fail',5),('close_fail',6)]:
            with self.subTest(mode=mode):
                r=self.run_case(mode);self.assertEqual(r.returncode,code,r.stdout+r.stderr)
                self.assertNotIn('STAGE1_LOADER_PASSED',r.stdout)
                if mode!='open_fail':self.assertIn('MOCK_CLOSE_CALLED',r.stdout)
        self.assertEqual(self.run_case('pass','relative.so').returncode,2)
if __name__=='__main__':unittest.main()
