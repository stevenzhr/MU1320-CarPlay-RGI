"""Run the actual installer on private host fixtures with simulated QNX tools/mounts."""
import hashlib,os,re,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
BASE=Path(__file__).resolve().parents[1];RESOURCE=BASE.parent/'resource'
class Stage2InstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='mu1320-stage2-');self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.vehicle=self.root/'vehicle';self.sd=self.root/'sd';self.sd.mkdir();self.commands=self.root/'commands';self.commands.mkdir()
        self.app=self.vehicle/'mnt/app';self.jars=self.app/'eso/hmi/lsd/jars';self.jars.mkdir(parents=True)
        (self.app/'root').mkdir();self.work=self.app/'root/mu1320-rgi-stage2-v2'
        self.old=self.jars/'NavActiveIgnore.jar';self.new=self.jars/'CarPlayRGI-MU1320-Stage2.jar'
        self.flag=self.root/'mount-state';self.flag.write_text('ro\n');self.calls=self.root/'mount-calls'
        self.source={}
        def original(target,local,mode=0o644):
            p=self.vehicle/target.lstrip('/');p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(RESOURCE/local,p);p.chmod(mode);self.source[p]=p.read_bytes()
        for p in (RESOURCE/'jars').iterdir():original('/mnt/app/eso/hmi/lsd/jars/'+p.name,'jars/'+p.name,0o777 if p.name=='NavActiveIgnore.jar' else 0o644)
        for target,local in [('/proc/boot/libc.so.3','native-libs/proc/boot/libc.so.3'),('/mnt/app/eso/hmi/lsd/lsd.sh','lsd.sh'),('/etc/eso/production/dio_manager.json','dio_manager.json'),('/mnt/system/etc/eso/production/dio_manager.json','dio_manager.json'),('/etc/eso/production/smartphone_integrator.json','smartphone_integrator.json'),('/mnt/system/etc/eso/production/smartphone_integrator.json','smartphone_integrator.json')]:original(target,local)
        prior=self.app/'root/mu1320-rgi-stage1-v2/backup/NavActiveIgnore.jar';prior.parent.mkdir(parents=True);shutil.copyfile(self.old,prior);prior.chmod(0o777)
        shutil.copyfile(BASE/'stage2/carplay_mu1320_stage2.jar.DISABLED',self.sd/'carplay_mu1320_stage2.jar.DISABLED')
        helper=self.sd/'mount_state';helper.write_text('#!/bin/sh\ncat "$MOUNT_FLAG"\n');helper.chmod(0o755)
        def command(name,body):
            p=self.commands/name;p.write_text('#!/bin/sh\n'+body);p.chmod(0o755)
        command('id','printf " 0\\n"\n');command('uname','echo "QNX mmx 6.5.0 fixture armle"\n');command('sync',':\n');command('chown','exit 99\n')
        command('mount','echo "$*" >> "$MOUNT_CALLS"\ncase "$1" in -uw) echo rw > "$MOUNT_FLAG" ;; -ur) [ "${FAIL:-}" != ro_fail ] || exit 1; echo ro > "$MOUNT_FLAG" ;; *) exit 2 ;; esac\n')
        command('mkdir','[ "$(cat "$MOUNT_FLAG")" = rw ] || exit 88\nexec /bin/mkdir "$@"\n')
        command('cp','''[ "$(cat "$MOUNT_FLAG")" = rw ] || exit 88
case "$*" in *backup/NavActiveIgnore.jar*) [ "${FAIL:-}" != backup_copy ] || exit 90 ;; esac
case "$*" in *.mu1320-stage2.pending*) [ "${FAIL:-}" != payload_copy ] || exit 90 ;; esac
exec /bin/cp "$@"
''')
        command('mv','''[ "$(cat "$MOUNT_FLAG")" = rw ] || exit 88
point=none
case "$*" in *quarantine/NavActiveIgnore.jar) point=quarantine ;; *jars/CarPlayRGI-MU1320-Stage2.jar) point=activate ;; esac
[ "${FAIL:-}" != "before_$point" ] || exit 91
/bin/mv "$@" || exit $?
[ "${FAIL:-}" != "after_$point" ] || exit 92
''')
        ls=self.commands/'ls';ls.write_text('#!'+sys.executable+'\n'+'''import subprocess,sys
r=subprocess.run(['/bin/ls',*sys.argv[1:]],capture_output=True,text=True)
for line in r.stdout.splitlines():
 f=line.split()
 if len(f)>=9 and f[0][0] in '-dl':f[0]=f[0][:10];f[2]=f[3]='0';line=' '.join(f)
 print(line)
sys.stderr.write(r.stderr);sys.exit(r.returncode)
''');ls.chmod(0o755)
        text=(BASE/'stage2/stage2.sh').read_text()
        text=re.sub(r'^PATH=.*$',f'PATH={self.commands}:/usr/bin:/bin',text,count=1,flags=re.M)
        # Single pass avoids replacing /etc twice inside /mnt/system/etc.
        text=re.sub(r'/mnt/app|/mnt/system/etc/eso|/mnt/system|/etc/eso|/proc/boot/libc.so.3|/tmp/carplay_java.log',lambda m:str(self.vehicle/m.group().lstrip('/')),text)
        crc,size=subprocess.check_output(['cksum',str(helper)],text=True).split()[:2]
        text=re.sub(r'check_file \d+ \d+ "\$stage_dir/mount_state"',f'check_file {crc} {size} "$stage_dir/mount_state"',text)
        self.script=self.sd/'stage2.sh';self.script.write_text(text)
    def run_action(self,action,fail=''):
        return subprocess.run(['/bin/sh',str(self.script),action],capture_output=True,text=True,timeout=25,env=dict(os.environ,MOUNT_FLAG=str(self.flag),MOUNT_CALLS=str(self.calls),FAIL=fail))
    def assert_production_unchanged(self,include_old=True):
        for p,content in self.source.items():
            if p==self.old and not include_old:continue
            self.assertEqual(p.read_bytes(),content,str(p))
    def install(self):
        r=self.run_action('install');self.assertEqual(r.returncode,0,r.stdout+r.stderr)
    def test_install_rollback_and_repeated_rollback(self):
        self.install();self.assertTrue(self.new.exists());self.assertFalse(self.old.exists())
        self.assertEqual(self.new.stat().st_mode&0o777,0o644);self.assertEqual(self.flag.read_text(),'ro\n');self.assert_production_unchanged(False)
        for _ in range(2):
            r=self.run_action('rollback');self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertFalse(self.new.exists());self.assertEqual(self.old.stat().st_mode&0o777,0o777)
        self.assert_production_unchanged();self.assertEqual(self.flag.read_text(),'ro\n')
    def test_install_interruption_can_rollback_each_file_boundary(self):
        # Separate fixture per interruption to preserve the real no-overwrite policy.
        for fault in ['backup_copy','payload_copy','before_quarantine','after_quarantine','before_activate','after_activate']:
            with self.subTest(fault=fault):
                if fault!='backup_copy':self.tearDown();self.doCleanups();self.setUp()
                r=self.run_action('install',fault);self.assertNotEqual(r.returncode,0)
                self.assertEqual(self.flag.read_text(),'ro\n')
                r=self.run_action('rollback');self.assertEqual(r.returncode,0,r.stdout+r.stderr)
                self.assertFalse(self.new.exists());self.assert_production_unchanged()
    def test_unknown_jar_rejected_before_remount(self):
        (self.jars/'unexpected.jar').write_text('unknown')
        r=self.run_action('install');self.assertNotEqual(r.returncode,0);self.assertFalse(self.work.exists());self.assertFalse(self.calls.exists())
    def test_changed_payload_rejected_before_remount(self):
        (self.sd/'carplay_mu1320_stage2.jar.DISABLED').write_text('bad')
        self.assertNotEqual(self.run_action('install').returncode,0);self.assertFalse(self.calls.exists());self.assert_production_unchanged()
    def test_existing_workspace_not_overwritten(self):
        self.work.mkdir();(self.work/'sentinel').write_text('keep')
        self.assertNotEqual(self.run_action('install').returncode,0);self.assertEqual((self.work/'sentinel').read_text(),'keep');self.assertFalse(self.calls.exists())
    def test_changed_backup_refuses_destructive_rollback(self):
        self.install();(self.work/'backup/NavActiveIgnore.jar').write_text('changed')
        self.assertNotEqual(self.run_action('rollback').returncode,0);self.assertTrue(self.new.exists());self.assertFalse(self.old.exists())
    def test_symlink_payload_destination_rejected(self):
        other=self.root/'sentinel';other.write_text('keep');self.new.symlink_to(other)
        self.assertNotEqual(self.run_action('install').returncode,0);self.assertEqual(other.read_text(),'keep');self.assertFalse(self.calls.exists())
    def test_readonly_restore_failure_is_not_success(self):
        r=self.run_action('install','ro_fail');self.assertNotEqual(r.returncode,0)
        self.assertNotIn('STAGE2_install_FILES_PASSED',r.stdout)
        # A later rollback preserves the then-current RW state instead of guessing.
        r=self.run_action('rollback');self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assert_production_unchanged()
    def test_archive_enumeration_failure_rejected_before_remount(self):
        cmd=self.commands/'find';cmd.write_text('#!/bin/sh\nexit 1\n');cmd.chmod(0o755)
        r=self.run_action('install');self.assertNotEqual(r.returncode,0);self.assertFalse(self.calls.exists())
    def test_status_does_not_write_or_remount(self):
        r=self.run_action('status');self.assertEqual(r.returncode,0,r.stderr)
        self.assertFalse(self.work.exists());self.assertFalse(self.calls.exists());self.assert_production_unchanged()
if __name__=='__main__':unittest.main()
