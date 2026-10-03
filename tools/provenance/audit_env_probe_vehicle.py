#!/usr/bin/env python3
"""Audit raw returned environments and identities, not collector verdict strings."""
import hashlib
import json
import re
import subprocess
from pathlib import Path
from formats import config

BASE=Path(__file__).resolve().parents[1]
RESOURCE=BASE.parent/'resource'
DUMP=RESOURCE/'private/vehicle-dump/env-probe-v2-out'
MARKER='MU1320_SI_PROBE=mu1320_env_v2_a7f907b7'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    original=config((RESOURCE/'smartphone_integrator.json').read_text())
    candidate=config((BASE/'env-probe/smartphone_integrator.json').read_text())
    original['children']['carplay']['envs'].append(MARKER)
    assert candidate==original,'candidate has changes beyond the single env marker'
    phases={};inputs={}
    selections={'before':'before-*','marked':'marked-*','restored_initial':'restored-6336654',
                'restored_after_full_boot':'restored-3924110'}
    for phase,pattern in selections.items():
        dirs=list(DUMP.glob(pattern));assert len(dirs)==1
        folder=dirs[0];text=(folder/'collect.txt').read_text()
        wire_phase='restored' if phase.startswith('restored') else phase
        assert f'ENV_PROBE_COLLECT_BEGIN phase={wire_phase}' in text
        assert f'ENV_PROBE_COLLECT_END phase={wire_phase}' in text
        assert f'EXPECTED_MARKER: {MARKER}' in text
        checks={p:[int(c),int(n)] for c,n,p in re.findall(r'^\s*(\d+)\s+(\d+)\s+(/(?:mnt/system/)?etc/eso/production/smartphone_integrator\.json)\s*$',text,re.M)}
        assert len(checks)==2
        roles={}
        for role,name in [('SI','smartphone_integrator'),('DIO','dio_manager')]:
            files=list(folder.glob(role+'-*-environment.txt'));assert len(files)==1
            file=files[0];pid=int(file.name.split('-')[1]);raw=file.read_text()
            block=text.split(f'PROCESS_BEGIN: role={role} pid={pid}\n',1)[1].split('PROCESS_END',1)[0]
            env_match=re.search(r'ENVIRONMENT_BEGIN: exit=(\d+) file=([^\n]+)\n(.*?)ENVIRONMENT_END',block,re.S)
            assert env_match and env_match[1]=='0' and env_match[3]==raw
            row=re.search(r'^\s*'+str(pid)+r'\s+\S+\s+(.+)$',raw,re.M);assert row
            fields=row[1].split();assert any(x.startswith('LD_LIBRARY_PATH=') for x in fields)
            identities=re.findall(r'^\s*'+str(pid)+r'\s+(\d+)\s+(\S*'+name+r')\s+(.+)$',block,re.M)
            assert len(identities)==2 and identities[0]==identities[1]
            ppid,path,started=identities[0]
            table=(folder/'processes.txt').read_text()
            assert re.search(r'^\s*'+str(pid)+r'\s+'+ppid+r'\s+'+re.escape(path)+r'\s*$',table,re.M)
            roles[role]=dict(pid=pid,parent_pid=int(ppid),executable=path,start_time_display=started.strip(),
                             marker_present=MARKER in fields,raw_environment_matches_collect=True,
                             identity_stable_during_collection=True)
        assert roles['DIO']['parent_pid']==roles['SI']['pid']
        phases[phase]=dict(directory=folder.name,date_line=text.splitlines()[3],config_checksums=checks,processes=roles,
            rollback_ram_witness_present='RAM_WITNESS_PRESENT: /tmp/mu1320-env-probe-v2-rollback-witness' in text)
        for p in folder.iterdir():
            if p.is_file():inputs[str(p.relative_to(RESOURCE))]=sha(p)
    assert not phases['before']['processes']['DIO']['marker_present']
    assert phases['marked']['processes']['DIO']['marker_present']
    assert phases['restored_initial']['processes']['DIO']['marker_present']
    assert not phases['restored_after_full_boot']['processes']['DIO']['marker_present']
    assert all(not p['processes']['SI']['marker_present'] for p in phases.values())
    baseline=[535418540,7359]
    c,n=subprocess.check_output(['cksum',str(BASE/'env-probe/smartphone_integrator.json')],text=True).split()[:2]
    assert all(x==baseline for p in ['before','restored_initial','restored_after_full_boot'] for x in phases[p]['config_checksums'].values())
    assert all(x==[int(c),int(n)] for x in phases['marked']['config_checksums'].values())
    for name,action in [('env-probe-install.txt','install'),('env-probe-rollback.txt','rollback')]:
        p=RESOURCE/'private/vehicle-dump'/name
        assert f'ENV_PROBE_{action}_FILES_PASSED' in p.read_text()
        assert 'MOUNTS_RESTORED: app=ro system=ro' in p.read_text()
        inputs[str(p.relative_to(RESOURCE))]=sha(p)
    result=dict(status='ENV_PROPAGATION_AND_RUNTIME_ROLLBACK_VERIFIED',marker=MARKER,
                env_propagation_positive=True,file_rollback_verified=True,runtime_rollback_verified=True,
                hook_loaded=False,phases=phases,input_sha256=inputs,
                inference='The initial restored sample retained the cached marker in a new DIO under the unchanged SI. After a full boot, stock files produced a new SI/DIO without the marker.',
                limitations=['PID/start-time display alone cannot exclude reuse; RAM witness, process table and timing support continuity.',
                             'No SD mount transition log or new on-car script copy was returned; SD remount success is user-reported.',
                             'Local extracted scripts match the shipped v2 ZIP; this does not attest to all on-car edits.',
                             'The initial rollback was reportedly performed with USB connected; this can affect lifecycle timing but does not explain away the new marked DIO under the unchanged SI.',
                             'This validates an ordinary environment item, not LD_PRELOAD, hook interception or VC/HUD.'])
    (BASE/'reports/env-probe-vehicle-v2.json').write_text(json.dumps(result,indent=2)+'\n')
    print(result['status'])
    for phase,p in phases.items():print(phase,'SI',p['processes']['SI']['pid'],'DIO',p['processes']['DIO']['pid'],'marker',p['processes']['DIO']['marker_present'])

if __name__=='__main__':main()
