"""Actual env-only scripts against isolated mounts, files and numeric PID shims."""
import os
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
import test_stage3 as fixture

BASE=fixture.BASE
RESOURCE=fixture.RESOURCE

class EnvProbeTests(unittest.TestCase):
    def setUp(self):
        self.s3=fixture.Stage3Tests();self.s3.setUp();self.addCleanup(self.s3.doCleanups)
        self.f=self.s3.f;f=self.f
        self.root=f.app/'root/mu1320-env-probe-v2'
        self.system=self.s3.system;self.active=self.s3.active
        shutil.copyfile(RESOURCE/'smartphone_integrator',f.app/'eso/bin/apps/smartphone_integrator')
        for p in (BASE/'env-probe').iterdir():
            if p.is_file() and p.name!='mount_state':shutil.copyfile(p,f.sd/p.name)
        def rewrite(s):
            s=re.sub(r'^PATH=.*$',f'PATH={f.commands}:/usr/bin:/bin',s,flags=re.M)
            return re.sub(r'/mnt/app|/mnt/system/etc/eso|/mnt/system|/etc/eso|/proc/boot/libc.so.3|/ramdisk|/tmp',lambda m:str(f.vehicle/m.group().lstrip('/')),s)
        # The collector only writes under /fs (removable media); map that to the fixture SD.
        collector=f.sd/'collect_env.sh';collector.write_text(rewrite((BASE/'env-probe/collect_env.sh').read_text()).replace('in /fs/*)',f'in {f.sd.resolve()}*)'))
        source=rewrite((BASE/'env-probe/env_probe.sh').read_text())
        for name in ['mount_state','collect_env.sh']:
            crc,size=subprocess.check_output(['cksum',str(f.sd/name)],text=True).split()[:2]
            source=re.sub(r'check \d+ \d+ "\$stage_dir/'+re.escape(name)+'"',f'check {crc} {size} "$stage_dir/{name}"',source)
        self.script=f.sd/'env_probe.sh';self.script.write_text(source)
        self.pidfile=f.vehicle/'ramdisk/var/run/smartphone_integrator_children.pid'
        self.pidfile.parent.mkdir(parents=True);self.pidfile.write_text('carplay: 202\n')
        pidin=f.commands/'pidin'
        pidin.write_text('#!'+sys.executable+'\n'+'''import os,sys
from pathlib import Path
a=sys.argv[1:];mode=os.environ.get('PID_MODE','')
names={'101':'/mnt/app/eso/bin/apps/smartphone_integrator','202':'/mnt/app/eso/bin/apps/dio_manager'}
if '-p' not in a:
 print('pid parent name');print('101 1 '+names['101'])
 if mode!='no_dio':print('202 101 '+names['202'])
 sys.exit(0)
p=a[a.index('-p')+1];name=names[p];parent='1' if p=='101' else '101'
if 'environment' in a:
 if mode=='env_error' and p=='202':print('Permission denied');sys.exit(1)
 if mode=='header_only' and p=='202':print('pid name environment');sys.exit(0)
 env='LD_LIBRARY_PATH=/proc/boot:/lib IPL_CONFIG_DIR_DIO_MANAGER=/etc/eso/production'
 candidate='MU1320_SI_PROBE=' in Path(os.environ['ACTIVE_FILE']).read_text()
 if (p=='202' and candidate) or (p=='101' and mode=='parent_marker'):env+=' MU1320_SI_PROBE=mu1320_env_v2_a7f907b7'
 print(p+' '+name+' '+env);sys.exit(0)
if 'users' in a:print(p+' '+name+' 0 0 0 0 0 0');sys.exit(0)
start='2026-09-23_00:00:00'
if mode=='changed' and p=='202':
 state=Path(os.environ['PID_COUNTER']);n=int(state.read_text()) if state.exists() else 0
 state.write_text(str(n+1));start=str(n)
print('pid parent name start');print(p+' '+parent+' '+name+' '+start)
''');pidin.chmod(0o755)

    def run_action(self,*args,fail='',mode=''):
        return subprocess.run(['/bin/sh',str(self.script),*args],capture_output=True,text=True,timeout=25,
            env=dict(os.environ,MOUNT_FLAG=str(self.f.flag),SYSTEM_FLAG=str(self.s3.sysflag),MOUNT_CALLS=str(self.f.calls),
                     ACTIVE_FILE=str(self.active),PID_MODE=mode,PID_COUNTER=str(self.f.root/'pid-counter'),FAIL=fail))
    def success(self,*args):
        r=self.run_action(*args);self.assertEqual(r.returncode,0,r.stdout+r.stderr);return r
    def propagate(self):shutil.copyfile(self.system,self.active)
    def test_three_phase_trial_and_unchanged_original_files(self):
        before=self.success('collect','before');self.assertIn('MARKER_NOT_OBSERVED: role=DIO pid=202',before.stdout)
        self.success('install');self.assertEqual(self.active.read_bytes(),(RESOURCE/'smartphone_integrator.json').read_bytes())
        self.propagate();marked=self.success('collect','marked')
        self.assertIn('MARKER_OBSERVED: role=DIO pid=202',marked.stdout)
        self.assertIn('PID_FILE_MATCH: 202',marked.stdout);self.assertIn('DIRECT_SI_PARENT: dio=202 si=101',marked.stdout)
        self.assertIn('RAM_WITNESS_PRESENT',marked.stdout)
        self.success('rollback');self.propagate();restored=self.success('collect','restored')
        self.assertIn('MARKER_NOT_OBSERVED: role=DIO pid=202',restored.stdout)
        self.f.assert_production_unchanged()
        self.assertEqual(self.f.flag.read_text(),'ro\n');self.assertEqual(self.s3.sysflag.read_text(),'ro\n')
        logs=list((self.f.sd/'out').glob('*/collect.txt'))
        self.assertEqual(sorted(p.parent.name.split('-')[0] for p in logs),['before','marked','restored'])
        self.assertIn('SAVED_ON_SD: '+str(self.f.sd.resolve()/'out'),marked.stdout)
        self.assertEqual([d for d in (self.f.vehicle/'tmp').iterdir() if d.is_dir()],[])
        self.assertTrue(all('ENV_PROBE_COLLECT_END' in p.read_text() for p in logs))
    def test_install_failures_restore_mounts_and_allow_rollback(self):
        for i,fault in enumerate(['backup_copy','before_commit','after_commit','mount_rw']):
            with self.subTest(fault=fault):
                if i:self.doCleanups();self.setUp()
                r=self.run_action('install',fail=fault);self.assertNotEqual(r.returncode,0)
                self.assertEqual(self.f.flag.read_text(),'ro\n');self.assertEqual(self.s3.sysflag.read_text(),'ro\n')
                self.success('rollback');self.f.assert_production_unchanged()
    def test_failed_rollback_can_retry_with_own_ram_witness(self):
        self.success('install')
        r=self.run_action('rollback',fail='before_commit');self.assertNotEqual(r.returncode,0)
        self.success('rollback');self.f.assert_production_unchanged()
    def test_corrupt_candidate_or_collector_blocks_before_remount(self):
        for i,name in enumerate(['smartphone_integrator.json','collect_env.sh']):
            with self.subTest(name=name):
                if i:self.doCleanups();self.setUp()
                (self.f.sd/name).write_text('bad')
                self.assertNotEqual(self.run_action('install').returncode,0)
                self.assertFalse(self.f.calls.exists());self.assertFalse(self.root.exists())
    def test_backup_corruption_blocks_restore_and_preserves_current_file(self):
        self.success('install');current=self.system.read_bytes()
        (self.root/'backup/smartphone_integrator.json').write_text('bad')
        self.assertNotEqual(self.run_action('rollback').returncode,0)
        self.assertEqual(current,self.system.read_bytes())
    def test_no_dio_or_header_only_or_error_is_not_negative(self):
        for mode in ['no_dio','header_only','env_error','changed']:
            with self.subTest(mode=mode):
                r=self.run_action('collect','before',mode=mode)
                self.assertNotIn('MARKER_NOT_OBSERVED: role=DIO',r.stdout)
                self.assertNotIn('MARKER_OBSERVED: role=DIO',r.stdout)
                self.assertTrue('INCONCLUSIVE_NO_DIO' in r.stdout or 'INVALID_OR_PROCESS_CHANGED' in r.stdout,r.stdout)
    def test_stale_pidfile_falls_back_to_verified_full_name(self):
        self.pidfile.write_text('carplay: 999\n')
        r=self.success('collect','before')
        self.assertIn('PID_FILE_NOT_MATCHED: 202',r.stdout)
        self.assertIn('MARKER_NOT_OBSERVED: role=DIO pid=202',r.stdout)
        self.assertNotIn('pid=999',r.stdout)
    def test_parent_marker_is_flagged_and_status_collect_do_not_remount(self):
        self.success('status');r=self.run_action('collect','before',mode='parent_marker')
        self.assertIn('source attribution is confounded',r.stdout)
        self.assertFalse(self.f.calls.exists());self.assertFalse(self.root.exists());self.f.assert_production_unchanged()
    def test_mount_restore_failure_is_not_success(self):
        r=self.run_action('install',fail='mount_ro')
        self.assertNotEqual(r.returncode,0)
        self.assertNotIn('ENV_PROBE_install_FILES_PASSED',r.stdout)
    def test_unknown_system_file_not_overwritten(self):
        self.system.write_text('unknown')
        for action in ['install','rollback']:
            self.assertNotEqual(self.run_action(action).returncode,0)
            self.assertEqual(self.system.read_text(),'unknown')
        self.assertFalse(self.f.calls.exists())
    def test_initial_rw_mounts_remain_rw(self):
        self.f.flag.write_text('rw\n');self.s3.sysflag.write_text('rw\n')
        self.success('install');self.success('rollback')
        self.assertEqual(self.f.flag.read_text(),'rw\n');self.assertEqual(self.s3.sysflag.read_text(),'rw\n')
        self.assertFalse(self.f.calls.exists());self.f.assert_production_unchanged()
    def test_existing_workspace_and_witness_symlink_block_before_writes(self):
        self.root.mkdir();sentinel=self.root/'keep';sentinel.write_text('preserve')
        self.assertNotEqual(self.run_action('install').returncode,0)
        self.assertEqual(sentinel.read_text(),'preserve');self.assertFalse(self.f.calls.exists())
        sentinel.unlink();self.root.rmdir()
        witness=self.f.vehicle/'tmp/mu1320-env-probe-v2-install-witness'
        witness.symlink_to(self.system)
        self.assertNotEqual(self.run_action('install').returncode,0)
        self.f.assert_production_unchanged();self.assertFalse(self.f.calls.exists())

    def test_collect_refuses_non_removable_location_and_readonly_sd(self):
        collector=self.f.sd/'collect_env.sh'
        guarded=collector.read_text().replace(f'in {self.f.sd.resolve()}*)','in /fs/*)')
        collector.write_text(guarded)
        r=subprocess.run(['/bin/sh',str(collector),'before'],capture_output=True,text=True,timeout=25)
        self.assertEqual(r.returncode,2);self.assertIn('must run from SD/USB under /fs',r.stdout)
        self.assertFalse((self.f.sd/'out').exists())
    def test_unwritable_sd_stops_with_clear_message(self):
        blocker=self.f.sd/'out';blocker.write_text('not a directory')
        r=self.run_action('collect','before')
        self.assertNotEqual(r.returncode,0);self.assertIn('STOP: cannot create',r.stdout+r.stderr)

if __name__=='__main__':unittest.main()
