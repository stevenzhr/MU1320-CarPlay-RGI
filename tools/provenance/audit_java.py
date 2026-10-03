#!/usr/bin/env python3
"""Inventory MU1320 override APIs and installed patch conflicts."""
import hashlib
import json
import zipfile
from pathlib import Path
from formats import ClassFile

BASE = Path(__file__).resolve().parents[1]
PRIVATE = BASE.parent / "private-data" / "mu1320-rgi"
ROOT = BASE.parent


def main():
    stock = zipfile.ZipFile(PRIVATE / 'MU1320-base.jar')
    prefixes = [str(p.relative_to(ROOT/'mib2q-carplay-rgi/java_patch')).removesuffix('.java')
                for p in (ROOT/'mib2q-carplay-rgi/java_patch/de').rglob('*.java')]
    names = sorted(n for n in stock.namelist() if n.endswith('.class') and
                   any(n == p+'.class' or n.startswith(p+'$') for p in prefixes))
    stock_api = {n: ClassFile(stock.read(n)).api() for n in names}
    additional = ['de/audi/atip/interapp/combi/bap/navi/CombiBAPServiceNavi.class',
                  'org/dsi/ifc/carplay/AppState.class',
                  'de/audi/app/terminalmode/smartphone/androidauto2/nav/AndroidAuto2NavHandler.class']
    for n in additional:
        if n in stock.namelist(): stock_api[n] = ClassFile(stock.read(n)).api()
    (BASE/'reports/java-stock-api.json').write_text(json.dumps(stock_api, indent=2)+'\n')
    jar_inventory, patch_details = {}, {}
    for p in sorted((ROOT/'resource/jars').glob('*.jar')):
        with zipfile.ZipFile(p) as z:
            cs = [n for n in z.namelist() if n.endswith('.class')]
            jar_inventory[p.name] = {'sha256': hashlib.sha256(p.read_bytes()).hexdigest(),
                                     'class_count': len(cs),
                                     'overlaps_upstream_override': sorted(set(cs) & set(names))}
            if p.name == 'NavActiveIgnore.jar':
                for n in cs:
                    cf = ClassFile(z.read(n))
                    patch_details[n] = {'api': cf.api(), 'references': cf.refs(),
                                        'differs_from_stock': n not in stock.namelist() or z.read(n) != stock.read(n)}
    output = {'stock_class_count': len([n for n in stock.namelist() if n.endswith('.class')]),
              'override_family_class_count': len(names), 'installed_jars': jar_inventory,
              'NavActiveIgnore': patch_details, 'source_only_cannot_prove_abi': True}
    classes = PRIVATE / 'java-mu1320/classes'
    abi = []
    for p in sorted(classes.rglob('*.class')):
        n = str(p.relative_to(classes))
        if n not in stock.namelist(): continue
        old, new = ClassFile(stock.read(n)), ClassFile(p.read_bytes())
        missing, changed = [], []
        for kind in ['fields', 'methods']:
            new_map = {(m['name'], m['descriptor']): m for m in getattr(new, kind)}
            for m in getattr(old, kind):
                # All nonprivate members, including package access and synthetic accessors.
                if m['access'] & 2 or m['name'] == '<clinit>': continue
                key = (m['name'], m['descriptor'])
                if key not in new_map: missing.append({'kind': kind, 'name': key[0], 'descriptor': key[1]})
                elif (m['access'] & 0x000d) != (new_map[key]['access'] & 0x000d):
                    changed.append({'kind': kind, 'name': key[0], 'descriptor': key[1],
                                    'old': m['access'], 'new': new_map[key]['access']})
        abi.append({'class': n, 'missing_nonprivate_members': missing, 'changed_access_static': changed,
                    'super_changed': old.super != new.super, 'interfaces_changed': old.interfaces != new.interfaces})
    output['compiled_override_ABI'] = abi
    # Synthetic accessor renumbering is not itself a break if every caller is replaced.
    # Scan the surviving MU1320 JXE and installed bundles/JARs for references to removed members.
    removed = set()
    for item in abi:
        owner = item['class'].removesuffix('.class')
        for m in item['missing_nonprivate_members']:
            removed.add((owner, m['name'], m['descriptor']))
    replacements = {str(p.relative_to(classes)) for p in classes.rglob('*.class')}
    broken, scanned = [], 0
    inputs = [PRIVATE / 'MU1320-base.jar']
    inputs += [p for folder in ['jars', 'bundles', 'bundles_prod'] for p in sorted((ROOT/'resource'/folder).glob('*.jar'))]
    for archive in inputs:
        with zipfile.ZipFile(archive) as z:
            for name in z.namelist():
                if not name.endswith('.class') or name in replacements: continue
                cf = ClassFile(z.read(name))
                scanned += 1
                for kind, owner, member, desc in cf.refs():
                    if (owner, member, desc) in removed:
                        broken.append({'archive': archive.name, 'caller': name, 'owner': owner,
                                       'member': member, 'descriptor': desc})
    output['surviving_classfiles_scanned'] = scanned
    output['surviving_references_to_removed_members'] = broken
    output['closure_limitations'] = 'Direct symbolic references only; reflection, inherited dispatch, native JNI and behavior still require review.'
    (BASE/'reports/java-audit.json').write_text(json.dumps(output, indent=2)+'\n')
    print('Stock classes:', output['stock_class_count'], 'override family:', len(names))
    print('Installed overlap:', {k: v['overlaps_upstream_override'] for k, v in jar_inventory.items() if v['overlaps_upstream_override']})
    print('ABI exceptions:', len([x for x in abi if x['missing_nonprivate_members'] or x['changed_access_static'] or x['super_changed'] or x['interfaces_changed']]))
    print('Surviving classfiles:', scanned, 'references to removed members:', len(broken))


if __name__ == '__main__': main()
