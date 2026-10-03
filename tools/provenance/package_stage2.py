#!/usr/bin/env python3
"""Package the scoped Java trial, never overwrite an issued archive."""
import hashlib,json,zipfile,subprocess
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    stage=BASE/'stage2'
    audit=json.loads((BASE/'reports/stage2-java-audit.json').read_text())
    validation=json.loads((BASE/'reports/current-validation.json').read_text())
    assert audit['status']=='PASS' and validation['stage2_install_rollback_host_tests']=='PASS'
    subprocess.run(['/bin/sh','-n',str(stage/'stage2.sh')],check=True)
    assert sha(stage/'carplay_mu1320_stage2.jar.DISABLED')==json.loads((BASE/'reports/stage2-java-build.json').read_text())['jar_sha256']
    assert (stage/'stage2.sh').read_text().count('LD_DEBUG_OUTPUT=')==0
    assert 'chown 0:0' not in (stage/'stage2.sh').read_text()
    assert 'WORK=/mnt/app/root/mu1320-rgi-stage2-v2' in (stage/'stage2.sh').read_text()
    assert (stage/'IDENTITY').read_text()=='MU1320-STAGE2-PASSIVE-V2\n'
    names=['README.md','stage2.sh','carplay_mu1320_stage2.jar.DISABLED','mount_state','mount_state.c','IDENTITY']
    (stage/'SHA256SUMS').write_text(''.join(f'{sha(stage/n)}  {n}\n' for n in names))
    archive=BASE.parent/'archive/trial-zips/MU1320-RGI-stage2-java-passive-v2.zip'
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for n in names+['SHA256SUMS']:
            info=zipfile.ZipInfo('mu1320-stage2-v2/'+n,(2026,9,23,0,0,0));info.create_system=3;info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=(0o100755 if n=='mount_state' else 0o100644)<<16
            z.writestr(info,(stage/n).read_bytes())
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        for n in names:assert z.read('mu1320-stage2-v2/'+n)==(stage/n).read_bytes()
    report=dict(version=2,path=archive.name,sha256=sha(archive),size=archive.stat().st_size,file_count=len(names)+1,scope='passive Java/HMI trial; native hook and navigation modules disabled',java_vehicle_tested=False,archive_verified=True,automatic_restart=False,chown_dependency=False,v1_status_result='STOP before any write: missing chown')
    (BASE/'reports/stage2-package.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
