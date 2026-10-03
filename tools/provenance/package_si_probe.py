#!/usr/bin/env python3
"""Audit and package an isolated reader; never overwrite a shipped ZIP."""
import hashlib
import json
import re
import subprocess
import zipfile
from pathlib import Path
from audit_native import inspect
from audit_native_probe import check_binary

BASE = Path(__file__).resolve().parents[1]
RESOURCE = BASE.parent/'resource'
STAGE = BASE/'si-probe'

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    inventory = {str(p.relative_to(RESOURCE)): inspect(p)
                 for p in (RESOURCE/'native-libs').rglob('*.so*') if p.is_file()}
    audit = check_binary(STAGE/'config_probe', inventory)
    assert audit['status'] == 'STATIC_PASS', audit
    util = inventory['native-libs/mnt/app/eso/lib/libutil.so']
    assert util['sha256'] == '6abb2442f29927b2dc5c799afca266ef4f0e6bdb70d9668a271e64eb967df831'
    source = (STAGE/'config_probe.c').read_text()
    symbols = re.findall(r'sym\(lib, "([^"]+)"\)', source)
    assert len(symbols) == 5
    assert all(s in util['exports'] for s in symbols)
    assert 'exec' not in audit['required_symbols']
    assert not any(s.startswith(('spawn','exec','kill','mount')) for s in audit['required_symbols'])
    script = (STAGE/'run_probe.sh').read_text()
    for name in ['config_probe','stage3-candidate.json']:
        c,n = subprocess.check_output(['cksum',str(STAGE/name)],text=True).split()[:2]
        assert f'check {c} {n} "$src/{name}"' in script
    subprocess.run(['/bin/sh','-n',str(STAGE/'run_probe.sh')],check=True)
    report = dict(runtime_tested=False, purpose='isolated JSON parser diagnosis; not installation',
                  image='sha256:e52565b1f62dab0f93f12532d52611b94e90b89e4da04f972b11f54eaeb6a05d',
                  compiler='arm-unknown-nto-qnx6.5.0eabi-gcc 4.9.4',
                  compiler_flags='-O2 -std=gnu99 -Wall -Wextra -Werror',
                  abi_exports={s:util['exports'][s] for s in symbols},elf_audit=audit)
    report['files']={p.name:sha(p) for p in sorted(STAGE.iterdir()) if p.is_file() and p.name!='SHA256SUMS'}
    (STAGE/'SHA256SUMS').write_text(''.join(f'{digest}  {name}\n' for name,digest in report['files'].items()))
    out = BASE.parent/'archive/trial-zips/MU1320-RGI-si-config-probe-v1.zip'
    with zipfile.ZipFile(out,'x',zipfile.ZIP_DEFLATED) as archive:
        for p in sorted(STAGE.iterdir()):
            if p.is_file(): archive.write(p,'mu1320-si-config-probe-v1/'+p.name)
    report['package'] = dict(name=out.name,size=out.stat().st_size,sha256=sha(out))
    (BASE/'reports/si-probe-package.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report['package'],indent=2))

if __name__ == '__main__':
    main()
