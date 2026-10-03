"""Exercise actual Stage3 shell scripts with isolated filesystem and QNX tool shims."""
import os,re,shutil,subprocess,unittest
from pathlib import Path
import test_stage2_install as fixtures
BASE=fixtures.BASE;RESOURCE=fixtures.RESOURCE

class Stage3Tests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.Stage2InstallTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        f=self.f;self.root=f.app/'root/mu1320-rgi-stage3-v1';self.system=f.vehicle/'mnt/system/etc/eso/production/smartphone_integrator.json';self.active=f.vehicle/'etc/eso/production/smartphone_integrator.json'
        (f.vehicle/'tmp').mkdir();self.arm=f.vehicle/'tmp/mu1320-stage3.arm'
        self.sysflag=f.root/'system-state';self.sysflag.write_text('ro\n')
        for p in (BASE/'stage3').iterdir():
            if p.is_file():shutil.copyfile(p,f.sd/p.name)
        def command(name,body):
            p=f.commands/name;p.write_text('#!/bin/sh\n'+body);p.chmod(0o755)
        command('mount','''echo "$*" >> "$MOUNT_CALLS"
case "$2" in */mnt/app) flag=$MOUNT_FLAG ;; */mnt/system) flag=$SYSTEM_FLAG ;; *) exit 80 ;; esac
case "$1" in -uw) [ "${FAIL:-}" != mount_rw ] || exit 81; echo rw > "$flag" ;; -ur) [ "${FAIL:-}" != mount_ro ] || exit 82; echo ro > "$flag" ;; *) exit 83 ;; esac
''')
        command('mkdir','exec /bin/mkdir "$@"\n')
        command('cp','''case "$*" in *backup/smartphone_integrator.json*) [ "${FAIL:-}" != backup_copy ] || exit 90 ;; esac
exec /bin/cp "$@"
''')
        command('mv','''case "$*" in */production/smartphone_integrator.json)
 [ "$(cat "$SYSTEM_FLAG")" = rw ] || exit 88
 [ "${FAIL:-}" != before_commit ] || exit 90
 /bin/mv "$@" || exit $?
 [ "${FAIL:-}" != after_commit ] || exit 91 ;;
*) exec /bin/mv "$@" ;; esac
''')
        helper=f.sd/'mount_state';helper.write_text('#!/bin/sh\ncase "$1" in */mnt/app) cat "$MOUNT_FLAG" ;; */mnt/system) cat "$SYSTEM_FLAG" ;; *) exit 2 ;; esac\n');helper.chmod(0o755)
        self.rewrite=lambda s:re.sub(r'/mnt/app|/mnt/system/etc/eso|/mnt/system|/etc/eso|/proc/boot/libc.so.3|/lib/libsocket.so.3|/tmp/mu1320-stage3[^\s";]*|/tmp/carplay_verbose|/tmp/carplay_hook.log',lambda m:str(f.vehicle/m.group().lstrip('/')),s)
        socket=f.vehicle/'lib/libsocket.so.3';socket.parent.mkdir();shutil.copyfile(RESOURCE/'native-libs/lib/libsocket.so.3',socket)
        for local,target in [('dio_manager','eso/bin/apps/dio_manager'),('libairplay.so','eso/lib/libairplay.so'),('libNmeSDK.so','armle/usr/lib/libNmeSDK.so'),('libNmeBaseClasses.so','armle/usr/lib/libNmeBaseClasses.so'),('libNme.so','armle/usr/lib/libNme.so'),('cinemo/libNmeTransport.so','armle/usr/lib/cinemo/libNmeTransport.so')]:
            p=f.app/target;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(RESOURCE/local,p)
        # Runtime wrapper paths are rewritten too; regenerate its checksum inside installer.
        wrapper=self.rewrite((BASE/'stage3/carplay_startup.sh').read_text())
        # Never ask the host dynamic loader to load a QNX ARM binary.
        wrapper=wrapper.replace('LD_PRELOAD=', 'TRIAL_PRELOAD=')
        (f.sd/'carplay_startup.sh').write_text(wrapper)
        script=self.rewrite((BASE/'stage3/stage3.sh').read_text())
        script=re.sub(r'^PATH=.*$',f'PATH={f.commands}:/usr/bin:/bin',script,count=1,flags=re.M)
        for name in ['mount_state','carplay_startup.sh']:
            crc,size=subprocess.check_output(['cksum',str(f.sd/name)],text=True).split()[:2]
            script=re.sub(r'check \d+ \d+ ("\$(?:stage_dir|ROOT)/'+re.escape(name)+r'")',f'check {crc} {size} \\1',script)
        self.script=f.sd/'stage3.sh';self.script.write_text(script)
    def run_action(self,action,fail=''):
        f=self.f
        return subprocess.run(['/bin/sh',str(self.script),action],capture_output=True,text=True,timeout=25,env=dict(os.environ,MOUNT_FLAG=str(f.flag),SYSTEM_FLAG=str(self.sysflag),MOUNT_CALLS=str(f.calls),FAIL=fail))
    def success(self,action):
        r=self.run_action(action);self.assertEqual(r.returncode,0,r.stdout+r.stderr);return r
    def test_install_rollback_preserves_production_except_si_and_restores_mounts(self):
        self.success('install');self.assertNotEqual(self.system.read_bytes(),self.active.read_bytes())
        self.assertEqual(self.active.read_bytes(),(RESOURCE/'smartphone_integrator.json').read_bytes())
        self.success('rollback');self.success('rollback');self.f.assert_production_unchanged()
        self.assertEqual(self.f.flag.read_text(),'ro\n');self.assertEqual(self.sysflag.read_text(),'ro\n')
    def test_install_failure_boundaries_restore_or_allow_rollback(self):
        for i,fault in enumerate(['backup_copy','before_commit','after_commit','mount_rw']):
            with self.subTest(fault=fault):
                if i:self.doCleanups();self.setUp()
                r=self.run_action('install',fault);self.assertNotEqual(r.returncode,0)
                self.assertEqual(self.f.flag.read_text(),'ro\n');self.assertEqual(self.sysflag.read_text(),'ro\n')
                self.success('rollback');self.f.assert_production_unchanged()
    def test_readonly_restore_failure_cannot_report_success(self):
        r=self.run_action('install','mount_ro');self.assertNotEqual(r.returncode,0)
        self.assertNotIn('STAGE3_install_FILES_PASSED',r.stdout)
        self.success('rollback');self.f.assert_production_unchanged()
    def test_arm_requires_reboot_propagation(self):
        self.success('install');self.assertNotEqual(self.run_action('arm').returncode,0);self.assertFalse(self.arm.exists())
        shutil.copyfile(self.system,self.active);self.success('arm');self.assertTrue(self.arm.exists())
        self.success('disarm');self.assertFalse(self.arm.exists())
    def test_corrupt_backup_blocks_rollback(self):
        self.success('install');(self.root/'backup/smartphone_integrator.json').write_text('bad')
        current=self.system.read_bytes();self.assertNotEqual(self.run_action('rollback').returncode,0);self.assertEqual(current,self.system.read_bytes())
    def test_unknown_active_config_or_payload_prevents_writes(self):
        (self.f.sd/'libcarplay_hook.so').write_text('bad')
        self.assertNotEqual(self.run_action('install').returncode,0);self.assertFalse(self.root.exists());self.assertFalse(self.f.calls.exists())
    def test_status_is_readonly(self):
        self.success('status');self.f.assert_production_unchanged();self.assertFalse(self.root.exists());self.assertFalse(self.f.calls.exists())
    def test_wrapper_one_shot_then_stock_preserves_args(self):
        self.success('install');shutil.copyfile(self.system,self.active);self.success('arm')
        binary=self.f.app/'eso/bin/apps/dio_manager'
        binary.write_text('#!/bin/sh\nprintf "PRELOAD=%s\\nCONFIG=%s\\nARG=%s\\n" "${TRIAL_PRELOAD:-}" "${IPL_CONFIG_DIR_DIO_MANAGER:-}" "$1"\n');binary.chmod(0o755)
        env=dict(os.environ,PATH=str(self.f.commands)+':/usr/bin:/bin',MOUNT_FLAG=str(self.f.flag),SYSTEM_FLAG=str(self.sysflag),IPL_CONFIG_DIR_DIO_MANAGER='/etc/eso/production')
        def run():return subprocess.run(['/bin/sh',str(self.root/'carplay_startup.sh'),'kept argument'],env=env,capture_output=True,text=True)
        first=run();self.assertEqual(first.returncode,0,first.stderr);self.assertIn('libcarplay_hook.so',first.stdout);self.assertIn('ARG=kept argument',first.stdout);self.assertFalse(self.arm.exists())
        second=run();self.assertEqual(second.returncode,0,second.stderr);self.assertIn('PRELOAD=\nCONFIG=/etc/eso/production',second.stdout)
        # A damaged hook after arming must use stock without consuming the token.
        self.arm.write_text('MU1320-STAGE3-ONE-SHOT-V1\n')
        (self.root/'libcarplay_hook.so').write_text('damaged')
        third=run();self.assertEqual(third.returncode,0,third.stderr)
        self.assertIn('PRELOAD=\nCONFIG=/etc/eso/production',third.stdout);self.assertTrue(self.arm.exists())
    def test_wrong_runtime_owner_is_rejected(self):
        ls=self.f.commands/'ls';s=ls.read_text();s=s.replace("print(line)","if '.mu1320-stage3-install.' in line: f=line.split();f[3]='99';line=' '.join(f)\n print(line)");ls.write_text(s)
        r=self.run_action('install');self.assertNotEqual(r.returncode,0)
        self.assertIn('pending SI validation',r.stderr);self.f.assert_production_unchanged()
if __name__=='__main__':unittest.main()
