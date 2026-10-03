#!/usr/bin/env python3
"""Audit the stage1 artifacts and generate a fixed-scope vehicle wrapper."""
import hashlib,json,subprocess
from pathlib import Path
from audit_native import inspect
from audit_native_probe import check_binary
BASE=Path(__file__).resolve().parents[1]
RESOURCE=BASE.parent/'resource'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    previous=json.loads((BASE/'reports/native-probe-audit.json').read_text())
    inventory={}
    for n,h in previous['runtime_input_sha256'].items():
        assert sha(RESOURCE/n)==h,n
        inventory[n]=inspect(RESOURCE/n)
    audits={n:check_binary(BASE/'stage1'/n,inventory) for n in ['libcarplay_hook.so','loader_check','mount_state']}
    for n,a in audits.items():
        assert a['status']=='STATIC_PASS',(n,a)
        assert set(a['dependency_closure'])<= {'libc.so.3','libsocket.so.3'},(n,a)
    assert set(audits['mount_state']['required_symbols']) <= {'memset','statvfs','statvfs64','strcmp','fprintf','stderr','strerror','__get_errno_ptr','puts','_init_libc','_init_array','_preinit_array','_fini_array','atexit','exit'},audits['mount_state']['required_symbols']
    hook=inspect(BASE/'stage1/libcarplay_hook.so')
    assert 'rgd_module_def' in hook['exports']
    assert not any('coverart' in x.lower() or x.startswith('stbi_') for x in hook['exports'])
    allowed={'puts','printf','fflush','stdout','alarm','dlopen','dlsym','dlerror','dlclose','sigemptyset','sigaddset','signal','sigprocmask','_init_libc','_init_array','_preinit_array','_fini_array','atexit','exit'}
    assert set(audits['loader_check']['required_symbols'])<=allowed,audits['loader_check']['required_symbols']
    mappings=[('dio_manager.json','/etc/eso/production/dio_manager.json','etc-dio.json'),('dio_manager.json','/mnt/system/etc/eso/production/dio_manager.json','system-dio.json'),('smartphone_integrator.json','/etc/eso/production/smartphone_integrator.json','etc-si.json'),('smartphone_integrator.json','/mnt/system/etc/eso/production/smartphone_integrator.json','system-si.json'),('carplay_cleanup.sh','/etc/scripts/carplay_cleanup.sh','carplay_cleanup.sh'),('lsd.sh','/mnt/app/eso/hmi/lsd/lsd.sh','lsd.sh'),('jars/NavActiveIgnore.jar','/mnt/app/eso/hmi/lsd/jars/NavActiveIgnore.jar','NavActiveIgnore.jar')]
    pinned={}
    for n in ['input-manifest.json','supplement-manifest.json']: pinned.update(json.loads((BASE/'reports'/n).read_text())['files'])
    checks=[];backups=[];original=[]
    def check(local,target):
        crc,size=subprocess.check_output(['cksum',str(local)],text=True).split()[:2]
        return crc,size,f'check_file {crc} {size} {target}'
    for n in ['loader_check','libcarplay_hook.so','transaction.sh','mount_state']:
        checks.append(check(BASE/'stage1'/n,'"$stage_dir/'+n+'"')[2])
    for local,target in [('native-libs/proc/boot/libc.so.3','/proc/boot/libc.so.3'),('native-libs/lib/libsocket.so.3','/lib/libsocket.so.3')]: checks.append(check(RESOURCE/local,target)[2])
    for local,target,name in mappings:
        assert sha(RESOURCE/local)==pinned[local]['sha256']
        crc,size,line=check(RESOURCE/local,target);checks.append(line);original.append(line)
        backups.append(f'backup {target} {name} {crc} {size}')
    text=(BASE/'scripts/run_stage1.sh.in').read_text()
    for tag,value in [('@CHECKS@',checks),('@BACKUPS@',backups),('@ORIGINAL_CHECKS@',original)]:
        assert text.count(tag)==1;text=text.replace(tag,'\n'.join(value))
    (BASE/'stage1/run_stage1.sh').write_text(text)
    report=dict(version=2,mount_management='Query statvfs; remount only /mnt/app if read-only; restore initial state on exit/HUP/INT/TERM; verify before success',vehicle_runtime_tested=False,artifacts=audits,navigation_only_module_table=True,loader_does_not_call_hook_entries=True,backup_sources=[target for _,target,_ in mappings],persistent_writes_confined_to='/mnt/app/root/mu1320-rgi-stage1-v2',limitations=['Backup is a selected-file baseline, not a complete vehicle recovery image.','Rehearsal tests only isolated files on /mnt/app; /mnt/system and alias writes remain untested.','dlopen in standalone process does not prove actual dio_manager interposition.'])
    (BASE/'reports/stage1-audit.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Stage 1 static audits and generated wrapper passed')
if __name__=='__main__':main()
