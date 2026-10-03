#!/usr/bin/env python3
"""Prepare a one-shot native trial; leave all upstream sources unchanged."""
import copy,difflib,hashlib,json,re,shutil,subprocess
from pathlib import Path
from formats import config
from prepare_configs import add_ids
BASE=Path(__file__).resolve().parents[1]; RESOURCE=BASE.parent/'resource'; STAGE=BASE/'stage3'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def crc(p):return subprocess.check_output(['cksum',str(p)],text=True).split()[:2]
def main():
    assert json.loads((BASE/'reports/stage2-vehicle-v2.json').read_text())['java_initialization_observed']
    source=(RESOURCE/'smartphone_integrator.json').read_text()
    manifest=json.loads((BASE/'reports/input-manifest.json').read_text())['files']
    for n in ['smartphone_integrator.json','dio_manager.json']:assert sha(RESOURCE/n)==manifest[n]['sha256']
    start=source.index('"carplay":{');end=source.index('"carlife":{',start)
    child=source[start:end]
    assert child.count('"exec":"dio_manager"')==1 and child.count('"path":"/mnt/app/eso/bin/apps"')==1
    child=child.replace('"exec":"dio_manager"','"exec":"carplay_startup.sh"').replace('"path":"/mnt/app/eso/bin/apps"','"path":"/mnt/app/root/mu1320-rgi-stage3-v1"')
    updated=source[:start]+child+source[end:]
    expected=copy.deepcopy(config(source));expected['children']['carplay'].update(exec='carplay_startup.sh',path='/mnt/app/root/mu1320-rgi-stage3-v1')
    assert config(updated)==expected
    (STAGE/'smartphone_integrator.json').write_text(updated)
    (STAGE/'dio_manager.json').write_text(add_ids((RESOURCE/'dio_manager.json').read_text()))
    (STAGE/'IDENTITY').write_text('MU1320-STAGE3-NATIVE-ONESHOT-V1\n')
    (STAGE/'ARM-TOKEN').write_text('MU1320-STAGE3-ONE-SHOT-V1\n')
    hook=BASE/'stage1/libcarplay_hook.so'
    assert sha(hook)==json.loads((BASE/'reports/stage1-build.json').read_text())['artifacts']['libcarplay_hook.so']['sha256']
    shutil.copyfile(hook,STAGE/'libcarplay_hook.so')
    values={}
    for label,p in [('SI_OLD',RESOURCE/'smartphone_integrator.json'),('SI_NEW',STAGE/'smartphone_integrator.json'),('DIO',STAGE/'dio_manager.json'),('HOOK',hook),('MOUNT',STAGE/'mount_state'),('ARM',STAGE/'ARM-TOKEN'),('IDENTITY',STAGE/'IDENTITY')]:
        c,n=crc(p);values[label+'_CRC']=c;values[label+'_SIZE']=n
    def render(name,output):
        text=(BASE/'scripts'/name).read_text()
        for key,value in values.items():text=text.replace('@'+key+'@',value)
        assert not re.search(r'@[A-Z_]+@',text)
        (STAGE/output).write_text(text)
        subprocess.run(['/bin/sh','-n',str(STAGE/output)],check=True)
    render('stage3_wrapper.sh.in','carplay_startup.sh')
    runtime=[];payload=[]
    for n,dest,mode in [('carplay_startup.sh','carplay_startup.sh','-rwxr-xr-x'),('libcarplay_hook.so','libcarplay_hook.so','-rw-r--r--'),('dio_manager.json','config/dio_manager.json','-rw-r--r--')]:
        c,size=crc(STAGE/n)
        runtime.append(f'check {c} {size} "$ROOT/{dest}" && [ "$(attrs "$ROOT/{dest}")" = \'{mode} 0 0\' ] || fail "runtime {n} validation"')
    for n in ['carplay_startup.sh','libcarplay_hook.so','dio_manager.json','smartphone_integrator.json','IDENTITY']:
        c,size=crc(STAGE/n);payload.append(f'check {c} {size} "$stage_dir/{n}" || fail "payload {n} checksum"')
    # Same library baselines that passed standalone loading on this vehicle.
    for n in ['native-libs/lib/libsocket.so.3']:
        p=RESOURCE/n;c,size=crc(p);payload.append(f'check {c} {size} /lib/libsocket.so.3 || fail "libsocket baseline"')
    values['RUNTIME_CHECKS']='\n    '.join(runtime);values['PAYLOAD_CHECKS']='\n    '.join(payload)
    pinned=dict(manifest)
    pinned.update(json.loads((BASE/'reports/supplement-manifest.json').read_text())['files'])
    for local,target in [('dio_manager','/mnt/app/eso/bin/apps/dio_manager'),('libairplay.so','/mnt/app/eso/lib/libairplay.so'),('libNmeSDK.so','/mnt/app/armle/usr/lib/libNmeSDK.so'),('libNmeBaseClasses.so','/mnt/app/armle/usr/lib/libNmeBaseClasses.so'),('libNme.so','/mnt/app/armle/usr/lib/libNme.so'),('cinemo/libNmeTransport.so','/mnt/app/armle/usr/lib/cinemo/libNmeTransport.so')]:
        assert sha(RESOURCE/local)==pinned[local]['sha256']
        c,size=crc(RESOURCE/local)
        line=f'check {c} {size} {target} || fail "native baseline {local}"'
        values['PAYLOAD_CHECKS']+='\n    '+line
        values['RUNTIME_CHECKS']+='\n    '+line
    render('stage3.sh.in','stage3.sh')
    (BASE/'reports/stage3-si.diff').write_text(''.join(difflib.unified_diff(source.splitlines(True),updated.splitlines(True),fromfile='stock/smartphone_integrator.json',tofile='stage3/smartphone_integrator.json')))
    report=dict(scope='one-shot native hook and iAP2 route reception; stock Java retained, no renderer',hook_sha256=sha(hook),original_si_sha256=sha(RESOURCE/'smartphone_integrator.json'),patched_si_sha256=sha(STAGE/'smartphone_integrator.json'),system_dio_unchanged=True,system_si_changes=['children.carplay.exec','children.carplay.path'],upstream_watchdogs_timeouts_cleanup_and_env_preserved=True,files={n:sha(STAGE/n) for n in ['stage3.sh','carplay_startup.sh','mount_state','mount_state.c','libcarplay_hook.so','dio_manager.json','smartphone_integrator.json']},vehicle_tested=False)
    (BASE/'reports/stage3-build.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Stage3 generated: SI child path/exec only; custom dio config on /mnt/app; one-shot hook, no Java.')
if __name__=='__main__':main()
