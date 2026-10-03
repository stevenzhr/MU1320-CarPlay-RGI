#!/usr/bin/env python3
"""Audit Stage2 Java against actual stock APIs with NavActiveIgnore excluded."""
import hashlib,json,zipfile,struct
from pathlib import Path
from formats import ClassFile
BASE=Path(__file__).resolve().parents[1];ROOT=BASE.parent
PRIVATE = BASE.parent / "private-data" / "mu1320-rgi"

def main():
    artifact=BASE/'stage2/carplay_mu1320_stage2.jar.DISABLED'
    build=json.loads((BASE/'reports/stage2-java-build.json').read_text())
    assert hashlib.sha256(artifact.read_bytes()).hexdigest()==build['jar_sha256']
    with zipfile.ZipFile(artifact) as z:built={n[:-6]:ClassFile(z.read(n)) for n in z.namelist() if n.endswith('.class')}
    archives=[p for p in sorted((ROOT/'resource/jars').glob('*.jar')) if p.name!='NavActiveIgnore.jar']
    archives+=[PRIVATE / 'MU1320-base.jar']+sorted((ROOT/'resource/bundles').glob('*.jar'))+sorted((ROOT/'resource/bundles_prod').glob('*.jar'))
    stock={};all_classes=[]
    for p in archives:
        with zipfile.ZipFile(p) as z:
            for n in z.namelist():
                if n.endswith('.class'):
                    data=z.read(n);stock.setdefault(n[:-6],data);all_classes.append((p.name,n[:-6],data))
    cache=dict(built)
    def get(name):
        if name not in cache and name in stock:cache[name]=ClassFile(stock[name])
        return cache.get(name)
    def resolve(owner,name,desc,kind,seen=None):
        seen=set() if seen is None else seen
        if owner is None or owner in seen:return False
        seen.add(owner)
        if owner.startswith('['):return name=='clone'
        c=get(owner)
        if c is None:return False
        if any(m['name']==name and m['descriptor']==desc for m in (c.fields if kind==9 else c.methods)):return True
        if name=='<init>':return False
        return any(resolve(p,name,desc,kind,seen) for p in [c.super,*c.interfaces])
    unresolved=[];count=0
    for caller,c in built.items():
        assert c.major==48
        assert not any(x in caller.lower() for x in ['coverart','cursor','steeringwheelinput'])
        for kind,owner,name,desc in c.refs():
            count+=1
            assert not any(x in owner.lower() for x in ['com/luka/carplay/coverart','com/luka/carplay/cursor','com/luka/carplay/core/steeringwheelinput'])
            if not resolve(owner,name,desc,kind):unresolved.append([caller,owner,name,desc])
    removed=set();shape=[];access_changes=[]
    for n,c in built.items():
        if n not in stock:continue
        old=ClassFile(stock[n])
        if c.super!=old.super or c.interfaces!=old.interfaces:shape.append(n)
        for oldmembers,newmembers in [(old.methods,c.methods),(old.fields,c.fields)]:
            current={(m['name'],m['descriptor']):m for m in newmembers}
            for m in oldmembers:
                match=current.get((m['name'],m['descriptor']))
                if not m['access']&2 and match and (m['access']&0x000d)!=(match['access']&0x000d):access_changes.append([n,m['name'],m['descriptor'],m['access'],match['access']])
                if not m['access']&2 and (m['name'],m['descriptor']) not in current:removed.add((n,m['name'],m['descriptor']))
    broken=[];scanned=0
    for archive,name,data in all_classes:
        if name in built:continue
        scanned+=1
        for _,owner,member,desc in ClassFile(data).refs():
            if (owner,member,desc) in removed:broken.append([archive,name,owner,member,desc])
    app=built['com/luka/carplay/core/CarPlayApp']
    assert all(not owner.startswith(('com/luka/carplay/rgd/','com/luka/carplay/cluster/')) and owner not in ['com/luka/carplay/core/ScreenModule','com/luka/carplay/core/RgdModule'] for _,owner,_,_ in app.refs())
    method=next(m for m in app.methods if m['name']=='isActive');code=method['attributes']['Code'];length=struct.unpack('>I',code[4:8])[0];assert code[8:8+length]==b'\x03\xac'
    report=dict(status='PASS' if not unresolved and not broken and not shape and not access_changes else 'FAIL',classes=len(built),references=count,missing=unresolved,shape_changes=shape,access_changes=access_changes,surviving_classfiles_scanned=scanned,surviving_references_to_removed_members=broken,removed_nonprivate_members=sorted(removed),nav_active_ignore_excluded=True,passive_app_has_no_module_calls=True,is_active_constant_false=True,classfile_major=48,limitations=['Symbol resolution is not J9 runtime, reflection/JNI or full behavioral validation.','Passive build still replaces HMI classes and retains narrow incoming CarPlay NAVI ownership suppression.'])
    (BASE/'reports/stage2-java-audit.json').write_text(json.dumps(report,indent=2)+'\n')
    print(report['status'],len(built),'classes',count,'refs; missing',len(unresolved),'broken survivors',len(broken),'shape',shape)
    return 0 if report['status']=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
