#!/usr/bin/env python3
"""Validate returned Stage1 log, selected backups and recorded vehicle attributes."""
import hashlib,json,subprocess
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
RESOURCE=BASE.parent/'resource'
DUMP=RESOURCE/'private/vehicle-dump'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    log=DUMP/'stage1-v2.txt';text=log.read_text()
    markers=['stage1_loader_exit=0','MOUNT_INITIAL: /mnt/app ro','MOUNT_WORKING: /mnt/app rw','BASELINE_BACKUP_COMPLETE:','REHEARSAL_RESTORED','MOUNT_RESTORED: /mnt/app ro','STAGE1_V2_PASSED: prepare complete; original mount state verified','stage1_exit=0']
    positions=[text.index(m) for m in markers]
    assert positions==sorted(positions) and 'STOP:' not in text and 'FAIL:' not in text
    root=DUMP/'stage1-backup/mu1320-rgi-stage1-v2';backup=root/'backup'
    assert (root/'IDENTITY').read_text().strip()=='MU1320-STAGE1-V2-BACKUP-AND-REHEARSAL'
    assert (backup/'COMPLETE').read_text().strip()=='BASELINE_BACKUP_COMPLETE'
    mappings={
        'etc-dio.json':('dio_manager.json','/etc/eso/production/dio_manager.json'),
        'system-dio.json':('dio_manager.json','/mnt/system/etc/eso/production/dio_manager.json'),
        'etc-si.json':('smartphone_integrator.json','/etc/eso/production/smartphone_integrator.json'),
        'system-si.json':('smartphone_integrator.json','/mnt/system/etc/eso/production/smartphone_integrator.json'),
        'carplay_cleanup.sh':('carplay_cleanup.sh','/etc/scripts/carplay_cleanup.sh'),
        'lsd.sh':('lsd.sh','/mnt/app/eso/hmi/lsd/lsd.sh'),
        'NavActiveIgnore.jar':('jars/NavActiveIgnore.jar','/mnt/app/eso/hmi/lsd/jars/NavActiveIgnore.jar')}
    pinned={}
    for n in ['input-manifest.json','supplement-manifest.json']:pinned.update(json.loads((BASE/'reports'/n).read_text())['files'])
    attrs={}
    for line in (backup/'attributes.txt').read_text().splitlines():
        fields=line.split();assert len(fields)==9,line
        assert fields[-1] not in attrs
        attrs[fields[-1]]=dict(mode=fields[0],uid=int(fields[2]),gid=int(fields[3]),size=int(fields[4]),displayed_timestamp=' '.join(fields[5:8]))
    result={}
    for line in (backup/'index.txt').read_text().splitlines():
        crc,size,name,source=line.split();assert name in mappings and name not in result
        local,target=mappings[name];assert source==target
        p=backup/name;assert not p.is_symlink() and p.is_file()
        actual=subprocess.check_output(['cksum',str(p)],text=True).split()[:2]
        assert actual==[crc,size]
        assert sha(p)==sha(RESOURCE/local)==pinned[local]['sha256']
        backup_target='/mnt/app/root/mu1320-rgi-stage1-v2/backup/'+name
        assert attrs[source]==attrs[backup_target]
        assert attrs[source]['size']==int(size)
        result[name]=dict(sha256=sha(p),size=int(size),matches_original_baseline=True,vehicle_recorded_attributes=attrs[source])
    assert set(result)==set(mappings) and len(attrs)==14
    assert (root/'rehearsal/live/item').read_bytes()==(root/'rehearsal/baseline/item').read_bytes()==b'MU1320 rehearsal original\n'
    assert (root/'rehearsal/candidate').read_bytes()==b'MU1320 rehearsal candidate\n'
    report=dict(status='PASS',variant='v2 with user-tested run_clean correction; original v2 ZIP is not the tested wrapper',log_sha256=sha(log),reviewed_wrapper_sha256=sha(BASE/'stage1/run_stage1.sh'),input_sha256={str(p.relative_to(DUMP)):sha(p) for p in sorted(root.rglob('*')) if p.is_file()},backup_files=result,stage1_exit=0,standalone_loader_passed=True,backup_verified=True,isolated_rehearsal_restored=True,mount_transition=['ro','rw','ro'],hmi_recovery_tested=False,actual_interposition_java_renderer_tested=False,limitations=['Vehicle attributes come from the captured ls record and runtime checks, not host filesystem ownership.','Distinct directory inodes do not establish configuration alias/write propagation.','Original v2 archive contains the previous loader-environment bug; retain the corrected local wrapper.'])
    (BASE/'reports/stage1-vehicle-v2.json').write_text(json.dumps(report,indent=2)+'\n')
    print('PASS: ordered completion log, 7 baseline SHA256/CRC matches, 7 attribute pairs, restored rehearsal, ro->rw->ro')
if __name__=='__main__':main()
