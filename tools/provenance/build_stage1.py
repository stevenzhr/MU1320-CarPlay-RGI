#!/usr/bin/env python3
"""Build a navigation-only hook and independent loader test in a private copy."""
import hashlib, json, subprocess, shutil
from pathlib import Path
BASE = Path(__file__).resolve().parents[1]
PRIVATE = BASE.parent / "private-data" / "mu1320-rgi"
IMAGE = 'sha256:e52565b1f62dab0f93f12532d52611b94e90b89e4da04f972b11f54eaeb6a05d'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    out = PRIVATE / 'stage1-build'
    if out.exists(): raise SystemExit('Refusing to overwrite prior build')
    for n in ['libcarplay_hook.so', 'loader_check']:
        if (BASE/'stage1'/n).exists(): raise SystemExit('Refusing to overwrite prior artifact')
    pinned = json.loads((BASE/'reports/source-manifest.json').read_text())
    upstream = BASE.parent/'mib2q-carplay-rgi'
    for n,h in pinned['files'].items():
        if sha(upstream/n) != h: raise SystemExit('Changed upstream: '+n)
    version = subprocess.check_output(['docker','run','--rm','--network=none','--platform=linux/amd64',IMAGE,'arm-unknown-nto-qnx6.5.0eabi-gcc','-dumpversion'],text=True).strip()
    if version != '4.9.4': raise SystemExit('Unexpected compiler')
    src = out/'src'; src.mkdir(parents=True)
    for n in pinned['files']:
        if n.startswith('hook/') or n == 'scripts/build_hook.sh':
            dest=src/n;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(upstream/n,dest)
    main=src/'hook/main.c';text=main.read_text()
    for old in ['#include "coverart/coverart_hook.h"\n','    &coverart_module_def,\n']:
        assert text.count(old)==1;text=text.replace(old,'')
    main.write_text(text)
    script=src/'scripts/build_hook.sh';text=script.read_text()
    for old,new in [('IMG=qnx65-armv7-toolchain:latest','IMG='+IMAGE),('docker run --rm ','docker run --rm --network=none '),(' coverart/coverart_hook.c',''),('-Wl,--gc-sections -lz -lsocket','-Wl,--gc-sections -lsocket')]:
        assert text.count(old)==1,(old,text.count(old));text=text.replace(old,new)
    script.write_text(text)
    with (out/'hook-build.log').open('w') as f:
        subprocess.run(['bash',str(script)],stdout=f,stderr=subprocess.STDOUT,check=True)
    shutil.copyfile(BASE/'stage1/loader_check.c',src/'loader_check.c')
    subprocess.run(['docker','run','--rm','--network=none','--platform=linux/amd64','-v',str(src)+':/src',IMAGE,'arm-unknown-nto-qnx6.5.0eabi-gcc','-O2','-std=gnu99','-Wall','-Wextra','-Werror','/src/loader_check.c','-o','/src/build/loader_check'],check=True)
    for n in ['libcarplay_hook.so','loader_check']: shutil.copyfile(src/'build'/n,BASE/'stage1'/n)
    # Keep patch/provenance separate from Java patches applied by build_java_probe.py.
    diff=subprocess.run(['diff','-u',str(upstream/'hook/main.c'),str(main)],capture_output=True,text=True)
    (BASE/'reports/stage1-native-scope.diff').write_text(diff.stdout)
    report=dict(upstream_commit=pinned['commit'],image_id=IMAGE,compiler_version=version,modules=['rgd_module_def'],coverart_source_compiled=False,links_zlib=False,upstream_abi_guards_preserved=True,vehicle_runtime_tested=False,build_script_sha256=sha(Path(__file__)),modified_sources={str(p.relative_to(src)):sha(p) for p in [main,script]},artifacts={n:dict(sha256=sha(BASE/'stage1'/n),size=(BASE/'stage1'/n).stat().st_size) for n in ['libcarplay_hook.so','loader_check']})
    (BASE/'reports/stage1-build.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Stage 1 built; no installation or vehicle execution.')
if __name__=='__main__': main()
