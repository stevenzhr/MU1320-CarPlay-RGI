#!/usr/bin/env python3
"""F7 v1 Java = F6 v2 bytecode + the renderer keeper and persistent switches.

The F6 v2 JAR (car-run: T session) is the baseline.  Recompiled from source:
  * F5Probe          keeper hooks (request on HELLO / active route, lost-link
                     tick, cluster stays stock until the keeper is ready, log
                     caps) and F7Switches instead of the two /tmp checks;
  * StockDisplay     helper path in the F7 workspace;
  * CarPlayApp       BUILD_ID and listener line;
  * TouchpadBridge   F7Switches.touchpadOff() and BUILD_ID;
  * new              RendererKeeper, F7Switches.
Before patching, the unmodified sources of those four classes are compiled
and must reproduce the F6 v2 class bytes exactly, so the diff in
reports/f7-v1-source.diff is the whole Java change.  All other classes are
copied from the F6 v2 JAR byte for byte.
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
OUT = PRIVATE / "f7-daily-v1-java"
SRC = BASE / "f7-src"
STAGE = BASE / "mu1320-f7-daily-v1"
JAR = STAGE / "carplay_mu1320_f7_daily_v1.jar.DISABLED"
F6 = BASE / "mu1320-f6-accept-v2"
F6_JAR = F6 / "carplay_mu1320_f6_accept_v2.jar.DISABLED"
F6_SRC = PRIVATE / "f6-accept-v2/src"
BUILD_ID = "MU1320-F7-DAILY-V1"
JDK = PRIVATE / "tools/jxe2jar/jvms/zulu8.78.0.19-ca-jdk8.0.412-macosx_aarch64/zulu-8.jdk/Contents/Home/bin"
sys.path.insert(0, str(BASE / "scripts"))
import audit_navjava_ingress  # noqa: E402

PROBE = "com/luka/carplay/rgd/F5Probe"
DISPLAY = "com/luka/carplay/rgd/StockDisplay"
APP = "com/luka/carplay/core/CarPlayApp"
TOUCH = "com/luka/carplay/input/TouchpadBridge"
NEW = ["com/luka/carplay/rgd/RendererKeeper", "com/luka/carplay/rgd/F7Switches"]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


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


def patch_probe(s):
    s = once(s, "    private RenderLink link;\n",
             "    private RenderLink link;\n    private RendererServer renderer;\n    private RendererKeeper keeper;\n"
             "    private long lastCap;\n")
    s = once(s, "    private static final long POLL_MS = 1000L;\n",
             "    private static final long POLL_MS = 1000L;\n    private static final long CAP_MS = 60000L;\n")
    s = once(s, "            link = new RenderLink(new RendererServer(), presenter, renderLog);\n",
             "            renderer = new RendererServer();\n"
             "            link = new RenderLink(renderer, presenter, renderLog);\n"
             "            /* F7: no manual arm.  The keeper starts the renderer and declares context 80;\n"
             "             * until it reports ready the cluster stays stock. */\n"
             "            keeper = RendererKeeper.vehicle(renderLog);\n"
             "            presenter.setRenderKill(true);\n")
    s = once(s, "            bapLog.line(\"START_PROBE build=\" + BUILD_ID + \" yield=stock_rg_active metric=\" + (NaviBapSink.isMetric() ? 1 : 0)\n"
                "                + \" kill=\" + (exists(KILL_PATH) ? 1 : 0)",
             "            bapLog.line(\"START_PROBE build=\" + BUILD_ID + \" yield=stock_rg_active metric=\" + (NaviBapSink.isMetric() ? 1 : 0)\n"
             "                + \" kill=\" + (F7Switches.bapOff() ? 1 : 0)")
    s = once(s, "            renderLog.line(\"START_PROBE build=\" + BUILD_ID + \" render_off=\" + (exists(RENDER_OFF_PATH) ? 1 : 0)",
             "            renderLog.line(\"START_PROBE build=\" + BUILD_ID + \" render_off=\" + (F7Switches.renderOff() ? 1 : 0)")
    s = once(s, "                + \" helper=\" + StockDisplay.SC_HELPER);\n",
             "                + \" helper=\" + StockDisplay.SC_HELPER + \" keeper=\" + RendererKeeper.SCRIPT\n"
             "                + \" daily=\" + com.luka.carplay.core.CarPlayApp.BUILD_ID);\n")
    s = once(s, "            presenter.setMode(readMode());\n            output.setKilled(exists(KILL_PATH));\n            setupDisplay();\n",
             "            presenter.setMode(readMode());\n            output.setKilled(F7Switches.bapOff());\n            setupDisplay();\n")
    s = once(s, "            if (!linkUp) linkUp = true;\n            output.setKilled(exists(KILL_PATH));\n",
             "            if (!linkUp) linkUp = true;\n            output.setKilled(F7Switches.bapOff());\n")
    s = once(s, "            linkUp = true;\n            sanitizer.reset();\n            record(core.onSession(), \"E SESSION\");\n",
             "            linkUp = true;\n            sanitizer.reset();\n            record(core.onSession(), \"E SESSION\");\n"
             "            if (!F7Switches.renderOff()) keeper.request(\"hello\");\n")
    s = once(s, "                if (output.held()) output.setKilled(exists(KILL_PATH));\n",
             "                if (output.held()) output.setKilled(F7Switches.bapOff());\n")
    s = once(s, "                lastPoll = now;\n                output.setKilled(exists(KILL_PATH));\n",
             "                lastPoll = now;\n                output.setKilled(F7Switches.bapOff());\n")
    s = once(s, "                boolean renderOff = exists(RENDER_OFF_PATH);\n                boolean calib = exists(CALIB_PATH) && !output.owning();\n"
                "                presenter.setRenderKill(renderOff);\n",
             "                boolean renderOff = F7Switches.renderOff();\n                boolean calib = exists(CALIB_PATH) && !output.owning();\n"
             "                keeper.tick(renderer.isConnected());\n"
             "                if (!renderOff && (core.isActive() || calib) && !keeper.ready()) keeper.request(\"route\");\n"
             "                if (now - lastCap >= CAP_MS) {\n"
             "                    lastCap = now;\n"
             "                    RendererKeeper.capLogs(renderLog);\n"
             "                }\n"
             "                presenter.setRenderKill(renderOff || !keeper.ready());\n")
    assert "exists(KILL_PATH)" not in s and "exists(RENDER_OFF_PATH)" not in s
    return s


def patch_display(s):
    return once(s, "/mnt/app/root/mu1320-rgi-f6-v2/render/f5_sc.sh", "/mnt/app/root/mu1320-rgi-f7-v1/render/f5_sc.sh")


def patch_app(s):
    s = once(s, 'public static final String BUILD_ID = "MU1320-F6-ACCEPT-V2";',
             'public static final String BUILD_ID = "MU1320-F7-DAILY-V1";')
    return once(s, '" LISTENER_READY bap-yield+render; NavActiveIgnore quarantined; renderer 98 via ctx 80");',
                '" LISTENER_READY bap-yield+render; NavActiveIgnore quarantined; renderer 98 via ctx 80; keeper auto");')


def patch_touch(s):
    s = once(s, 'public static final String BUILD_ID = "MU1320-F6-ACCEPT-V2";',
             'public static final String BUILD_ID = "MU1320-F7-DAILY-V1";')
    return once(s, "try { return running && !fault && !off.exists(); }",
                "try { return running && !fault && !off.exists() && !com.luka.carplay.rgd.F7Switches.touchpadPersistentOff(); }")


def compile_java(src, out, cp, log):
    run([JDK / "javac", "-source", "1.4", "-target", "1.4", "-Xlint:-options",
         "-bootclasspath", cp[1], "-classpath", os.pathsep.join(map(str, cp)),
         "-sourcepath", src, "-d", out] + sorted(Path(src).rglob("*.java")), log)
    return {p.relative_to(out).as_posix(): p.read_bytes() for p in Path(out).rglob("*.class")}


def main():
    assert not OUT.exists(), "Preserve an existing build directory."
    assert not JAR.exists(), "Never overwrite an issued artifact."
    f6report = json.loads((BASE / "reports/f6-v2-build.json").read_text())
    assert sha(F6_JAR) == f6report["jar_sha256"], "must be the F6 v2 JAR that ran on the car"
    baseline = entries(F6_JAR)
    stock = PRIVATE / "MU1320-base.jar"
    assert sha(stock) == f6report["stock_jar_sha256"]

    originals = {
        PROBE: (BASE / "f5-src/F5Probe.java").read_text(),
        DISPLAY: (F6_SRC / (DISPLAY + ".java")).read_text(),
        APP: (F6_SRC / (APP + ".java")).read_text(),
        TOUCH: (BASE / "f6-v2-src/TouchpadBridge.java").read_text(),
    }
    assert originals[TOUCH] == (F6_SRC / (TOUCH + ".java")).read_text()
    proven = OUT / "proven"
    for n, data in baseline.items():
        p = proven / n
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    cp = [proven, stock] + sorted((ROOT / "resource/bundles").glob("*.jar"))
    cp += sorted((ROOT / "resource/bundles_prod").glob("*.jar"))
    cp += sorted((PRIVATE / "tools/jxe2jar/libs").glob("org.osgi.*.jar"))

    # 1. Reproduce the F6 v2 bytes from the unmodified sources.  F6 v2 did not
    # recompile F5Probe, so its bytes inline the F5 v5 StockDisplay.SC_HELPER
    # (a log-only string): F5Probe is reproduced against the F5 v5 StockDisplay
    # source, the three other classes against each other.
    repro = {}
    for tag, members in [("probe", {PROBE: originals[PROBE],
                                    DISPLAY: (BASE / "f5-src/StockDisplay.java").read_text()}),
                         ("rest", {n: originals[n] for n in (DISPLAY, APP, TOUCH)})]:
        repro_src, repro_out = OUT / ("repro-src-" + tag), OUT / ("repro-classes-" + tag)
        for name, text in members.items():
            p = repro_src / (name + ".java")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        repro_out.mkdir(parents=True)
        got = compile_java(repro_src, repro_out, cp, BASE / ("reports/f7-v1-repro-%s-compile.log" % tag))
        for n, data in got.items():
            if tag == "probe" and n.startswith(DISPLAY):
                continue
            assert baseline.get(n) == data, "source does not reproduce F6 v2 bytes: " + n
            repro[n] = sha(repro_out / n)
    for name in originals:
        assert name + ".class" in repro, name

    # 2. Patch and compile.
    patched = {PROBE: patch_probe(originals[PROBE]), DISPLAY: patch_display(originals[DISPLAY]),
               APP: patch_app(originals[APP]), TOUCH: patch_touch(originals[TOUCH])}
    src, classes = OUT / "src", OUT / "classes"
    changes = []
    for name, text in patched.items():
        p = src / (name + ".java")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        changes.extend(difflib.unified_diff(originals[name].splitlines(True), text.splitlines(True),
                                            "f6-v2/" + name + ".java", "f7-v1/" + name + ".java"))
    for name in NEW:
        p = src / (name + ".java")
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SRC / (name.rsplit("/", 1)[1] + ".java"), p)
    (BASE / "reports/f7-v1-source.diff").write_text("".join(changes))
    classes.mkdir(parents=True)
    rebuilt = compile_java(src, classes, cp, BASE / "reports/f7-v1-compile.log")
    owners = tuple(patched) + tuple(NEW)
    assert all(n[:-6].split("$")[0] in owners for n in rebuilt), sorted(rebuilt)
    for n in baseline:
        if n[:-6].split("$")[0] in owners:
            assert n in rebuilt, "lost existing class " + n
    for n, data in baseline.items():
        if n not in rebuilt:
            p = classes / n
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)

    # 3. Harnesses on the delivered classes.
    host = OUT / "host"
    host.mkdir()
    run([JDK / "javac", "-source", "1.8", "-target", "1.8", "-Xlint:-options", "-classpath",
         os.pathsep.join(map(str, [classes, stock])), "-d", host,
         SRC / "F7KeeperHarness.java", BASE / "f6-v2-src/TouchpadHarness.java", BASE / "f1-src/F1V2Harness.java",
         BASE / "f2-src/F2Harness.java", BASE / "f2-src/F2Replay.java",
         BASE / "f5-src/F5Harness.java", BASE / "f5-src/F5Replay.java"])
    hcp = os.pathsep.join(map(str, [host, classes, stock]))
    keeper = run([JDK / "java", "-Xverify:all", "-cp", hcp, "com.luka.carplay.rgd.F7KeeperHarness"],
                 BASE / "reports/f7-v1-keeper-harness.txt")
    f1 = run([JDK / "java", "-Xverify:all", "-cp", host, "F1V2Harness", stock, classes,
              ROOT / "resource/jars/NavActiveIgnore.jar"], BASE / "reports/f7-v1-f1-harness.txt")
    touch = run([JDK / "java", "-Xverify:all", "-cp", hcp, "com.luka.carplay.input.TouchpadHarness"],
                BASE / "reports/f7-v1-touchpad-harness.txt")
    vehicle = ROOT / "resource/private/vehicle-dump"
    f5 = run([JDK / "java", "-Xverify:all", "-cp", hcp, "com.luka.carplay.rgd.F5Harness",
              vehicle / "f2-shadow-v1/armed-9150607/mu1320-f2-frames.cap",
              vehicle / "f2-shadow-v1/armed-9150607/mu1320-f2-state.log",
              vehicle / "f3-bap-v2/armed-9855120/mu1320-f3-frames.cap",
              vehicle / "f3-bap-v2/armed-9855120/mu1320-f3-bap.log",
              vehicle / "f3-bap-v2/armed-9855120/mu1320-f3-state.log",
              PRIVATE / "f3-bap-v2/classes", PRIVATE / "f5-vchud-v5/f3-tools", stock],
             BASE / "reports/f7-v1-f5-harness.txt")

    # 4. JAR, report, link audit.
    STAGE.mkdir(exist_ok=True)
    assert not any(STAGE.iterdir()), "preserve existing SD folder"
    with zipfile.ZipFile(JAR, "x", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(classes.rglob("*.class")):
            info = zipfile.ZipInfo(p.relative_to(classes).as_posix(), (2026, 9, 27, 0, 0, 0))
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            z.writestr(info, p.read_bytes())
    final = entries(JAR)
    unchanged = sorted(n for n in baseline if baseline[n] == final.get(n))
    report = {"build_id": BUILD_ID, "jar_sha256": sha(JAR), "jar_size": JAR.stat().st_size,
              "stock_jar_sha256": sha(stock), "f6_v2_jar_sha256": sha(F6_JAR), "class_count": len(final),
              "f6_v2_byte_identical": unchanged, "changed_classes": sorted(set(baseline) - set(unchanged)),
              "new_classes": sorted(set(final) - set(baseline)), "reproduced_before_patch": sorted(repro),
              "vehicle_tested": False,
              "source_sha256": {p.relative_to(src).as_posix(): sha(p) for p in src.rglob("*.java")},
              "harness": {"keeper": keeper.strip().splitlines()[-1], "f1": f1.strip().splitlines()[-1],
                          "touch": touch.strip().splitlines()[-1], "f5": f5.strip().splitlines()[-1]}}
    reportpath = BASE / "reports/f7-v1-build.json"
    reportpath.write_text(json.dumps(report, indent=2) + "\n")
    audit = audit_navjava_ingress.audit(JAR, reportpath, BASE / "reports/f7-v1-audit.json",
        owners + ("com/luka/carplay/input/", "de/audi/app/terminalmode/dsi/carplay/"),
        ["Host JVM verification does not replace J9/vehicle validation.",
         "Navigation, BAP, presenter, lifecycle and touchpad gesture bytecode are F6 v2 bytes; "
         "F5Probe gains the keeper hooks and persistent switches.",
         "The keeper script, launcher and always-on native gate need the F7 vehicle sessions."],
        proven_jar=F6_JAR, allowed_tokens=("CarplayDSILifecycleController", "Renderer", "DisplayManager"))
    assert audit["status"] == "PASS", audit
    print(json.dumps({k: report[k] for k in ("build_id", "class_count", "jar_sha256", "changed_classes",
                                               "new_classes", "harness")}, indent=2))


if __name__ == "__main__":
    main()
