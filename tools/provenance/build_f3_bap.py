#!/usr/bin/env python3
"""Build the F3 BAP trial JAR and run the offline F3 harness.

The vehicle JAR =
  * the F2 class set that ran on the car (bus, logger, TerminalMode entry seam,
    ingress validator, RouteStateCore, F2ShadowProbe, unmodified upstream
    ManeuverMapper), recompiled and checked byte-identical to the F2 JAR;
  * the 13 CarplayDSILifecycleController classes copied byte for byte from the
    vehicle-tested F1 v2 JAR (CarPlay NAVI app state -> 0, the NavActiveIgnore
    replacement);
  * new F3 classes: BapPlanner, BapSink, F3BapOutput, NaviBapSink, F3BapProbe,
    and the F3 CarPlayApp entry.
It publishes navigation BAP FctIDs 17/39/23/18/49/55/21 only while CarPlay has
an active route and the stock navigation has none (yield mode).  No renderer,
display context, input, cover-art, lane, ETA or text FctIDs.
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
# v1 ran on the car on 2026-09-25 (HOLD_OFF: stock check used the persistent
# route); its outputs keep the unversioned report names f3-bap-*.
VERSION = 2
V = "v%d" % VERSION
BUILD_ID = "MU1320-F3-BAP-V%d" % VERSION
REPORT = "f3-bap-" + V
OUT = PRIVATE / ("f3-bap-" + V)
STAGE = BASE / ("mu1320-f3-bap-" + V)
JAR = STAGE / ("carplay_mu1320_f3_bap_%s.jar.DISABLED" % V)
F2_JAR = BASE / "mu1320-f2-shadow-v1/carplay_mu1320_f2_shadow_v1.jar.DISABLED"
F1_JAR = BASE / "f1-trial-v2/carplay_mu1320_f1_navi_v2.jar.DISABLED"
UPSTREAM_COMMIT = "f36790d450392516ed9cbfab9cc06aa13a08bf31"
LIFECYCLE = "de/audi/app/terminalmode/dsi/carplay/CarplayDSILifecycleController"
F2_VEHICLE = ROOT / "resource/private/vehicle-dump/f2-shadow-v1/armed-9150607"

sys.path.insert(0, str(BASE / "scripts"))
import audit_navjava_ingress  # noqa: E402


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def run(command, log=None):
    done = subprocess.run(command, text=True, capture_output=True)
    if log is not None:
        log.write_text(done.stdout + done.stderr)
    assert done.returncode == 0, done.stdout + done.stderr
    return done.stdout


def main():
    assert not OUT.exists(), "Preserve the existing F3 build; use a new version."
    assert not JAR.exists(), "Never overwrite an issued Java artifact."
    upstream = ROOT / "mib2q-carplay-rgi"
    head = subprocess.check_output(["git", "-C", str(upstream), "rev-parse", "HEAD"], text=True).strip()
    assert head == UPSTREAM_COMMIT, head

    f1_build = json.loads((BASE / "reports/f1-v2-build.json").read_text())
    f1_vehicle = json.loads((BASE / "reports/f1-v2-vehicle.json").read_text())
    f2_build = json.loads((BASE / "reports/f2-shadow-build.json").read_text())
    f2_vehicle = json.loads((BASE / "reports/f2-shadow-vehicle-v1.json").read_text())
    assert f1_vehicle["status"] == "F1_V2_NAVI_SEAM_AND_ROLLBACK_VERIFIED"
    assert f2_vehicle["status"] == "F2_SHADOW_STATE_AND_ROLLBACK_VERIFIED"
    assert sha(F1_JAR) == f1_build["jar_sha256"], "must be the F1 v2 JAR that ran on the car"
    assert sha(F2_JAR) == f2_build["jar_sha256"], "must be the F2 JAR that ran on the car"

    src, classes, test_classes = OUT / "src", OUT / "classes", OUT / "test-classes"
    for path in (src, classes, test_classes):
        path.mkdir(parents=True)

    proven = PRIVATE / "stage2-java/src"
    rgd = "com/luka/carplay/rgd/"
    inputs = {
        "com/luka/carplay/bus/CarplayBus.java": proven / "com/luka/carplay/bus/CarplayBus.java",
        "com/luka/carplay/framework/Log.java": proven / "com/luka/carplay/framework/Log.java",
        "de/audi/app/terminalmode/combi/TerminalModeBapCombi.java":
            proven / "de/audi/app/terminalmode/combi/TerminalModeBapCombi.java",
        rgd + "RgdIngressProbe.java": BASE / "navjava-trial-src/RgdIngressProbe.java",
        rgd + "ManeuverMapper.java": upstream / "java_patch/com/luka/carplay/rgd/ManeuverMapper.java",
        rgd + "RouteStateCore.java": BASE / "f2-src/RouteStateCore.java",
        rgd + "F2ShadowProbe.java": BASE / "f2-src/F2ShadowProbe.java",
        "com/luka/carplay/core/CarPlayApp.java": BASE / "f3-src/CarPlayApp.java",
    }
    for name in ["BapPlanner", "BapSink", "F3BapOutput", "NaviBapSink", "F3BapProbe"]:
        inputs[rgd + name + ".java"] = BASE / "f3-src" / (name + ".java")
    for name, source in inputs.items():
        assert source.is_file(), source
        target = src / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

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

    # F1 v2 lifecycle family: vehicle-tested bytes, never recompiled here.
    with zipfile.ZipFile(F1_JAR) as archive:
        family = {name: archive.read(name) for name in archive.namelist() if name.endswith(".class")}
    assert len(family) == 13 and all(name.startswith(LIFECYCLE) for name in family), sorted(family)
    for name, data in family.items():
        assert not (classes / name).exists(), name
        (classes / name).parent.mkdir(parents=True, exist_ok=True)
        (classes / name).write_bytes(data)

    # Host-only harness and replay tools (Java 8; never packaged).
    host_sources = [BASE / "f2-src/F2Harness.java", BASE / "f2-src/F2Replay.java",
                    BASE / "f3-src/F3Replay.java", BASE / "f3-src/F3Harness.java"]
    run([str(javac), "-source", "1.8", "-target", "1.8", "-Xlint:-options",
         "-classpath", os.pathsep.join([str(classes), str(stock)]),
         "-d", str(test_classes)] + list(map(str, host_sources)))
    harness = run([str(java), "-Xverify:all",
                   "-cp", os.pathsep.join([str(test_classes), str(classes), str(stock)]),
                   "com.luka.carplay.rgd.F3Harness",
                   str(F2_VEHICLE / "mu1320-f2-frames.cap"), str(F2_VEHICLE / "mu1320-f2-state.log")],
                  BASE / "reports" / (REPORT + "-harness.txt"))
    assert "F3_HARNESS_PASS" in harness

    STAGE.mkdir(exist_ok=True)
    assert not any(STAGE.iterdir()), "Preserve existing staged files; use a new version."
    with zipfile.ZipFile(JAR, "x", zipfile.ZIP_DEFLATED) as archive:
        for item in sorted(classes.rglob("*.class")):
            entry = zipfile.ZipInfo(str(item.relative_to(classes)), (2026, 9, 25, 0, 0, 0))
            entry.create_system = 3
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, item.read_bytes())
    with zipfile.ZipFile(JAR) as archive:
        assert archive.testzip() is None
        entries = {name: archive.read(name) for name in archive.namelist() if name.endswith(".class")}
    assert not any("Harness" in name or "Replay" in name for name in entries)

    # Every class shared with a vehicle-run JAR must be byte-identical to it.
    with zipfile.ZipFile(F2_JAR) as archive:
        f2 = {name: archive.read(name) for name in archive.namelist() if name.endswith(".class")}
    shared_f2 = sorted(name for name in entries if name in f2
                       and not name.startswith("com/luka/carplay/core/CarPlayApp"))
    assert len(shared_f2) == len(f2) - 1, sorted(set(f2) - set(shared_f2))
    assert all(entries[name] == f2[name] for name in shared_f2), [n for n in shared_f2 if entries[n] != f2[n]]
    assert all(entries[name] == data for name, data in family.items())
    fresh = sorted(name for name in entries if name not in f2 and name not in family)
    fresh_expected = {"com/luka/carplay/core/CarPlayApp.class"}
    assert all(name.startswith((rgd + "BapPlanner", rgd + "BapSink", rgd + "F3BapOutput",
                                rgd + "NaviBapSink", rgd + "F3BapProbe"))
               or name in fresh_expected for name in fresh), fresh

    build_report = BASE / "reports" / (REPORT + "-build.json")
    report = {
        "profile": "f3-bap-yield",
        "build_id": BUILD_ID,
        "class_count": len(entries),
        "classes": sorted(entries),
        "fresh_classes": fresh,
        "v1_vehicle_result": "HOLD_OFF reason=STOCK_ROUTE for the whole session: RouteManager.getRoute() is the persistent route",
        "source_sha256": {name: sha(path) for name, path in inputs.items()},
        "upstream_commit": UPSTREAM_COMMIT,
        "maneuver_mapper": "unmodified upstream source at upstream_commit",
        "stock_jar_sha256": stock_sha,
        "jar_sha256": sha(JAR),
        "jar_size": JAR.stat().st_size,
        "f2_vehicle_classes_reused_byte_identical": shared_f2,
        "f1_v2_lifecycle_classes_copied_byte_identical": sorted(family),
        "f1_v2_jar_sha256": sha(F1_JAR),
        "f2_jar_sha256": sha(F2_JAR),
        "harness": harness.strip().splitlines()[-2:],
        "bap_fctids": [17, 39, 23, 18, 49, 55, 21],
        "stock_coexistence": "yield: publish only while stock DSIResponseContainer.isRgActive()==false; "
                             "silent release (no teardown) whenever stock has or may have a route",
        "kill_switch": "/tmp/mu1320-f3-bap-off",
        "nav_active_ignore_policy": "quarantined (F1 v2 transaction); lifecycle family replaces it",
        "includes_renderer": False,
        "vehicle_tested": False,
    }
    build_report.write_text(json.dumps(report, indent=2) + "\n")

    audit = audit_navjava_ingress.audit(
        JAR, build_report, BASE / "reports" / (REPORT + "-audit.json"),
        ("com/luka/carplay/core/CarPlayApp", rgd + "BapPlanner", rgd + "BapSink", rgd + "F3BapOutput",
         rgd + "NaviBapSink", rgd + "F3BapProbe", LIFECYCLE),
        ["Symbol resolution does not replace a J9 runtime test.",
         "The lifecycle family is byte-identical to the vehicle-tested F1 v2 JAR (checked by the build), "
         "not to the F2 JAR used as proven_jar here.",
         "NavActiveIgnore is quarantined by the install transaction; the audit's overlap check covers "
         "the case where it is not.",
         "BAP output is verified offline only; VC/HUD display requires the vehicle trial."],
        proven_jar=F2_JAR, allowed_tokens=("CarplayDSILifecycleController",))
    assert audit["status"] == "PASS", audit
    print(json.dumps({key: report[key] for key in
                      ["build_id", "class_count", "jar_sha256", "jar_size", "harness"]}, indent=2))


if __name__ == "__main__":
    main()
