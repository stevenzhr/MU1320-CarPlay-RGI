#!/usr/bin/env python3
import hashlib,zipfile,subprocess
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    source=BASE/'preflight/stage3_diagnose_readonly.sh';readme=BASE/'preflight/STAGE3-DIAGNOSE.md'
    subprocess.run(['/bin/sh','-n',str(source)],check=True)
    names=[('README.md',readme),('stage3_diagnose_readonly.sh',source)]
    manifest=''.join(f'{sha(p)}  {name}\n' for name,p in names)
    archive=BASE.parent/'archive/trial-zips/MU1320-RGI-stage3-diagnose-readonly-v1.zip'
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for name,path in names:
            info=zipfile.ZipInfo('mu1320-stage3-diagnose-v1/'+name,(2026,9,23,0,0,0));info.create_system=3;info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16;z.writestr(info,path.read_bytes())
        info=zipfile.ZipInfo('mu1320-stage3-diagnose-v1/SHA256SUMS',(2026,9,23,0,0,0));info.create_system=3;info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16;z.writestr(info,manifest)
    with zipfile.ZipFile(archive) as z:assert z.testzip() is None
    print(archive.name,sha(archive),archive.stat().st_size)
if __name__=='__main__':main()
