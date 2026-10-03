#!/usr/bin/env python3
"""Compile upstream against MU1320, never turn this probe into an installable JAR."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
PRIVATE = BASE.parent / "private-data" / "mu1320-rgi"
ROOT = BASE.parent


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--stock', type=Path, default=PRIVATE / 'MU1320-base.jar')
    p.add_argument('--javac', type=Path, default=PRIVATE / 'tools/jxe2jar/jvms/zulu8.78.0.19-ca-jdk8.0.412-macosx_aarch64/zulu-8.jdk/Contents/Home/bin/javac')
    p.add_argument('--mu1320', action='store_true', help='apply the reviewed MU1320 resource API patch')
    a = p.parse_args()
    if not a.stock.is_file() or not a.javac.is_file():
        p.error('requires converted MU1320 stock JAR and JDK8 javac')
    pinned = json.loads((BASE/'reports/source-manifest.json').read_text())
    for name, digest in pinned['files'].items():
        if hashlib.sha256((ROOT/'mib2q-carplay-rgi'/name).read_bytes()).hexdigest() != digest:
            p.error('source differs from audited baseline: ' + name)
    # Exclude installed patches from the reference boot API. They are audited separately.
    stock = zipfile.ZipFile(a.stock)
    assert 'java/lang/Object.class' in stock.namelist()
    assert 'java/lang/StringBuilder.class' not in stock.namelist()
    probe = PRIVATE / ('java-mu1320' if a.mu1320 else 'java-probe')
    if probe.exists():
        p.error('probe output already exists; archive it before rerunning (no destructive overwrite)')
    classes = probe/'classes'
    classes.mkdir(parents=True)
    source = probe/'src'
    shutil.copytree(ROOT/'mib2q-carplay-rgi/java_patch', source)
    app = source/'com/luka/carplay/core/CarPlayApp.java'
    app.write_text(app.read_text().replace('@BUILD_ID@', 'MU1320-PROBE-NOT-FOR-INSTALL'))
    if a.mu1320:
        for patch in sorted((BASE/'patches').glob('*.patch')):
            subprocess.run(['patch', '-F', '0', '-p1', '-i', str(patch)], cwd=source, check=True)
    cp = [str(a.stock.resolve())]
    for folder in ['bundles', 'bundles_prod']:
        cp += [str(x.resolve()) for x in sorted((ROOT/'resource'/folder).glob('*.jar'))]
    libs = PRIVATE / 'tools/jxe2jar/libs'
    cp += [str(x.resolve()) for x in sorted(libs.glob('org.osgi.*.jar'))]
    sources = sorted(source.rglob('*.java'))
    cmd = [str(a.javac), '-source', '1.4', '-target', '1.4', '-Xlint:-options',
           '-bootclasspath', str(a.stock.resolve()), '-classpath', os.pathsep.join(cp),
           '-sourcepath', str(source), '-d', str(classes), '-Xmaxerrs', '300'] + [str(x) for x in sources]
    run = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    label = 'java-mu1320' if a.mu1320 else 'java'
    (BASE/('reports/'+label+'-compile.log')).write_text(run.stdout)
    report = {'deployable': False, 'purpose': 'compile probe; ABI audit and runtime validation still required',
              'stock_sha256': hashlib.sha256(a.stock.read_bytes()).hexdigest(),
              'source_count': len(sources), 'exit_code': run.returncode,
              'strict_MU1320_bootclasspath': True, 'command': cmd}
    (BASE/('reports/'+label+'-build.json')).write_text(json.dumps(report, indent=2)+'\n')
    if a.mu1320 and run.returncode == 0:
        # Deliberately outside jars/, and not named *.jar or *.zip: lsd.sh scans recursively.
        jar = BASE/'candidate/carplay_hook-mu1320.jar.DISABLED'
        with zipfile.ZipFile(jar, 'w', zipfile.ZIP_DEFLATED) as z:
            for c in sorted(classes.rglob('*.class')):
                info = zipfile.ZipInfo(str(c.relative_to(classes)), (2026, 9, 22, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                z.writestr(info, c.read_bytes())
        print('EXPERIMENTAL DISABLED archive:', jar)
    print(run.stdout[-14000:])
    print('Probe exit:', run.returncode, '; NOT a release build.')
    return run.returncode


if __name__ == '__main__': raise SystemExit(main())
