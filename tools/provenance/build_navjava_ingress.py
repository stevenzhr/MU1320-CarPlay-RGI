#!/usr/bin/env python3
"""Build the receive-only native-to-Java ingress trial.

The vehicle artifact contains only the already vehicle-proven bus/logger and
TerminalMode entry seam plus the new parser. It deliberately excludes every
BAP, renderer, display, navigation-ownership, cover-art and input class.
"""
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
OUT = PRIVATE / "navjava-ingress-v1"
STAGE = BASE / "navjava-trial"
JAR = STAGE / "carplay_mu1320_navjava_ingress_v1.jar.DISABLED"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    assert not OUT.exists(), "Preserve the existing ingress build; use a new version."
    assert not JAR.exists(), "Never overwrite an issued Java artifact."
    src = OUT / "src"
    classes = OUT / "classes"
    test_classes = OUT / "test-classes"
    src.mkdir(parents=True)
    classes.mkdir()
    test_classes.mkdir()

    proven = PRIVATE / "stage2-java/src"
    inputs = {
        "com/luka/carplay/bus/CarplayBus.java": proven / "com/luka/carplay/bus/CarplayBus.java",
        "com/luka/carplay/framework/Log.java": proven / "com/luka/carplay/framework/Log.java",
        "de/audi/app/terminalmode/combi/TerminalModeBapCombi.java":
            proven / "de/audi/app/terminalmode/combi/TerminalModeBapCombi.java",
        "com/luka/carplay/core/CarPlayApp.java": BASE / "navjava-trial-src/CarPlayApp.java",
        "com/luka/carplay/rgd/RgdIngressProbe.java": BASE / "navjava-trial-src/RgdIngressProbe.java",
    }
    for name, source in inputs.items():
        assert source.is_file(), source
        target = src / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

    stock = PRIVATE / "MU1320-base.jar"
    stock_sha = json.loads((BASE / "reports/java-mu1320-build.json").read_text())["stock_sha256"]
    assert sha(stock) == stock_sha
    javac = (PRIVATE / "tools/jxe2jar/jvms/"
             "zulu8.78.0.19-ca-jdk8.0.412-macosx_aarch64/"
             "zulu-8.jdk/Contents/Home/bin/javac")
    java = javac.with_name("java")
    cp = [stock]
    cp += sorted((ROOT / "resource/bundles").glob("*.jar"))
    cp += sorted((ROOT / "resource/bundles_prod").glob("*.jar"))
    cp += sorted((PRIVATE / "tools/jxe2jar/libs").glob("org.osgi.*.jar"))
    sources = sorted(src.rglob("*.java"))
    command = [str(javac), "-source", "1.4", "-target", "1.4", "-Xlint:-options",
               "-bootclasspath", str(stock), "-classpath", os.pathsep.join(map(str, cp)),
               "-sourcepath", str(src), "-d", str(classes)] + list(map(str, sources))
    compiled = subprocess.run(command, text=True, capture_output=True)
    (BASE / "reports/navjava-ingress-compile.log").write_text(compiled.stdout + compiled.stderr)
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr

    harness = BASE / "navjava-trial-src/RgdIngressProbeHarness.java"
    harness_compile = subprocess.run(
        [str(javac), "-source", "1.4", "-target", "1.4", "-Xlint:-options",
         "-bootclasspath", str(stock), "-classpath", os.pathsep.join([str(classes)] + list(map(str, cp))),
         "-d", str(test_classes), str(harness)], text=True, capture_output=True)
    assert harness_compile.returncode == 0, harness_compile.stdout + harness_compile.stderr
    tested = subprocess.run(
        [str(java), "-cp", os.pathsep.join([str(test_classes), str(classes), str(stock)]),
         "com.luka.carplay.rgd.RgdIngressProbeHarness"], text=True, capture_output=True)
    (BASE / "reports/navjava-ingress-parser-tests.txt").write_text(tested.stdout + tested.stderr)
    assert tested.returncode == 0 and "RGD_INGRESS_PARSER_TESTS_PASS" in tested.stdout

    STAGE.mkdir(exist_ok=True)
    assert not any(STAGE.iterdir()), "Preserve existing staged files; use a new version."
    with zipfile.ZipFile(JAR, "x", zipfile.ZIP_DEFLATED) as archive:
        for item in sorted(classes.rglob("*.class")):
            entry = zipfile.ZipInfo(str(item.relative_to(classes)), (2026, 9, 24, 0, 0, 0))
            entry.create_system = 3
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, item.read_bytes())

    entries = []
    with zipfile.ZipFile(JAR) as archive:
        assert archive.testzip() is None
        entries = sorted(name for name in archive.namelist() if name.endswith(".class"))
    forbidden = ("BAPBridge", "RouteGuidance", "Renderer", "ScreenModule",
                 "DisplayManager", "CarplayDSILifecycleController", "AppState",
                 "CoverArt", "Cursor", "SteeringWheel")
    assert not any(any(word in name for word in forbidden) for name in entries)
    assert any(name.endswith("RgdIngressProbe.class") for name in entries)

    report = {
        "profile": "native-to-java-receive-and-parse-only",
        "build_id": "MU1320-NAVJAVA-INGRESS-V1",
        "class_count": len(entries),
        "classes": entries,
        "source_sha256": {name: sha(path) for name, path in inputs.items()},
        "stock_jar_sha256": stock_sha,
        "jar_sha256": sha(JAR),
        "jar_size": JAR.stat().st_size,
        "parser_host_tests": "PASS",
        "nav_active_ignore_policy": "retained-in-place-and-hash-pinned",
        "includes_navigation_ownership_change": False,
        "includes_bap_or_renderer": False,
        "vehicle_tested": False,
    }
    (BASE / "reports/navjava-ingress-build.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in
                      ["build_id", "class_count", "jar_sha256", "jar_size", "parser_host_tests"]},
                     indent=2))


if __name__ == "__main__":
    main()
