#!/usr/bin/env python3
"""Build the F2 shadow-state JAR and run the offline F2 harness.

The vehicle JAR = the vehicle-run navjava-ingress class set (bus, logger,
TerminalMode entry seam, ingress validator; reused byte for byte) plus the F2
route-state core, the unmodified upstream ManeuverMapper and a shadow listener.
It publishes nothing: no BAP, renderer, display, ownership, cover-art or input.
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
OUT = PRIVATE / "f2-shadow-v1"
STAGE = BASE / "mu1320-f2-shadow-v1"
JAR = STAGE / "carplay_mu1320_f2_shadow_v1.jar.DISABLED"
NAVJAVA_JAR = BASE / "navjava-trial/carplay_mu1320_navjava_ingress_v1.jar.DISABLED"
UPSTREAM_COMMIT = "f36790d450392516ed9cbfab9cc06aa13a08bf31"

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


def main():
    assert not OUT.exists(), "Preserve the existing F2 build; use a new version."
    assert not JAR.exists(), "Never overwrite an issued Java artifact."
    upstream = ROOT / "mib2q-carplay-rgi"
    head = subprocess.check_output(["git", "-C", str(upstream), "rev-parse", "HEAD"], text=True).strip()
    assert head == UPSTREAM_COMMIT, head
    src, classes, test_classes = OUT / "src", OUT / "classes", OUT / "test-classes"
    for path in (src, classes, test_classes):
        path.mkdir(parents=True)

    proven = PRIVATE / "stage2-java/src"
    inputs = {
        "com/luka/carplay/bus/CarplayBus.java": proven / "com/luka/carplay/bus/CarplayBus.java",
        "com/luka/carplay/framework/Log.java": proven / "com/luka/carplay/framework/Log.java",
        "de/audi/app/terminalmode/combi/TerminalModeBapCombi.java":
            proven / "de/audi/app/terminalmode/combi/TerminalModeBapCombi.java",
        "com/luka/carplay/rgd/RgdIngressProbe.java": BASE / "navjava-trial-src/RgdIngressProbe.java",
        "com/luka/carplay/rgd/ManeuverMapper.java":
            upstream / "java_patch/com/luka/carplay/rgd/ManeuverMapper.java",
        "com/luka/carplay/rgd/RouteStateCore.java": BASE / "f2-src/RouteStateCore.java",
        "com/luka/carplay/rgd/F2ShadowProbe.java": BASE / "f2-src/F2ShadowProbe.java",
        "com/luka/carplay/core/CarPlayApp.java": BASE / "f2-src/CarPlayApp.java",
    }
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
        BASE / "reports/f2-shadow-compile.log")

    # Host-only harness and replay tool (Java 8; never packaged).
    host_sources = [BASE / "f2-src/F2Harness.java", BASE / "f2-src/F2Replay.java"]
    run([str(javac), "-source", "1.8", "-target", "1.8", "-Xlint:-options",
         "-classpath", os.pathsep.join([str(classes), str(stock)]),
         "-d", str(test_classes)] + list(map(str, host_sources)))
    harness = run([str(java), "-Xverify:all", "-cp", os.pathsep.join([str(test_classes), str(classes)]),
                   "com.luka.carplay.rgd.F2Harness"], BASE / "reports/f2-harness.txt")
    assert "F2_HARNESS_PASS" in harness

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
    assert not any(name.startswith(("com/luka/carplay/rgd/F2Harness", "com/luka/carplay/rgd/F2Replay"))
                   for name in entries)

    # Classes shared with the vehicle-run navjava JAR must be byte-identical.
    with zipfile.ZipFile(NAVJAVA_JAR) as archive:
        navjava = {name: archive.read(name) for name in archive.namelist() if name.endswith(".class")}
    shared = sorted(name for name in entries if name in navjava
                    and not name.startswith("com/luka/carplay/core/CarPlayApp"))
    identical = {name: entries[name] == navjava[name] for name in shared}
    assert shared and all(identical.values()), identical
    assert any(name.startswith("com/luka/carplay/rgd/RgdIngressProbe") for name in shared)

    build_report = BASE / "reports/f2-shadow-build.json"
    report = {
        "profile": "f2-route-state-shadow",
        "build_id": "MU1320-F2-SHADOW-V1",
        "class_count": len(entries),
        "classes": sorted(entries),
        "source_sha256": {name: sha(path) for name, path in inputs.items()},
        "upstream_commit": UPSTREAM_COMMIT,
        "maneuver_mapper": "unmodified upstream source at upstream_commit",
        "stock_jar_sha256": stock_sha,
        "jar_sha256": sha(JAR),
        "jar_size": JAR.stat().st_size,
        "navjava_vehicle_classes_reused_byte_identical": shared,
        "harness": harness.strip().splitlines()[-2:],
        "nav_active_ignore_policy": "retained-in-place-and-hash-pinned",
        "includes_navigation_ownership_change": False,
        "includes_bap_or_renderer": False,
        "vehicle_tested": False,
    }
    build_report.write_text(json.dumps(report, indent=2) + "\n")

    audit = audit_navjava_ingress.audit(
        JAR, build_report, BASE / "reports/f2-shadow-audit.json",
        ("com/luka/carplay/core/CarPlayApp", "com/luka/carplay/rgd/RgdIngressProbe",
         "com/luka/carplay/rgd/RouteStateCore", "com/luka/carplay/rgd/F2ShadowProbe",
         "com/luka/carplay/rgd/ManeuverMapper"),
        ["Symbol resolution does not replace a J9 runtime test.",
         "The existing NavActiveIgnore behavior is retained, not endorsed or revalidated by this audit.",
         "Shadow mode: BAP, renderer and VC/HUD output are outside this gate (F3/F4)."],
        proven_jar=NAVJAVA_JAR)
    assert audit["status"] == "PASS", audit
    print(json.dumps({key: report[key] for key in
                      ["build_id", "class_count", "jar_sha256", "jar_size", "harness"]}, indent=2))


if __name__ == "__main__":
    main()
