#!/usr/bin/env python3
"""Create the standalone Stage1 SD archive; excludes all vehicle files and Java candidates."""
import hashlib,json,zipfile
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    stage=BASE/'stage1'
    names=['README.md','run_stage1.sh','transaction.sh','loader_check','loader_check.c','libcarplay_hook.so','mount_state','mount_state.c']
    build=json.loads((BASE/'reports/stage1-build.json').read_text())
    audit=json.loads((BASE/'reports/stage1-audit.json').read_text())
    for n in ['loader_check','libcarplay_hook.so','mount_state']:
        assert sha(stage/n)==build['artifacts'][n]['sha256']==audit['artifacts'][n]['sha256']
        assert audit['artifacts'][n]['status']=='STATIC_PASS'
    for n in names:
        assert (stage/n).is_file() and not (stage/n).is_symlink()
    (stage/'SHA256SUMS').write_text(''.join(f'{sha(stage/n)}  {n}\n' for n in names))
    archive=BASE.parent/'archive/trial-zips/MU1320-RGI-stage1-native-backup-v2.zip'
    if archive.exists():raise SystemExit('Archive exists; refuse overwrite')
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for n in names+['SHA256SUMS']:
            info=zipfile.ZipInfo('mu1320-stage1-v2/'+n,(2026,9,22,0,0,0));info.create_system=3;info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=(0o100755 if n in {'loader_check','mount_state'} else 0o100644)<<16
            z.writestr(info,(stage/n).read_bytes())
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None and len(z.namelist())==9
        for line in z.read('mu1320-stage1-v2/SHA256SUMS').decode().splitlines():
            h,n=line.split('  ',1);assert hashlib.sha256(z.read('mu1320-stage1-v2/'+n)).hexdigest()==h
    report=dict(version=2,path=archive.name,sha256=sha(archive),size=archive.stat().st_size,file_count=9,contains_vehicle_files=False,contains_java_or_renderer=False,navigation_hook_included=True,automatic_install=False,vehicle_runtime_tested=False,archive_crc_and_manifest_verified=True)
    (BASE/'reports/stage1-package.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
if __name__=='__main__':main()
