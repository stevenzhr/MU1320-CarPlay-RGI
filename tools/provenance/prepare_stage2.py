#!/usr/bin/env python3
import hashlib,json,subprocess
from pathlib import Path
BASE=Path(__file__).resolve().parents[1];RESOURCE=BASE.parent/'resource'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def crc(p):return subprocess.check_output(['cksum',str(p)],text=True).split()[:2]
def main():
    assert json.loads((BASE/'reports/stage2-java-audit.json').read_text())['status']=='PASS'
    assert json.loads((BASE/'reports/stage1-vehicle-v2.json').read_text())['status']=='PASS'
    build=json.loads((BASE/'reports/stage2-java-build.json').read_text())
    payload=BASE/'stage2/carplay_mu1320_stage2.jar.DISABLED';assert sha(payload)==build['jar_sha256']
    assert sha(BASE/'stage2/mount_state')==sha(BASE/'stage1/mount_state')
    values={}
    for name,p in [('OLD',RESOURCE/'jars/NavActiveIgnore.jar'),('NEW',payload),('MOUNT',BASE/'stage2/mount_state')]:
        c,n=crc(p);values[name+'_CRC']=c;values[name+'_SIZE']=n
    identity=BASE/'stage2/IDENTITY';identity.write_text('MU1320-STAGE2-PASSIVE-V2\n');c,n=crc(identity);values.update(IDENTITY_CRC=c,IDENTITY_SIZE=n)
    pinned={}
    for name in ['input-manifest.json','supplement-manifest.json']:pinned.update(json.loads((BASE/'reports'/name).read_text())['files'])
    checks=[];cases=[]
    for p in sorted((RESOURCE/'jars').iterdir()):
        assert p.suffix in ['.jar','.zip'] and sha(p)==pinned['jars/'+p.name]['sha256']
        c,n=crc(p);path='/mnt/app/eso/hmi/lsd/jars/'+p.name
        checks.append(f'check_file {c} {n} {path} || fail "baseline archive differs: {p.name}"')
        cases.append(f'            "$JARS/{p.name}") check_file {c} {n} "$archive" || fail "archive changed" ;;')
    baseline=[('lsd.sh','/mnt/app/eso/hmi/lsd/lsd.sh'),('dio_manager.json','/etc/eso/production/dio_manager.json'),('dio_manager.json','/mnt/system/etc/eso/production/dio_manager.json'),('smartphone_integrator.json','/etc/eso/production/smartphone_integrator.json'),('smartphone_integrator.json','/mnt/system/etc/eso/production/smartphone_integrator.json')]
    for local,path in baseline:
        assert sha(RESOURCE/local)==pinned[local]['sha256'];c,n=crc(RESOURCE/local)
        checks.append(f'check_file {c} {n} {path} || fail "baseline differs: {path}"')
    text=(BASE/'scripts/stage2.sh.in').read_text()
    values['BASELINE_CHECKS']='\n    '.join(checks);values['ARCHIVE_CASES']='\n'.join(cases)
    for key,value in values.items():assert '@'+key+'@' in text;text=text.replace('@'+key+'@',value)
    assert '@' not in text.replace('"$@"','')
    (BASE/'stage2/stage2.sh').write_text(text)
    print('Stage2 installer generated; archive inventory pinned; rollback leaves JSON untouched.')
if __name__=='__main__':main()
