#!/usr/bin/env python3
"""F6 v2 = F5 v5 bytecode + narrowly rebuilt lifecycle and touchpad bridge.
No native changes; no stock converted class files are shipped. Reproducible
source rebuild in an isolated private directory; existing outputs preserved.
"""
import difflib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
ROOT = BASE.parent
PRIVATE = ROOT / "private-data/mu1320-rgi"
OUT = PRIVATE / "f6-accept-v2"
SRC = BASE / "f6-v2-src"
STAGE = BASE / "mu1320-f6-accept-v2"
JAR = STAGE / "carplay_mu1320_f6_accept_v2.jar.DISABLED"
F5 = BASE / "mu1320-f5-vchud-v5"
FAMILY = "de/audi/app/terminalmode/dsi/carplay/CarplayDSILifecycleController"
JDK = PRIVATE / "tools/jxe2jar/jvms/zulu8.78.0.19-ca-jdk8.0.412-macosx_aarch64/zulu-8.jdk/Contents/Home/bin"
sys.path.insert(0, str(BASE / "scripts"))
import bytecode_compare
import audit_navjava_ingress


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def once(s, old, new):
    assert s.count(old) == 1, old
    return s.replace(old, new, 1)


def run(cmd, log=None):
    p = subprocess.run(list(map(str, cmd)), text=True, capture_output=True)
    if log:
        log.write_text(p.stdout + p.stderr)
    assert p.returncode == 0, p.stdout + p.stderr
    return p.stdout


def entries(jar):
    with zipfile.ZipFile(jar) as z:
        return {n: z.read(n) for n in z.namelist() if n.endswith(".class")}


def patch_lifecycle(s):
    s = once(s, "\n    public void init() {", "\n    private final com.luka.carplay.input.TouchpadBridge touchpad;\n\n    public void init() {")
    s = once(s, "        this.configuration = icontext.getConfiguration();",
             "        this.configuration = icontext.getConfiguration();\n"
             "        this.touchpad = new com.luka.carplay.input.TouchpadBridge(this.dsiCarplaySafe,\n"
             "            this.configuration.getScreenOffsetX(), this.configuration.getScreenOffsetY());")
    s = once(s, "        this.carPlayDsiController.init();", "        this.carPlayDsiController.init();\n        this.touchpad.start();")
    s = once(s, "    public void deinit() {\n        super.deinit();",
             "    public void deinit() {\n        this.touchpad.stop();\n        super.deinit();")
    start = "        public void startService(IDSIAppState[] aidsiappstate, IDSIResource[] aidsiresource) {"
    s = once(s, start, start + "\n            com.luka.carplay.input.TouchpadBridge.newSession();")
    signature = "        public void updateTouchEvents(de.audi.app.terminalmode.keyevents.TouchEvent[] events) {"
    s = once(s, signature, signature + "\n            if (this.this$0.touchpad.handle(events)) return;")
    return s


