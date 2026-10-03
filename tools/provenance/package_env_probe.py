#!/usr/bin/env python3
"""Validate the marker-only delta, test the scripts, then make an immutable ZIP."""
import copy
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path
from audit_native import inspect
from audit_native_probe import check_binary
from formats import config

BASE=Path(__file__).resolve().parents[1]
RESOURCE=BASE.parent/'resource'
STAGE=BASE/'env-probe'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    version=json.loads((BASE/'reports/env-probe-build.json').read_text())['version']
    folder='mu1320-env-probe-'+version
    archive=BASE.parent/'archive/trial-zips'/('MU1320-RGI-si-env-probe-'+version+'.zip')
    assert not archive.exists(),'Do not overwrite a shipped ZIP'
    build=json.loads((BASE/'reports/env-probe-build.json').read_text())
    for n,digest in build['files'].items():assert sha(STAGE/n)==digest,n
    before=config((RESOURCE/'smartphone_integrator.json').read_text())
    after=config((STAGE/'smartphone_integrator.json').read_text())
    expected=copy.deepcopy(before)
    expected['children']['carplay']['envs'].append(build['marker'])
    assert after==expected
    assert before['children']['carplay']['exec']=='dio_manager'
    assert before['children']['carplay']['path']=='/mnt/app/eso/bin/apps'
    inventory={str(p.relative_to(RESOURCE)):inspect(p) for p in (RESOURCE/'native-libs').rglob('*.so*') if p.is_file()}
    helper=check_binary(STAGE/'mount_state',inventory)
    assert helper['status']=='STATIC_PASS',helper
    for name in ['env_probe.sh','collect_env.sh']:
        subprocess.run(['/bin/sh','-n',str(STAGE/name)],check=True)
    result=subprocess.run(['python3','-m','unittest','discover','-s',str(BASE/'tests'),'-p','test_env_probe.py','-v'],capture_output=True,text=True)
    (BASE/'reports/env-probe-host-tests.txt').write_text(result.stdout+result.stderr)
    assert result.returncode==0,result.stdout+result.stderr
    names=['README.md','env_probe.sh','collect_env.sh','mount_state','mount_state.c','smartphone_integrator.json','IDENTITY']
    (STAGE/'SHA256SUMS').write_text(''.join(f'{sha(STAGE/n)}  {n}\n' for n in names))
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
        for n in names+['SHA256SUMS']:
            entry=zipfile.ZipInfo(folder+'/'+n,(2026,9,23,0,0,0))
            entry.create_system=3;entry.compress_type=zipfile.ZIP_DEFLATED
            entry.external_attr=(0o100755 if n=='mount_state' else 0o100644)<<16
            z.writestr(entry,(STAGE/n).read_bytes())
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        for n in names+['SHA256SUMS']:assert z.read(folder+'/'+n)==(STAGE/n).read_bytes()
    report=dict(package=archive.name,sha256=sha(archive),size=archive.stat().st_size,
                marker=build['marker'],semantic_changes=build['semantic_changes'],host_tests='PASS',
                host_test_log_sha256=sha(BASE/'reports/env-probe-host-tests.txt'),mount_helper_audit=helper,
                vehicle_tested=False,installs_hook=False,changes_exec_path=False,
                files={n:sha(STAGE/n) for n in names+['SHA256SUMS']})
    (BASE/'reports/env-probe-package.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ['package','sha256','size','host_tests','vehicle_tested']},indent=2))

if __name__=='__main__': main()
