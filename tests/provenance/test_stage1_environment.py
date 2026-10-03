"""Verify the user-tested run_clean function with absent/empty/inherited settings."""
import subprocess,tempfile,unittest
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
class CleanEnvironmentTests(unittest.TestCase):
    def exercise(self,mode,code=0):
        s=(BASE/'stage1/run_stage1.sh').read_text()
        start=s.index('run_clean() {');end=s.index('\nif [ "$action" = prepare ]; then',start)
        function=s[start:end]
        with tempfile.TemporaryDirectory(prefix='mu1320-clean-env-') as td:
            root=Path(td);helper=root/'helper';harness=root/'test.sh'
            helper.write_text('''#!/bin/sh
[ "${LD_PRELOAD+x}${LD_DEBUG+x}${DL_DEBUG+x}${LD_DEBUG_OUTPUT+x}" = "" ] || exit 88
[ "$LD_LIBRARY_PATH" = /proc/boot:/lib ] || exit 89
[ "$1" = 'argument with spaces' ] || exit 90
exit "$2"
''');helper.chmod(0o755)
            setup='unset LD_PRELOAD LD_DEBUG DL_DEBUG LD_DEBUG_OUTPUT || :\n'
            if mode!='absent':
                value='' if mode=='empty' else 'parent-sentinel'
                setup+=f"LD_PRELOAD='{value}'; LD_DEBUG='{value}'; DL_DEBUG='{value}'; LD_DEBUG_OUTPUT='{value}'\nexport LD_PRELOAD LD_DEBUG DL_DEBUG LD_DEBUG_OUTPUT\n"
            if mode=='unset_nonzero':
                setup+='unset() { command unset "$@"; return 1; }\n'
            harness.write_text('set -eu\n'+setup+"LD_LIBRARY_PATH=parent-lib; export LD_LIBRARY_PATH\n"+function+'''\nresult=0
run_clean "$1" 'argument with spaces' "$2" || result=$?
[ "$LD_LIBRARY_PATH" = parent-lib ] || exit 91
'''+("[ \"${LD_DEBUG_OUTPUT+x}\" = \"\" ] || exit 92\n" if mode=='absent' else "[ \"${LD_DEBUG_OUTPUT+x}\" = x ] || exit 92\n")+'''printf 'child_status=%s\n' "$result"
exit "$result"
''')
            return subprocess.run(['/bin/sh',str(harness),str(helper),str(code)],capture_output=True,text=True)
    def test_child_variables_absent_and_parent_unchanged(self):
        for mode in ['absent','empty','inherited','unset_nonzero']:
            with self.subTest(mode=mode):
                r=self.exercise(mode);self.assertEqual(r.returncode,0,r.stdout+r.stderr)
    def test_helper_failure_propagates(self):
        r=self.exercise('inherited',17);self.assertEqual(r.returncode,17,r.stdout+r.stderr)
        self.assertIn('child_status=17',r.stdout)
if __name__=='__main__':unittest.main()
