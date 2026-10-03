#!/usr/bin/env python3
import hashlib,json,zipfile
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    stage=BASE/'stage3'
    assert json.loads((BASE/'reports/stage3-audit.json').read_text())['status']=='STATIC_PASS'
    assert json.loads((BASE/'reports/current-validation.json').read_text())['stage3_host_tests']=='PASS'
    build=json.loads((BASE/'reports/stage3-build.json').read_text())
    for n,h in build['files'].items():assert sha(stage/n)==h
    names=['README.md','stage3.sh','carplay_startup.sh','mount_state','mount_state.c','libcarplay_hook.so','dio_manager.json','smartphone_integrator.json','IDENTITY']
    (stage/'SHA256SUMS').write_text(''.join(f'{sha(stage/n)}  {n}\n' for n in names))
    archive=BASE.parent/'archive/trial-zips/MU1320-RGI-stage3-native-oneshot-v1.zip'
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for n in names+['SHA256SUMS']:
            info=zipfile.ZipInfo('mu1320-stage3-v1/'+n,(2026,9,23,0,0,0));info.create_system=3;info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=(0o100755 if n in ['mount_state','carplay_startup.sh'] else 0o100644)<<16
            z.writestr(info,(stage/n).read_bytes())
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        for n in names+['SHA256SUMS']:assert z.read('mu1320-stage3-v1/'+n)==(stage/n).read_bytes()
    report=dict(path=archive.name,sha256=sha(archive),size=archive.stat().st_size,files=len(names)+1,version=1,actual_interposition_vehicle_tested=False,java_included=False,renderer_included=False,default_stock_until_one_shot_arm=True)
    (BASE/'reports/stage3-package.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
if __name__=='__main__':main()
