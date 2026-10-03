#!/usr/bin/env python3
"""Build the F5 VC/HUD trial JAR and run the offline F5 harness.

The vehicle JAR =
  * the F2 class set that ran on the car (bus, logger, TerminalMode entry seam,
    ingress validator, RouteStateCore, F2ShadowProbe, unmodified upstream
    ManeuverMapper), recompiled and checked byte-identical to the F2 JAR;
  * BapPlanner, recompiled and checked byte-identical to the F3 v2 JAR;
  * the 13 CarplayDSILifecycleController classes copied byte for byte from the
    vehicle-tested F1 v2 JAR (CarPlay NAVI app state -> 0, the NavActiveIgnore
    replacement);
  * upstream RendererMapper (unmodified) and RendererServer (plus one grid
    toggle command for the parked geometry calibration);
  * new F5 classes: BapSink/NaviBapSink (F3 v2 + lanes 24 + ETA 22),
    F5BapOutput, TripPlanner, RenderPlanner, RenderLink, ClusterPresenter,
    StockDisplay, GeomOverride, LineLog, F5Probe and the F5 CarPlayApp entry.
No stock Audi/e.solutions class is replaced.

v2 (F5 v1 car run: stock DisplayManagerMIB2High rewrote Java switchContext(80)
to 73, reports/F5-V1-CTX-CALLERS.md): ClusterPresenter switches natively (dmdt
through the installed helper f5_sc.sh, read back with dmdt gs) or, with
/tmp/mu1320-f5-ctx-mode = kdk, hides the stock KDK first; the harness models
the stock DisplayManager from bytecode.

v3 (F5 v2 car run): the helper's dmdt watchdog is stopped with SIGKILL (JVM
children inherit SIGTERM ignored: 20 s per native switch), and FIGHT_STOP
counts only retakes of takeovers that lasted under 2 s (one VIEW press makes
stock reclaim 3-4 times; v2 stopped the map box after two presses).

v4 (F5 v3 car run): a takeover whose read-back is a stock map context lost a
race with a stock reclaim and is taken again (TAKE_RACED); real failures retry
after 10 s, at most 3 times per ownership (v3 never retried).

v5 (F5 v4 car runs): kdk is the default mode (smoother on the car; the ctx-mode
file "native" selects native), FIGHT_STOP pauses 3 s (doubling to 30 s) and
resumes instead of stopping for the whole route (rapid VIEW presses).
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
PRIVATE = BASE.parent / "private-data" / "mu1320-rgi"
ROOT = BASE.parent
VERSION = 5
V = "v%d" % VERSION
BUILD_ID = "MU1320-F5-VCHUD-V%d" % VERSION
REPORT = "f5-vchud-" + V
OUT = PRIVATE / ("f5-vchud-" + V)
STAGE = BASE / ("mu1320-f5-vchud-" + V)
JAR = STAGE / ("carplay_mu1320_f5_vchud_%s.jar.DISABLED" % V)
F2_JAR = BASE / "mu1320-f2-shadow-v1/carplay_mu1320_f2_shadow_v1.jar.DISABLED"
F1_JAR = BASE / "f1-trial-v2/carplay_mu1320_f1_navi_v2.jar.DISABLED"
F3_JAR = BASE / "mu1320-f3-bap-v2/carplay_mu1320_f3_bap_v2.jar.DISABLED"
UPSTREAM_COMMIT = "f36790d450392516ed9cbfab9cc06aa13a08bf31"
LIFECYCLE = "de/audi/app/terminalmode/dsi/carplay/CarplayDSILifecycleController"
VEHICLE = ROOT / "resource/private/vehicle-dump"
F2_VEHICLE = VEHICLE / "f2-shadow-v1/armed-9150607"
F3_VEHICLE = VEHICLE / "f3-bap-v2/armed-9855120"
F5_CLASSES = ["BapSink", "NaviBapSink", "F5BapOutput", "TripPlanner", "RenderPlanner", "RenderLink",
              "ClusterPresenter", "StockDisplay", "GeomOverride", "LineLog", "F5Probe"]

GRID_ANCHOR_1 = "    private static final byte CMD_CLEAR       = 0x07;\n"
GRID_CONST = ("    /* MU1320 F5: debug overlay toggle (payload 2 = 8x6 geometry grid), used only\n"
              "     * by the parked geometry calibration step. */\n"
              "    private static final byte CMD_DEBUG       = 0x05;\n"
              "    private static final byte DEBUG_GRID_TOGGLE = 2;\n")
GRID_ANCHOR_2 = "    /**\n     * Non-blocking send.  Returns false if no current connection or"
GRID_METHOD = ("    /** MU1320 F5: toggle the renderer's 8x6 geometry grid (state lives in the renderer process). */\n"
               "    public boolean sendGridToggle() {\n"
               "        byte[] pkt = new byte[PKT_SIZE];\n"
               "        pkt[0] = CMD_DEBUG;\n"
               "        pkt[2] = DEBUG_GRID_TOGGLE;\n"
               "        return sendPacket(pkt);\n"
               "    }\n\n")

sys.path.insert(0, str(BASE / "scripts"))
import audit_navjava_ingress  # noqa: E402


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, log=None):
    done = subprocess.run(command, text=True, capture_output=True)
    if log is not None:
        log.write_text(done.stdout + done.stderr)
    assert done.returncode == 0, done.stdout + done.stderr
    return done.stdout


def jar_classes(path):
    with zipfile.ZipFile(path) as archive:
        return {name: archive.read(name) for name in archive.namelist() if name.endswith(".class")}


def main():
    assert not OUT.exists(), "Preserve the existing F5 build; use a new version."
    assert not JAR.exists(), "Never overwrite an issued Java artifact."
    upstream = ROOT / "mib2q-carplay-rgi"
    head = subprocess.check_output(["git", "-C", str(upstream), "rev-parse", "HEAD"], text=True).strip()
    assert head == UPSTREAM_COMMIT, head

    f1_build = json.loads((BASE / "reports/f1-v2-build.json").read_text())
    f2_build = json.loads((BASE / "reports/f2-shadow-build.json").read_text())
    f3_build = json.loads((BASE / "reports/f3-bap-v2-build.json").read_text())
    for report, status in [("f1-v2-vehicle.json", "F1_V2_NAVI_SEAM_AND_ROLLBACK_VERIFIED"),
                           ("f2-shadow-vehicle-v1.json", "F2_SHADOW_STATE_AND_ROLLBACK_VERIFIED"),
                           ("f3-bap-vehicle-v2.json", "F3_BAP_OUTPUT_AND_ROLLBACK_VERIFIED"),
                           ("f4-render-vehicle-v1.json", "F4_RENDERER_LAYER_AND_ROLLBACK_VERIFIED")]:
        assert json.loads((BASE / "reports" / report).read_text())["status"] == status, report
    assert sha(F1_JAR) == f1_build["jar_sha256"], "must be the F1 v2 JAR that ran on the car"
    assert sha(F2_JAR) == f2_build["jar_sha256"], "must be the F2 JAR that ran on the car"
    assert sha(F3_JAR) == f3_build["jar_sha256"], "must be the F3 v2 JAR that ran on the car"

    src, classes, test_classes, f3_tools = OUT / "src", OUT / "classes", OUT / "test-classes", OUT / "f3-tools"
    for path in (src, classes, test_classes, f3_tools):
        path.mkdir(parents=True)

    proven = PRIVATE / "stage2-java/src"
    rgd = "com/luka/carplay/rgd/"
    up = upstream / "java_patch/com/luka/carplay/rgd"
    inputs = {
        "com/luka/carplay/bus/CarplayBus.java": proven / "com/luka/carplay/bus/CarplayBus.java",
        "com/luka/carplay/framework/Log.java": proven / "com/luka/carplay/framework/Log.java",
        "de/audi/app/terminalmode/combi/TerminalModeBapCombi.java":
            proven / "de/audi/app/terminalmode/combi/TerminalModeBapCombi.java",
        rgd + "RgdIngressProbe.java": BASE / "navjava-trial-src/RgdIngressProbe.java",
        rgd + "ManeuverMapper.java": up / "ManeuverMapper.java",
        rgd + "RendererMapper.java": up / "RendererMapper.java",
        rgd + "RendererServer.java": BASE / "f5-src/RendererServer.java",
        rgd + "RouteStateCore.java": BASE / "f2-src/RouteStateCore.java",
        rgd + "F2ShadowProbe.java": BASE / "f2-src/F2ShadowProbe.java",
        rgd + "BapPlanner.java": BASE / "f3-src/BapPlanner.java",
        "com/luka/carplay/core/CarPlayApp.java": BASE / "f5-src/CarPlayApp.java",
    }
    for name in F5_CLASSES:
        inputs[rgd + name + ".java"] = BASE / "f5-src" / (name + ".java")
    helper = '"/mnt/app/root/mu1320-rgi-f5-%s/render/f5_sc.sh"' % V
    assert helper in (BASE / "f5-src/StockDisplay.java").read_text(), "StockDisplay.SC_HELPER must be the %s runtime" % V
    assert ('"MU1320-F5-VCHUD-V%d"' % VERSION) in (BASE / "f5-src/F5Probe.java").read_text()
    for name, source in inputs.items():
        assert source.is_file(), source
        target = src / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    # RendererMapper is upstream verbatim; RendererServer differs only by the grid toggle.
    assert (BASE / "f5-src/RendererMapper.java").read_bytes() == (up / "RendererMapper.java").read_bytes()
    server_diff = subprocess.run(["diff", str(up / "RendererServer.java"), str(BASE / "f5-src/RendererServer.java")],
                                 capture_output=True, text=True).stdout
    upstream_server = (up / "RendererServer.java").read_text()
    expected = upstream_server.replace(GRID_ANCHOR_1, GRID_ANCHOR_1 + GRID_CONST, 1).replace(
        GRID_ANCHOR_2, GRID_METHOD + GRID_ANCHOR_2, 1)
    assert expected == (BASE / "f5-src/RendererServer.java").read_text(), "RendererServer = upstream + grid toggle only"
    (BASE / "reports" / (REPORT + "-renderer-server.diff")).write_text(server_diff)

    stock = PRIVATE / "MU1320-base.jar"
    stock_sha = json.loads((BASE / "reports/java-mu1320-build.json").read_text())["stock_sha256"]
    assert sha(stock) == stock_sha
    jdk = (PRIVATE / "tools/jxe2jar/jvms/zulu8.78.0.19-ca-jdk8.0.412-macosx_aarch64/"
           "zulu-8.jdk/Contents/Home/bin")
    javac, java = jdk / "javac", jdk / "java"
    cp = [stock]
    cp += sorted((ROOT / "resource/bundles").glob("*.jar"))
    cp += sorted((ROOT / "resource/bundles_prod").glob("*.jar"))
    cp += sorted((PRIVATE / "tools/jxe2jar/libs").glob("org.osgi.*.jar"))
    run([str(javac), "-source", "1.4", "-target", "1.4", "-Xlint:-options",
         "-bootclasspath", str(stock), "-classpath", os.pathsep.join(map(str, cp)),
         "-sourcepath", str(src), "-d", str(classes)] + list(map(str, sorted(src.rglob("*.java")))),
        BASE / "reports" / (REPORT + "-compile.log"))

    family = jar_classes(F1_JAR)
    assert len(family) == 13 and all(name.startswith(LIFECYCLE) for name in family), sorted(family)
    for name, data in family.items():
        assert not (classes / name).exists(), name
        (classes / name).parent.mkdir(parents=True, exist_ok=True)
        (classes / name).write_bytes(data)

    # Host tools.  F3's replay runs against the shipped F3 v2 classes in its own
    # directory (F5 changed BapSink); the F5 harness loads it in an isolated loader.
    f3_classes = PRIVATE / "f3-bap-v2/classes"
    run([str(javac), "-source", "1.8", "-target", "1.8", "-Xlint:-options",
         "-classpath", os.pathsep.join([str(f3_classes), str(stock)]), "-d", str(f3_tools),
         str(BASE / "f2-src/F2Replay.java"), str(BASE / "f3-src/F3Replay.java")])
    host_sources = [BASE / "f2-src/F2Harness.java", BASE / "f2-src/F2Replay.java",
                    BASE / "f5-src/F5Replay.java", BASE / "f5-src/F5Harness.java"]
    run([str(javac), "-source", "1.8", "-target", "1.8", "-Xlint:-options",
         "-classpath", os.pathsep.join([str(classes), str(stock)]),
         "-d", str(test_classes)] + list(map(str, host_sources)))
    harness = run([str(java), "-Xverify:all",
                   "-cp", os.pathsep.join([str(test_classes), str(classes), str(stock)]),
                   "com.luka.carplay.rgd.F5Harness",
                   str(F2_VEHICLE / "mu1320-f2-frames.cap"), str(F2_VEHICLE / "mu1320-f2-state.log"),
                   str(F3_VEHICLE / "mu1320-f3-frames.cap"), str(F3_VEHICLE / "mu1320-f3-bap.log"),
                   str(F3_VEHICLE / "mu1320-f3-state.log"), str(f3_classes), str(f3_tools), str(stock)],
                  BASE / "reports" / (REPORT + "-harness.txt"))
    assert "F5_HARNESS_PASS" in harness

    STAGE.mkdir(exist_ok=True)
    assert not any(STAGE.iterdir()), "Preserve existing staged files; use a new version."
    with zipfile.ZipFile(JAR, "x", zipfile.ZIP_DEFLATED) as archive:
        for item in sorted(classes.rglob("*.class")):
            entry = zipfile.ZipInfo(str(item.relative_to(classes)), (2026, 9, 26, 0, 0, 0))
            entry.create_system = 3
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, item.read_bytes())
    with zipfile.ZipFile(JAR) as archive:
        assert archive.testzip() is None
    entries = jar_classes(JAR)
    assert not any("Harness" in name or "Replay" in name for name in entries)

    # Every class shared with a vehicle-run JAR must be byte-identical to it.
    f2 = jar_classes(F2_JAR)
    f3 = jar_classes(F3_JAR)
    shared_f2 = sorted(name for name in entries if name in f2
                       and not name.startswith("com/luka/carplay/core/CarPlayApp"))
    assert len(shared_f2) == len(f2) - 1, sorted(set(f2) - set(shared_f2))
    assert all(entries[name] == f2[name] for name in shared_f2), [n for n in shared_f2 if entries[n] != f2[n]]
    planner = sorted(name for name in entries if name.startswith(rgd + "BapPlanner"))
    assert planner and all(entries[name] == f3[name] for name in planner), planner
    assert all(entries[name] == data for name, data in family.items())
    fresh = sorted(name for name in entries if name not in f2 and name not in family and name not in planner)
    allowed = tuple(rgd + n for n in F5_CLASSES + ["RendererMapper", "RendererServer"]) + (
        "com/luka/carplay/core/CarPlayApp",)
    assert all(name.startswith(allowed) for name in fresh), fresh

    build_report = BASE / "reports" / (REPORT + "-build.json")
    report = {
        "profile": "f5-vchud",
        "build_id": BUILD_ID,
        "class_count": len(entries),
        "classes": sorted(entries),
        "fresh_classes": fresh,
        "source_sha256": {name: sha(path) for name, path in inputs.items()},
        "upstream_commit": UPSTREAM_COMMIT,
        "maneuver_mapper": "unmodified upstream source at upstream_commit",
        "renderer_mapper": "unmodified upstream source at upstream_commit",
        "renderer_server": "upstream + sendGridToggle (reports/" + REPORT + "-renderer-server.diff)",
        "stock_jar_sha256": stock_sha,
        "jar_sha256": sha(JAR),
        "jar_size": JAR.stat().st_size,
        "f2_vehicle_classes_reused_byte_identical": shared_f2,
        "f3_v2_classes_reused_byte_identical": planner,
        "f1_v2_lifecycle_classes_copied_byte_identical": sorted(family),
        "f1_v2_jar_sha256": sha(F1_JAR),
        "f2_jar_sha256": sha(F2_JAR),
        "f3_v2_jar_sha256": sha(F3_JAR),
        "harness": harness.strip().splitlines()[-2:],
        "bap_fctids": [17, 39, 23, 18, 49, 55, 21, 24, 22],
        "stock_coexistence": "yield (F3 v2): publish only while stock DSIResponseContainer.isRgActive()==false; "
                             "silent release whenever stock has or may have a route; resume immediately when it ends",
        "renderer": "Java listens on 127.0.0.1:19800 (upstream RendererServer); maneuver_render started by arm",
        "cluster": "ClusterPresenter: ctx 80 {98,102,101,33} only while BAP owns a route and the renderer has a frame; "
                   "98 cropped/placed at the stock KDK box (Layout 118-125, 58-61; stock small-stage rule); "
                   "switch natively via the installed f5_sc.sh (dmdt sc 4 + gs read-back) or, in kdk mode, "
                   "setKDKVisible(-1) then Java switchContext(80); never a Java switch to 80 with the KDK visible",
        "context_switch_helper": "/mnt/app/root/mu1320-rgi-f5-" + V + "/render/f5_sc.sh (Runtime.exec, as stock CommandLineExecuter)",
        "switches": ["/tmp/mu1320-f5-bap-off", "/tmp/mu1320-f5-render-off", "/tmp/mu1320-f5-calib",
                     "/tmp/mu1320-f5-geom.cfg", "/tmp/mu1320-f5-ctx-mode"],
        "nav_active_ignore_policy": "quarantined (F1 v2 transaction); lifecycle family replaces it",
        "vehicle_tested": False,
    }
    build_report.write_text(json.dumps(report, indent=2) + "\n")

    audit = audit_navjava_ingress.audit(
        JAR, build_report, BASE / "reports" / (REPORT + "-audit.json"),
        ("com/luka/carplay/core/CarPlayApp",) + tuple(rgd + n for n in F5_CLASSES)
        + (rgd + "RendererMapper", rgd + "RendererServer", rgd + "BapPlanner", LIFECYCLE),
        ["Symbol resolution does not replace a J9 runtime test.",
         "The lifecycle family is byte-identical to the vehicle-tested F1 v2 JAR and BapPlanner to the F3 v2 JAR "
         "(checked by the build), not to the F2 JAR used as proven_jar here.",
         "NavActiveIgnore is quarantined by the install transaction; the audit's overlap check covers "
         "the case where it is not.",
         "Renderer/DisplayManager use is intentional in F5 (ClusterPresenter, RenderLink); no stock class is replaced.",
         "Cluster geometry, context switching and VC/HUD display require the vehicle trial."],
        proven_jar=F2_JAR,
        allowed_tokens=("CarplayDSILifecycleController", "Renderer", "DisplayManager"))
    assert audit["status"] == "PASS", audit
    print(json.dumps({key: report[key] for key in
                      ["build_id", "class_count", "jar_sha256", "jar_size", "harness"]}, indent=2))


if __name__ == "__main__":
    main()
