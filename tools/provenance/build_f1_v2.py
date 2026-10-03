#!/usr/bin/env python3
"""Build F1 v2: NavActiveIgnore isolation with the vehicle-tested Stage2 family.

F1 v1 overrode one jxe2jar-converted stock nested class and the Audi
smartphone interface hung at start-up on the car. v2 ships no new bytecode:
the 13 CarplayDSILifecycleController family classes are copied byte for byte
from the Stage2 v2 archive that already ran on this vehicle. The build proves

* provenance: the archive bytes equal a fresh compile of the Stage2 source,
* scope: normalized bytecode differs from stock only in the reviewed methods,
* behaviour: the -Xverify:all host harness (F1V2Harness) passes.
"""
import difflib
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
PRIVATE = BASE.parent / "private-data" / "mu1320-rgi"
ROOT = BASE.parent
sys.path.insert(0, str(BASE / "scripts"))
from bytecode_compare import compare  # noqa: E402

OUT = PRIVATE / "f1-v2"
STAGE = BASE / "f1-trial-v2"
JAR = STAGE / "carplay_mu1320_f1_navi_v2.jar.DISABLED"
STAGE2_ZIP = ROOT / "archive/trial-zips/MU1320-RGI-stage2-java-passive-v2.zip"
STAGE2_JAR_ENTRY = "mu1320-stage2-v2/carplay_mu1320_stage2.jar.DISABLED"
STAGE2_JAR_SHA256 = "f128a9486ad8c7f81c85afcb43a0e14534018a04d4513b8e14617461015cf852"
FAMILY = "de/audi/app/terminalmode/dsi/carplay/CarplayDSILifecycleController"
SOURCE = PRIVATE / "stage2-java/src/de/audi/app/terminalmode/dsi/carplay/CarplayDSILifecycleController.java"
JDK = PRIVATE / "tools/jxe2jar/jvms/zulu8.78.0.19-ca-jdk8.0.412-macosx_aarch64/zulu-8.jdk/Contents/Home/bin"

