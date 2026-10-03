"""Exercise actual shell logic on host-isolated paths; not a QNX runtime test."""
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
RESOURCE=BASE.parent/'resource'

class Stage1Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='mu1320-stage1-test-')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.commands=self.root/'commands';self.commands.mkdir()
        self.parent=self.root/'vehicle-root';self.parent.mkdir()
        self.work=self.parent/'mu1320-rgi-stage1-v2'
        self.stage=self.root/'sd';self.stage.mkdir()
        self.counter=self.root/'loader-called'
        def command(name,body):
            p=self.commands/name;p.write_text('#!/bin/sh\n'+body);p.chmod(0o755)
        command('uname','echo "QNX mmx 6.5.0 fixture armle"\n')
        command('id','[ "${FAIL_MODE:-}" != id_fail ] || exit 1\nprintf "%s\\n" "${ID_OUTPUT- 0}"\n')
        self.mountflag=self.root/'mount-state';self.mountflag.write_text('ro\n')
        self.mountcalls=self.root/'mount-calls'
        command('mount', 'echo "$*" >> "$MOUNT_CALLS"\ncase "$1" in\n-uw) [ "${FAIL_MODE:-}" != rw_fail ] || exit 1; echo rw > "$MOUNT_FLAG" ;;\n-ur) [ "${FAIL_MODE:-}" != ro_fail ] || exit 1; echo ro > "$MOUNT_FLAG" ;;\n*) exit 2 ;;\nesac\n')
        state=self.stage/'mount_state'
        state.write_text('#!/bin/sh\n[ "${FAIL_MODE:-}" != state_fail ] || exit 3\ncat "$MOUNT_FLAG"\n');state.chmod(0o755)
        # No host-global flush, and intercept commands only in isolated test script copy.
        command('sync',':\n')
        command('cp','[ "${FAIL_MODE:-}" != term_signal ] || { kill -TERM "$PPID"; exit 143; }\n[ "${FAIL_MODE:-}" != copy_fail ] || exit 19\nexec /bin/cp "$@"\n')
        command('mv','[ "${FAIL_MODE:-}" != before_commit ] || exit 20\n/bin/mv "$@" || exit $?\n[ "${FAIL_MODE:-}" != after_commit ] || exit 21\n')
        self.helper=self.stage/'loader_check'
        self.helper.write_text('#!/bin/sh\necho "$LD_LIBRARY_PATH|${LD_PRELOAD:-}" > "$CALLED"\nexit "${LOADER_EXIT:-0}"\n');self.helper.chmod(0o755)
        (self.stage/'libcarplay_hook.so').write_text('fixture hook\n')
        self.originals={}
        # Translate every absolute vehicle source into a private host fixture.
        targets={'/proc/boot/libc.so.3':'native-libs/proc/boot/libc.so.3','/lib/libsocket.so.3':'native-libs/lib/libsocket.so.3',
                 '/etc/eso/production/dio_manager.json':'dio_manager.json','/mnt/system/etc/eso/production/dio_manager.json':'dio_manager.json',
                 '/etc/eso/production/smartphone_integrator.json':'smartphone_integrator.json','/mnt/system/etc/eso/production/smartphone_integrator.json':'smartphone_integrator.json',
                 '/etc/scripts/carplay_cleanup.sh':'carplay_cleanup.sh','/mnt/app/eso/hmi/lsd/lsd.sh':'lsd.sh','/mnt/app/eso/hmi/lsd/jars/NavActiveIgnore.jar':'jars/NavActiveIgnore.jar'}
        for target,local in targets.items():
            p=self.root/'sources'/target.lstrip('/');p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((RESOURCE/local).read_bytes());p.chmod(0o640)
            self.originals[target]=p
        for name in ['transaction.sh','run_stage1.sh']:
            text=(BASE/'stage1'/name).read_text()
            text=re.sub(r'^PATH=.*$',f'PATH={self.commands}:/usr/bin:/bin',text,count=1,flags=re.M)
            translations={target:str(p) for target,p in self.originals.items()}
            for target in ['/mnt/system/etc/eso/production','/etc/eso/production','/mnt/system/etc','/etc']:
                translations[target]=str(self.root/'sources'/target.lstrip('/'))
            translations['/mnt/app/root']=str(self.parent)
            pattern='|'.join(re.escape(t) for t in sorted(translations,key=len,reverse=True))
            text=re.sub(pattern,lambda m:translations[m.group(0)],text)
            (self.stage/name).write_text(text)
        # The wrapper checksum locks the test copy and host fixture, never real QNX ELF execution.
        wrapper=self.stage/'run_stage1.sh';text=wrapper.read_text()
        for name in ['loader_check','libcarplay_hook.so','transaction.sh','mount_state']:
            crc,size=subprocess.check_output(['cksum',str(self.stage/name)],text=True).split()[:2]
            text=re.sub(r'check_file \d+ \d+ "\$stage_dir/'+re.escape(name)+'"',f'check_file {crc} {size} "$stage_dir/{name}"',text)
        wrapper.write_text(text)
        self.before={p:(p.read_bytes(),p.stat().st_mode,p.stat().st_uid,p.stat().st_gid) for p in self.originals.values()}
    def run_script(self,name,*args,**env):
        return subprocess.run(['/bin/sh',str(self.stage/name),*args],capture_output=True,text=True,timeout=20,env=dict(os.environ,CALLED=str(self.counter),MOUNT_FLAG=str(self.mountflag),MOUNT_CALLS=str(self.mountcalls),**env))
    def assert_originals_unchanged(self):
        for p,v in self.before.items():self.assertEqual((p.read_bytes(),p.stat().st_mode,p.stat().st_uid,p.stat().st_gid),v)
    def prepared(self):
        result=self.run_script('run_stage1.sh');self.assertEqual(result.returncode,0,result.stdout+result.stderr)
    def test_success_backup_attributes_and_repeated_restore(self):
        self.prepared()
        self.assertEqual(self.counter.read_text(),'/proc/boot:/lib|\n')
        self.assertTrue((self.work/'backup/COMPLETE').is_file())
        self.assertEqual(self.mountflag.read_text(),'ro\n')
        self.assertEqual(self.mountcalls.read_text().splitlines(),['-uw /mnt/app','-ur /mnt/app'])
        for _ in range(2):self.assertEqual(self.run_script('transaction.sh','restore').returncode,0)
        self.assert_originals_unchanged()
        self.assertNotEqual(self.run_script('run_stage1.sh').returncode,0)
    def test_loader_failure_prevents_persistent_workspace(self):
        result=self.run_script('run_stage1.sh',LOADER_EXIT='4')
        self.assertNotEqual(result.returncode,0);self.assertFalse(self.work.exists());self.assert_originals_unchanged()
    def test_changed_baseline_prevents_loading_and_backup(self):
        p=self.originals['/etc/eso/production/dio_manager.json'];p.write_text('changed')
        result=self.run_script('run_stage1.sh');self.assertNotEqual(result.returncode,0)
        self.assertFalse(self.counter.exists());self.assertFalse(self.work.exists())
    def test_interrupted_install_restores_before_and_after_commit(self):
        self.prepared()
        for mode in ['copy_fail','before_commit','after_commit']:
            with self.subTest(mode=mode):
                result=self.run_script('transaction.sh','install',FAIL_MODE=mode)
                self.assertNotEqual(result.returncode,0)
                result=self.run_script('transaction.sh','restore');self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(self.run_script('transaction.sh','verify').returncode,0)
        self.assert_originals_unchanged()
    def test_reject_live_symlink_and_unknown_content(self):
        self.prepared();live=self.work/'rehearsal/live/item';live.unlink()
        external=self.root/'external';external.write_text('do not touch');live.symlink_to(external)
        self.assertNotEqual(self.run_script('transaction.sh','restore').returncode,0)
        self.assertEqual(external.read_text(),'do not touch');live.unlink();live.write_text('unexpected')
        self.assertNotEqual(self.run_script('transaction.sh','restore').returncode,0)
        self.assertEqual(live.read_text(),'unexpected')
    def test_backup_copy_failure_never_claims_complete(self):
        result=self.run_script('run_stage1.sh',FAIL_MODE='copy_fail')
        self.assertNotEqual(result.returncode,0);self.assertFalse((self.work/'backup/COMPLETE').exists());self.assert_originals_unchanged()
    def test_reject_changed_transaction_script(self):
        with (self.stage/'transaction.sh').open('a') as f:f.write('# unexpected change\n')
        self.assertNotEqual(self.run_script('run_stage1.sh').returncode,0)
        self.assertFalse(self.counter.exists());self.assertFalse(self.work.exists())
    def test_uid_whitespace_and_invalid_values(self):
        for uid in ['', '1000', '0 1000', 'root', '*']:
            with self.subTest(uid=uid):
                self.assertNotEqual(self.run_script('run_stage1.sh',ID_OUTPUT=uid).returncode,0)
                self.assertFalse(self.counter.exists());self.assertFalse(self.work.exists())
        self.assertNotEqual(self.run_script('run_stage1.sh',FAIL_MODE='id_fail').returncode,0)
        self.assertEqual(self.run_script('run_stage1.sh',ID_OUTPUT=' \t0 \n').returncode,0)
    def test_original_rw_mount_is_not_changed(self):
        self.mountflag.write_text('rw\n');self.prepared()
        self.assertFalse(self.mountcalls.exists());self.assertEqual(self.mountflag.read_text(),'rw\n')
    def test_remount_rw_failure_restores_and_prevents_workspace(self):
        r=self.run_script('run_stage1.sh',FAIL_MODE='rw_fail')
        self.assertNotEqual(r.returncode,0);self.assertFalse(self.work.exists())
        self.assertEqual(self.mountflag.read_text(),'ro\n');self.assertNotIn('STAGE1_V2_PASSED',r.stdout)
    def test_restore_ro_failure_cannot_report_success(self):
        r=self.run_script('run_stage1.sh',FAIL_MODE='ro_fail')
        self.assertNotEqual(r.returncode,0);self.assertEqual(self.mountflag.read_text(),'rw\n')
        self.assertNotIn('STAGE1_V2_PASSED',r.stdout);self.assertIn('could not restore',r.stderr)
    def test_copy_failure_restores_original_mount(self):
        r=self.run_script('run_stage1.sh',FAIL_MODE='copy_fail')
        self.assertNotEqual(r.returncode,0);self.assertEqual(self.mountflag.read_text(),'ro\n')
        self.assertNotIn('STAGE1_V2_PASSED',r.stdout)
    def test_mount_state_query_failure_prevents_remount(self):
        r=self.run_script('run_stage1.sh',FAIL_MODE='state_fail')
        self.assertNotEqual(r.returncode,0);self.assertFalse(self.mountcalls.exists());self.assertFalse(self.work.exists())
    def test_catchable_termination_restores_mount(self):
        r=self.run_script('run_stage1.sh',FAIL_MODE='term_signal')
        self.assertNotEqual(r.returncode,0)
        self.assertEqual(self.mountflag.read_text(),'ro\n')
        self.assertNotIn('STAGE1_V2_PASSED',r.stdout)
    def test_restore_action_manages_mount_without_rerunning_loader(self):
        self.prepared();self.counter.unlink()
        r=self.run_script('run_stage1.sh','restore')
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertFalse(self.counter.exists())
        self.assertEqual(self.mountflag.read_text(),'ro\n');self.assertIn('STAGE1_V2_PASSED',r.stdout)
if __name__=='__main__':unittest.main()