def main():
    assert not OUT.exists(), "Preserve an existing build directory."
    assert not JAR.exists(), "Never overwrite an issued artifact."
    f5jar = F5 / "carplay_mu1320_f5_vchud_v5.jar.DISABLED"
    f5report = json.loads((BASE / "reports/f5-vchud-v5-build.json").read_text())
    assert sha(f5jar) == f5report["jar_sha256"]
    baseline = entries(f5jar)
    stock = PRIVATE / "MU1320-base.jar"
    assert sha(stock) == f5report["stock_jar_sha256"]
    source = PRIVATE / ("stage2-java/src/" + FAMILY + ".java")
    stage2 = json.loads((BASE / "reports/stage2-java-build.json").read_text())
    assert sha(source) == stage2["source_sha256"][FAMILY + ".java"]

    src, classes, proven = OUT / "src", OUT / "classes", OUT / "proven"
    for d in (src, classes, proven):
        d.mkdir(parents=True)
    for n, data in baseline.items():
        p = proven / n
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    inputs = {FAMILY + ".java": (source.read_text(), patch_lifecycle(source.read_text()))}
    # Navigation bytecode remains unchanged except the helper's new install path.
    name = "com/luka/carplay/rgd/StockDisplay.java"
    old = (BASE / "f5-src/StockDisplay.java").read_text()
    inputs[name] = (old, once(old, "/mnt/app/root/mu1320-rgi-f5-v5/render/f5_sc.sh",
                            "/mnt/app/root/mu1320-rgi-f6-v2/render/f5_sc.sh"))
    name = "com/luka/carplay/core/CarPlayApp.java"
    old = (BASE / "f5-src/CarPlayApp.java").read_text()
    new = once(old, "public static final String BUILD_ID = F5Probe.BUILD_ID;",
               'public static final String BUILD_ID = "MU1320-F6-ACCEPT-V2";')
    # onActivate/onDeactivate are never called in the F5 lineage (TerminalModeBapCombi
    # only calls startTransport/onDeactivateAndWait), so the touchpad session starts
    # from the lifecycle's startService instead; CarPlayApp only changes BUILD_ID.
    new = new.replace("No input, cover-art or navigation-ownership module is", "No cover-art or navigation-ownership module is")
    inputs[name] = (old, new)
    changes = []
    for name, (old, new) in inputs.items():
        p = src / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(new)
        changes.extend(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                          "f5-v5/" + name, "f6-v2/" + name))
    for name in ("TouchpadGesture", "TouchpadBridge", "TouchpadLog"):
        p = src / ("com/luka/carplay/input/" + name + ".java")
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SRC / (name + ".java"), p)
    (BASE / "reports/f6-v2-source.diff").write_text("".join(changes))
    cp = [proven, stock] + sorted((ROOT / "resource/bundles").glob("*.jar"))
    cp += sorted((ROOT / "resource/bundles_prod").glob("*.jar"))
    cp += sorted((PRIVATE / "tools/jxe2jar/libs").glob("org.osgi.*.jar"))
    run([JDK / "javac", "-source", "1.4", "-target", "1.4", "-Xlint:-options",
         "-bootclasspath", stock, "-classpath", os.pathsep.join(map(str, cp)),
         "-sourcepath", src, "-d", classes] + sorted(src.rglob("*.java")),
        BASE / "reports/f6-v2-compile.log")
    rebuilt = {p.relative_to(classes).as_posix(): p.read_bytes() for p in classes.rglob("*.class")}
    replace = (FAMILY, "com/luka/carplay/core/CarPlayApp", "com/luka/carplay/rgd/StockDisplay")
    assert all(n.startswith(replace + ("com/luka/carplay/input/",)) for n in rebuilt), sorted(rebuilt)
    for n in baseline:
        if n.startswith(replace):
            assert n in rebuilt, "lost existing class " + n
    for n, data in baseline.items():
        if not n.startswith(replace):
            p = classes / n
            assert not p.exists(), n
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
    # Prove no unrelated method in the resource/phone/speech/key/rotary seam changed.
    bytecode_compare.JAVAP = JDK / "javap"
    directory = "de/audi/app/terminalmode/dsi/carplay"
    same, diff, gone, added, a, b = bytecode_compare.compare(proven / directory, classes / directory,
                                                           "CarplayDSILifecycleController")
    allowed = ("#public void init();", "#public void deinit();", "#public de.audi.app.terminalmode.dsi.carplay.CarplayDSILifecycleController(",
               "$TerminalModeDSIKeyEventsController#public void updateTouchEvents(",
               "$CarplayDSIController#public void startService(")
    assert all(any(k in m for k in allowed) or "access$" in m for m in diff), diff
    assert not gone, gone
    assert all("access$" in m for m in added), added
    (BASE / "reports/f6-v2-method-scope.json").write_text(json.dumps({"identical_methods": len(same),
        "changed_methods": diff, "removed": gone, "added": added}, indent=2) + "\n")
    host = OUT / "host"
    host.mkdir()
    run([JDK / "javac", "-source", "1.8", "-target", "1.8", "-Xlint:-options", "-classpath",
         os.pathsep.join(map(str, [classes, stock])), "-d", host,
         SRC / "TouchpadHarness.java", BASE / "f1-src/F1V2Harness.java"])
    # Existing phone/speech/resource/key equivalence harness on the NEW family.
    f1 = run([JDK / "java", "-Xverify:all", "-cp", host, "F1V2Harness", stock,
              classes, ROOT / "resource/jars/NavActiveIgnore.jar"], BASE / "reports/f6-v2-f1-harness.txt")
    touch = run([JDK / "java", "-Xverify:all", "-cp", os.pathsep.join(map(str, [host, classes, stock])),
                 "com.luka.carplay.input.TouchpadHarness"], BASE / "reports/f6-v2-touchpad-harness.txt")
    # Existing F5 state/output/presentation suite uses the v2 delivered classes.
    run([JDK / "javac", "-source", "1.8", "-target", "1.8", "-Xlint:-options", "-classpath",
         os.pathsep.join(map(str, [classes, stock])), "-d", host,
         BASE / "f2-src/F2Harness.java", BASE / "f2-src/F2Replay.java",
         BASE / "f5-src/F5Harness.java", BASE / "f5-src/F5Replay.java"])
    vehicle = ROOT / "resource/private/vehicle-dump"
    f5 = run([JDK / "java", "-Xverify:all", "-cp", os.pathsep.join(map(str, [host, classes, stock])),
              "com.luka.carplay.rgd.F5Harness",
              vehicle / "f2-shadow-v1/armed-9150607/mu1320-f2-frames.cap",
              vehicle / "f2-shadow-v1/armed-9150607/mu1320-f2-state.log",
              vehicle / "f3-bap-v2/armed-9855120/mu1320-f3-frames.cap",
              vehicle / "f3-bap-v2/armed-9855120/mu1320-f3-bap.log",
              vehicle / "f3-bap-v2/armed-9855120/mu1320-f3-state.log",
              PRIVATE / "f3-bap-v2/classes", PRIVATE / "f5-vchud-v5/f3-tools", stock],
             BASE / "reports/f6-v2-f5-harness.txt")
    STAGE.mkdir(exist_ok=True)
    assert not any(STAGE.iterdir()), "preserve existing SD folder"
    with zipfile.ZipFile(JAR, "x", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(classes.rglob("*.class")):
            info = zipfile.ZipInfo(p.relative_to(classes).as_posix(), (2026, 9, 27, 0, 0, 0))
            info.create_system = 3; info.compress_type = zipfile.ZIP_DEFLATED; info.external_attr = 0o100644 << 16
            z.writestr(info, p.read_bytes())
    final = entries(JAR)
    unchanged = sorted(n for n in baseline if baseline[n] == final.get(n))
    report = {"build_id": "MU1320-F6-ACCEPT-V2", "jar_sha256": sha(JAR), "jar_size": JAR.stat().st_size,
              "stock_jar_sha256": sha(stock), "f5_v5_jar_sha256": sha(f5jar), "class_count": len(final),
              "f5_v5_byte_identical": unchanged, "changed_classes": sorted(set(baseline) - set(unchanged)),
              "new_classes": sorted(set(final) - set(baseline)), "native_changed": False, "vehicle_tested": False,
              "source_sha256": {p.relative_to(src).as_posix(): sha(p) for p in src.rglob("*.java")},
              "harness": {"f1": f1.strip().splitlines()[-1], "touch": touch.strip().splitlines()[-1],
                          "f5": f5.strip().splitlines()[-1]}}
    reportpath = BASE / "reports/f6-v2-build.json"
    reportpath.write_text(json.dumps(report, indent=2) + "\n")
    audit = audit_navjava_ingress.audit(JAR, reportpath, BASE / "reports/f6-v2-audit.json",
        replace + ("com/luka/carplay/input/",),
        ["Host JVM verification does not replace J9/vehicle validation.",
         "Navigation is F5 v5 bytecode, except the StockDisplay helper path and the CarPlayApp BUILD_ID.",
         "Input gestures require parked T-session acceptance before integrated F6 sessions."],
        proven_jar=f5jar, allowed_tokens=("CarplayDSILifecycleController", "Renderer", "DisplayManager"))
    assert audit["status"] == "PASS", audit
    print(json.dumps({k: report[k] for k in ("build_id", "class_count", "jar_sha256", "harness")}, indent=2))


if __name__ == "__main__":
    main()
