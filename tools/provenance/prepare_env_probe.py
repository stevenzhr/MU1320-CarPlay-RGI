#!/usr/bin/env python3
"""Generate an env-marker-only experiment from the pinned original SI JSON."""
import copy
import difflib
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from formats import config

BASE=Path(__file__).resolve().parents[1]
RESOURCE=BASE.parent/'resource'
STAGE=BASE/'env-probe'
VERSION='v2'
MARKER='mu1320_env_v2_a7f907b7'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def crc(p): return subprocess.check_output(['cksum',str(p)],text=True).split()[:2]

def main():
    STAGE.mkdir(exist_ok=True)
    original=RESOURCE/'smartphone_integrator.json'
    assert sha(original)=='dd7bf2233198eaf26d7fefc0f01f459c1ce291e0d881eb0b9beeb2ecf4d1055d'
    source=original.read_text()
    start=source.index('"carplay":{');end=source.index('"carlife":{',start)
    part=source[start:end]
    needle='"IPL_CONFIG_DIR_DIO_MANAGER=/etc/eso/production"]'
    assert part.count(needle)==1 and 'MU1320_SI_PROBE' not in source
    part=part.replace(needle,'"IPL_CONFIG_DIR_DIO_MANAGER=/etc/eso/production", "MU1320_SI_PROBE='+MARKER+'"]')
    patched=source[:start]+part+source[end:]
    expected=copy.deepcopy(config(source))
    expected['children']['carplay']['envs'].append('MU1320_SI_PROBE='+MARKER)
    assert config(patched)==expected
    (STAGE/'smartphone_integrator.json').write_text(patched)
    (STAGE/'IDENTITY').write_text('MU1320-ENV-ONLY-PROBE-'+VERSION.upper()+'\n')
    build=json.loads((BASE/'reports/stage3-build.json').read_text())
    assert sha(BASE/'stage3/mount_state')==build['files']['mount_state']
    for n in ['mount_state','mount_state.c']: shutil.copyfile(BASE/'stage3'/n,STAGE/n)
    (STAGE/'mount_state').chmod(0o755)
    values={'MARKER':MARKER,'VERSION':VERSION}
    def pin(label,p):
        c,n=crc(p);values[label+'_CRC']=c;values[label+'_SIZE']=n
    for label,p in [('OLD',original),('NEW',STAGE/'smartphone_integrator.json'),('IDENTITY',STAGE/'IDENTITY'),('MOUNT',STAGE/'mount_state')]: pin(label,p)
    def render(template,name):
        content=(BASE/'scripts'/template).read_text()
        for k,v in values.items():content=content.replace('@'+k+'@',v)
        assert not re.search(r'@[A-Z_]+@',content)
        (STAGE/name).write_text(content)
        subprocess.run(['/bin/sh','-n',str(STAGE/name)],check=True)
    render('collect_env.sh.in','collect_env.sh')
    pin('COLLECT',STAGE/'collect_env.sh')
    checks=[]
    for local,target in [('smartphone_integrator','/mnt/app/eso/bin/apps/smartphone_integrator'),('dio_manager','/mnt/app/eso/bin/apps/dio_manager')]:
        c,n=crc(RESOURCE/local)
        checks.append(f'check {c} {n} {target} || fail "{local} baseline"')
    values['NATIVE_CHECKS']='\n    '.join(checks)
    render('env_probe.sh.in','env_probe.sh')
    (BASE/'reports/env-probe-si.diff').write_text(''.join(difflib.unified_diff(source.splitlines(True),patched.splitlines(True),fromfile='stock/smartphone_integrator.json',tofile='env-probe/smartphone_integrator.json')))
    report=dict(version=VERSION,marker='MU1320_SI_PROBE='+MARKER,semantic_changes=['append one children.carplay.envs entry'],
                stock_exec_path_preserved=True,existing_env_preserved=True,hook_included=False,java_included=False,
                renderer_included=False,runtime_tested=False,
                files={n:sha(STAGE/n) for n in ['env_probe.sh','collect_env.sh','mount_state','mount_state.c','smartphone_integrator.json','IDENTITY']})
    (BASE/'reports/env-probe-build.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Env-only trial generated; stock exec/path preserved.')

if __name__=='__main__': main()
