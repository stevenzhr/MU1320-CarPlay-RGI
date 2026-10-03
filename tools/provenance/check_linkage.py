#!/usr/bin/env python3
"""Offline symbolic-link audit against supplied MU1320 classes (not JDK8 APIs)."""
import json
import zipfile
from pathlib import Path
from formats import ClassFile

BASE = Path(__file__).resolve().parents[1]
PRIVATE = BASE.parent / "private-data" / "mu1320-rgi"
ROOT = BASE.parent


def main():
    archives = [*sorted((ROOT/'resource/jars').glob('*.jar')), PRIVATE / 'MU1320-base.jar',
                *sorted((ROOT/'resource/bundles').glob('*.jar')),
                *sorted((ROOT/'resource/bundles_prod').glob('*.jar'))]
    index, providers, opened = {}, {}, []
    for path in archives:
        z = zipfile.ZipFile(path)
        opened.append(z)
        for n in z.namelist():
            if n.endswith('.class'):
                providers.setdefault(n[:-6], []).append(path.name)
                index.setdefault(n[:-6], (z, n))
    classes = PRIVATE / 'java-mu1320/classes'
    built = {str(p.relative_to(classes))[:-6]: ClassFile(p.read_bytes()) for p in classes.rglob('*.class')}
    cache = dict(built)

    def get(name):
        if name not in cache:
            if name not in index: return None
            z, n = index[name]
            cache[name] = ClassFile(z.read(n))
        return cache[name]

    def resolve(owner, name, desc, kind, seen=None):
        seen = set() if seen is None else seen
        if owner in seen or owner is None: return False
        seen.add(owner)
        if owner.startswith('['): return name == 'clone'
        c = get(owner)
        if c is None: return False
        if any(m['name'] == name and m['descriptor'] == desc for m in (c.fields if kind == 9 else c.methods)):
            return True
        if name == '<init>': return False
        return any(resolve(p, name, desc, kind, seen) for p in [c.super, *c.interfaces])

    missing = []
    count = 0
    for caller, c in built.items():
        for kind, owner, name, desc in c.refs():
            count += 1
            if not resolve(owner, name, desc, kind):
                missing.append(dict(caller=caller, owner=owner, name=name, descriptor=desc, kind=kind))
    output = {'scope': 'symbolic member existence including superclass/interfaces, against supplied firmware only',
              'limitations': 'Not J9 loading, access-control, behavioral or native validation; duplicate bundle order not established.',
              'classes': len(built), 'references': count, 'missing': missing,
              'classfile_major_versions': sorted(set(c.major for c in built.values())),
              'external_build_libraries_used_for_resolution': False,
              'referenced_duplicate_providers': {k: v for k, v in providers.items() if len(v) > 1 and k in cache}}
    (BASE/'reports/java-linkage.json').write_text(json.dumps(output, indent=2)+'\n')
    print('Classes:', len(built), 'member references:', count, 'unresolved:', len(missing))
    for z in opened: z.close()
    return 1 if missing else 0


if __name__ == '__main__': raise SystemExit(main())