# Reviewed in reports/F1-V2-REVIEW.md. Any other difference fails the build.
C = "CarplayDSILifecycleController"
REVIEWED = {
    "intended": [
        C + "$DSICarplayListenerImpl#private de.audi.app.terminalmode.dsi.IAppState[] convertAppState(org.dsi.ifc.carplay.AppState[]);",
    ],
    "stage2_touch_guard_without_debug_logs": [
        C + "$TerminalModeDSIKeyEventsController#public void updateTouchEvents(de.audi.app.terminalmode.keyevents.TouchEvent[]);",
    ],
    "equivalent_switch_layout_harness_checked": [
        C + "$CarplayDSIController#private int mapButtonId(int);",
        C + "$DSICarplayListenerImpl#private de.audi.app.terminalmode.events.PlaybackInfoChangedEvent$PlaybackState convert(int);",
        C + "$TerminalModeDSIKeyEventsController#private int getDSITouchInputId(int);",
        C + "$TerminalModeDSIKeyEventsController#private int[] calcSecondCorr(int, int, int, int);",
    ],
    "equivalent_early_return_or_byte_local": [
        C + "$CarplayDSIController#public void startService(de.audi.app.terminalmode.dsi.IDSIAppState[], de.audi.app.terminalmode.dsi.IDSIResource[]);",
        C + "$DSICarplayListenerImpl#private void notifyPlayPosition(de.audi.app.terminalmode.events.TrackPlayPositionEvent);",
        C + "$DSICarplayListenerImpl#public void updateCallState(org.dsi.ifc.carplay.CallState[], int);",
        C + "$DSICarplayListenerImpl#public void updateMainAudioType(int, int);",
        C + "$DSICarplayListenerImpl#public void updateMode(org.dsi.ifc.carplay.Resource[], org.dsi.ifc.carplay.AppState[], int);",
        C + "$DSICarplayListenerImpl#public void updateTextInputState(int, int);",
        C + "$TerminalModeDSIKeyEventsController#public void updateKey(de.audi.app.terminalmode.keyevents.Key, de.audi.app.terminalmode.keyevents.KeyState);",
    ],
    "synthetic_outer_reference_in_constructors": [
        C + "#public de.audi.app.terminalmode.dsi.carplay.CarplayDSILifecycleController(de.audi.app.terminalmode.IContext, de.audi.app.terminalmode.dsi.carplay.IDSICarplayTransferObjectFactory, de.audi.app.terminalmode.dsi.carplay.DSICarplaySafe, de.audi.app.terminalmode.dsi.carplay.CarplayDSILifecycleController$DSICarplayListenerImpl, de.audi.app.terminalmode.dsi.carplay.DSICarplaySafeProxy);",
    ],
}
ANON_CONSTRUCTOR_PREFIX = C + "$DSICarplayListenerImpl$anon#de.audi.app.terminalmode.dsi.carplay.CarplayDSILifecycleController$DSICarplayListenerImpl$anon("


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    assert not OUT.exists(), "Preserve the existing F1 v2 build; use a new version."
    assert not JAR.exists(), "Never overwrite an issued Java artifact."
    stock = PRIVATE / "MU1320-base.jar"
    stock_sha = json.loads((BASE / "reports/java-mu1320-build.json").read_text())["stock_sha256"]
    assert sha(stock.read_bytes()) == stock_sha

    with zipfile.ZipFile(STAGE2_ZIP) as outer:
        stage2_jar = outer.read(STAGE2_JAR_ENTRY)
    assert sha(stage2_jar) == STAGE2_JAR_SHA256, "must be the Stage2 JAR that ran on the vehicle"
    (OUT / "v2/" ).mkdir(parents=True)
    import io
    family = {}
    with zipfile.ZipFile(io.BytesIO(stage2_jar)) as archive:
        for name in archive.namelist():
            if name.startswith(FAMILY) and name.endswith(".class"):
                family[name] = archive.read(name)
    assert len(family) == 13, sorted(family)
    for name, data in family.items():
        target = OUT / "v2" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    # Provenance: a fresh standalone compile of the Stage2 source is byte-identical.
    recompiled = OUT / "recompiled"
    recompiled.mkdir()
    result = subprocess.run([str(JDK / "javac"), "-source", "1.4", "-target", "1.4", "-Xlint:-options",
                             "-bootclasspath", str(stock), "-d", str(recompiled), str(SOURCE)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    rebuilt = {p.relative_to(recompiled).as_posix(): p.read_bytes() for p in recompiled.rglob("*.class")}
    assert rebuilt == family, "Stage2 archive family differs from its source"

    # Scope: method-level normalized comparison against stock.
    stock_dir = OUT / "stock"
    with zipfile.ZipFile(stock) as archive:
        for name in archive.namelist():
            if name.startswith(FAMILY) and name.endswith(".class"):
                target = stock_dir / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(name))
    carplay = "de/audi/app/terminalmode/dsi/carplay"
    same, diff, only_stock, only_new, a, b = compare(stock_dir / carplay, OUT / "v2" / carplay, C)
    reviewed = {key for keys in REVIEWED.values() for key in keys}
    unexplained = [k for k in diff if k not in reviewed and not k.startswith(ANON_CONSTRUCTOR_PREFIX)]
    assert not unexplained, unexplained
    assert reviewed <= set(diff), sorted(reviewed - set(diff))
    # Structural-only: private inner constructors take the outer reference twice
    # (explicit this$0 in the Stage2 source), and the stock anonymous touch
    # comparator became the named TouchXComparator.
    for key in only_stock + only_new:
        assert ("#de.audi.app" in key or "#private de.audi.app" in key or "TouchXComparator" in key
                or key.endswith("compare(java.lang.Object, java.lang.Object);")), key
    lines = []
    for key in diff:
        lines.append("===== " + key + "\n")
        left = [f"{o} {x}\n" for o, x in a[key][0]] if len(a[key]) == 1 else [repr(a[key]) + "\n"]
        right = [f"{o} {x}\n" for o, x in b[key][0]] if len(b[key]) == 1 else [repr(b[key]) + "\n"]
        lines += difflib.unified_diff(left, right, "stock", "f1-v2", n=1)
    lines += ["ONLY_STOCK " + k + "\n" for k in only_stock] + ["ONLY_V2 " + k + "\n" for k in only_new]
    (BASE / "reports/f1-v2-bytecode.diff").write_text("".join(lines))

    tests = OUT / "harness"
    tests.mkdir()
    result = subprocess.run([str(JDK / "javac"), "-nowarn", "-d", str(tests), str(BASE / "f1-src/F1V2Harness.java")],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    result = subprocess.run([str(JDK / "java"), "-Xverify:all", "-cp", str(tests), "F1V2Harness", str(stock),
                             str(OUT / "v2"), str(ROOT / "resource/jars/NavActiveIgnore.jar")],
                            capture_output=True, text=True)
    (BASE / "reports/f1-v2-harness.txt").write_text(result.stdout + result.stderr)
    assert result.returncode == 0 and "F1_V2_EQUIVALENCE_TESTS_PASS" in result.stdout, result.stdout + result.stderr

    for archive_path in sorted((ROOT / "resource/jars").glob("*.jar")):
        with zipfile.ZipFile(archive_path) as archive:
            assert not set(family) & set(archive.namelist()), archive_path

    STAGE.mkdir(exist_ok=True)
    assert not any(STAGE.iterdir()), "Preserve existing staged files; use a new version."
    with zipfile.ZipFile(JAR, "x", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(family):
            entry = zipfile.ZipInfo(name, (2026, 9, 25, 0, 0, 0))
            entry.create_system = 3
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, family[name])
    with zipfile.ZipFile(JAR) as archive:
        assert archive.testzip() is None
        assert {n: archive.read(n) for n in archive.namelist()} == family

    report = {
        "profile": "f1-v2-stage2-lifecycle-family",
        "build_id": "MU1320-F1-NAVI-V2",
        "classes": sorted(family),
        "class_sha256": {n: sha(d) for n, d in sorted(family.items())},
        "source": str(SOURCE.relative_to(BASE)),
        "source_sha256": sha(SOURCE.read_bytes()),
        "vehicle_tested_origin": {"archive": STAGE2_ZIP.name, "jar_sha256": STAGE2_JAR_SHA256,
                                  "result": "reports/stage2-vehicle-v2.json"},
        "stock_jar_sha256": stock_sha,
        "identical_methods": len(same),
        "reviewed_differences": REVIEWED,
        "jar_sha256": sha(JAR.read_bytes()),
        "jar_size": JAR.stat().st_size,
        "host_harness": (BASE / "reports/f1-v2-harness.txt").read_text().strip().splitlines()[-1],
        "new_bytecode_on_vehicle": False,
        "evidence_log": "none (no new code); acceptance by boot/CarPlay session, archive scan and NAVI/phone/Siri observations",
        "vehicle_tested": False,
    }
    (BASE / "reports/f1-v2-build.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ["build_id", "identical_methods", "jar_sha256", "jar_size", "host_harness"]}, indent=2))


if __name__ == "__main__":
    main()
