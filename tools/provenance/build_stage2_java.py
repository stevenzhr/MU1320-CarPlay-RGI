#!/usr/bin/env python3
"""Build a passive navigation-scoped Java trial; never installs on a vehicle."""
import hashlib,json,os,re,shutil,subprocess,zipfile,difflib
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
PRIVATE = BASE.parent / "private-data" / "mu1320-rgi"
ROOT=BASE.parent

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def span(text,signature):
    assert text.count(signature)==1,(signature,text.count(signature))
    start=text.index(signature);brace=text.index('{',start);depth=0
    # Ignore braces inside Java strings/comments.
    tokens=re.finditer(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|//[^\n]*|/\*[\s\S]*?\*/|[{}]',text[brace:])
    for m in tokens:
        if m.group()=='{':depth+=1
        elif m.group()=='}':
            depth-=1
            if depth==0:return start,brace,brace+m.end()
    raise ValueError('unterminated block')
def replace_block(s,signature,new):
    a,_,end=span(s,signature);return s[:a]+new+s[end:]
def main():
    out=PRIVATE / 'stage2-java';assert not out.exists(),'preserve existing build'
    dest=BASE/'stage2/carplay_mu1320_stage2.jar.DISABLED';assert not dest.exists()
    pinned=json.loads((BASE/'reports/source-manifest.json').read_text())
    upstream=ROOT/'mib2q-carplay-rgi'
    for name,h in pinned['files'].items():assert sha(upstream/name)==h,name
    src=out/'src';shutil.copytree(upstream/'java_patch',src);classes=out/'classes';classes.mkdir()
    for name in ['0001-mu1320-resource-api.patch','0002-preserve-mu1320-context34.patch']:
        subprocess.run(['patch','-F','0','-p1','-i',str(BASE/'patches'/name)],cwd=src,check=True,capture_output=True)
    removed=['com/luka/carplay/coverart/CoverArt.java','com/luka/carplay/cursor/CursorController.java','com/luka/carplay/core/SteeringWheelInputModule.java',
      'de/audi/app/combi/bap/app/audio/AppConnectorTerminalMode.java','de/audi/app/combi/bap/app/audio/AppConnectorTerminalMode$CoverArtProvider.java','de/audi/app/combi/bap/app/audio/CoverArtProviderMux.java']
    for name in removed:(src/name).unlink()
    shutil.copyfile(BASE/'stage2-src/CarPlayApp.java',src/'com/luka/carplay/core/CarPlayApp.java')
    p=src/'de/audi/app/terminalmode/combi/TerminalModeBapCombi.java';s=p.read_text()
    for line in ['        try { com.luka.carplay.coverart.CoverArt.getInstance().start(this.eventListener); }\n        catch (Throwable t) { /* optional */ }\n','        try { com.luka.carplay.coverart.CoverArt.getInstance().stop(this.eventListener); }\n        catch (Throwable t) { /* optional */ }\n']:
        assert line in s;s=s.replace(line,'')
    s=re.sub(r'^.*(?:CoverArt.getInstance\(\).resetSession|eventListener.resetCoverMerge).*\n','',s,flags=re.M)
    stock=PRIVATE / 'stage2-stock-review/src/de/audi/app/terminalmode/combi/TerminalModeBapCombi.java'
    stock_text=stock.read_text();a,_,e=span(stock_text,'private class EventListener')
    s=replace_block(s,'private class EventListener',stock_text[a:e]);assert 'CoverArt' not in s;p.write_text(s)
    p=src/'de/audi/app/terminalmode/dsi/carplay/CarplayDSILifecycleController.java';s=p.read_text()
    for line in ['import com.luka.carplay.cursor.CursorController;\n','import com.luka.carplay.core.SteeringWheelInputModule;\n']:
        assert line in s;s=s.replace(line,'')
    s=s.replace('        /* The same component object can be deinit/init\'d; deinit clears the singleton sink. */\n        ((CarplayDSILifecycleController.TerminalModeDSIKeyEventsController)this.keyEventController)\n            .installCursorTouchSink();\n','')
    s=re.sub(r'        /\* Remove the touch sink[\s\S]*?CursorController.getInstance\(\).setTouchSink\(null\);\n','',s,count=1)
    s=s.replace('            installCursorTouchSink();   /* CarPlay: touchpad -> DPAD ticks via CursorController */\n','')
    s=replace_block(s,'private void installCursorTouchSink()', '')
    a=s.index('            /* Raw key 40');e=s.index('            /* Central-console',a);s=s[:a]+s[e:]
    s=replace_block(s,'public void updateTouchEvents(','''public void updateTouchEvents(de.audi.app.terminalmode.keyevents.TouchEvent[] events) {
            // MU1320 stock semantics: preserve input ID, coordinates, active count and X ordering.
            if (events == null || events.length == 0) return;
            ArrayList points = new ArrayList(events.length);
            int active = 0;
            for (int i = 0; i < events.length; i++) {
                int x = events[i].getCurrentX();
                int y = events[i].getCurrentY();
                if (events[i].isTouchScreen()) {
                    x -= this.this$0.configuration.getScreenOffsetX();
                    y -= this.this$0.configuration.getScreenOffsetY();
                }
                points.add(new TouchEvent(x, y));
                if (events[i].getTouchState() != 1) active++;
            }
            Collections.sort(points, new TouchXComparator());
            this.this$0.dsiCarplaySafe.postTouchEvent(events[0].isTouchScreen() ? 1 : 0,
                active, (TouchEvent[])points.toArray(new TouchEvent[points.size()]));
        }''')
    # Remaining mentions in comments do not correspond to code; reject actual references.
    assert not re.search(r'(?:CursorController|SteeringWheelInputModule)\s*[.;(]',s)
    p.write_text(s)
    stockjar=PRIVATE / 'MU1320-base.jar'
    assert sha(stockjar)==json.loads((BASE/'reports/java-mu1320-build.json').read_text())['stock_sha256']
    javac=PRIVATE / 'tools/jxe2jar/jvms/zulu8.78.0.19-ca-jdk8.0.412-macosx_aarch64/zulu-8.jdk/Contents/Home/bin/javac'
    cp=[stockjar]+sorted((ROOT/'resource/bundles').glob('*.jar'))+sorted((ROOT/'resource/bundles_prod').glob('*.jar'))+sorted((PRIVATE / 'tools/jxe2jar/libs').glob('org.osgi.*.jar'))
    sources=sorted(src.rglob('*.java'))
    args=[str(javac),'-source','1.4','-target','1.4','-Xlint:-options','-bootclasspath',str(stockjar),'-classpath',os.pathsep.join(map(str,cp)),'-sourcepath',str(src),'-d',str(classes)]+list(map(str,sources))
    r=subprocess.run(args,text=True,capture_output=True)
    (BASE/'reports/stage2-java-compile.log').write_text(r.stdout+r.stderr)
    if r.returncode:print(r.stderr);return r.returncode
    with zipfile.ZipFile(dest,'x',zipfile.ZIP_DEFLATED) as z:
        for c in sorted(classes.rglob('*.class')):
            info=zipfile.ZipInfo(str(c.relative_to(classes)),(2026,9,22,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16;z.writestr(info,c.read_bytes())
    diff=''
    for c in sources:
        n=c.relative_to(src);orig=upstream/'java_patch'/n
        if orig.read_bytes()!=c.read_bytes():diff+=''.join(difflib.unified_diff(orig.read_text().splitlines(True),c.read_text().splitlines(True),fromfile='upstream/'+str(n),tofile='stage2/'+str(n)))
    (BASE/'reports/stage2-java-scope.diff').write_text(diff)
    report=dict(profile='passive-java-boot-and-bus-only',build_id='MU1320-STAGE2-JAVA-PASSIVE-V1',upstream_commit=pinned['commit'],source_count=len(sources),class_count=len(list(classes.rglob('*.class'))),removed_sources=removed,source_sha256={str(c.relative_to(src)):sha(c) for c in sources},stock_event_listener_decompilation_sha256=sha(stock),stock_jar_sha256=sha(stockjar),jar_sha256=sha(dest),jar_size=dest.stat().st_size,exit_code=0,vehicle_tested=False,route_screen_input_modules_activated=False,narrow_navi_ownership_suppression_retained=True,stock_touch_algorithm_restored_with_null_empty_guard=True)
    (BASE/'reports/stage2-java-build.json').write_text(json.dumps(report,indent=2)+'\n');print('Stage2 Java compiled:',report['class_count'],'classes,',report['jar_size'],'bytes')
    return 0
if __name__=='__main__':raise SystemExit(main())
