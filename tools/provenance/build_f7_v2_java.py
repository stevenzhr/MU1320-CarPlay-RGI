#!/usr/bin/env python3
"""F7 v2 Java = the F7 v1.1 bytecode with the v2 version names.

B11 is native and B12 is fixed in the scripts (stop/rollback switch BAP off
through the car-proven runtime kill switch and wait for Java before the
renderer is stopped), so no Java logic changes.  The six classes that carry
a version name (BUILD_ID or the runtime workspace) are recompiled:

  CarPlayApp, TouchpadBridge   BUILD_ID                     MU1320-F7-DAILY-V2
  F7Switches.ROOT, StockDisplay.SC_HELPER                   /mnt/app/root/mu1320-rgi-f7-v2
  F5Probe, RendererKeeper      inline the constants above (recompiled, as the
                               F7 v1 build learned from F6 v2's stale F5Probe)

Checks: the F7 v1.1 sources reproduce the F7 v1.1 JAR byte for byte first;
the v2 sources are the v1.1 sources with only the two names replaced; every
recompiled class equals v1.1 under javap -v once the names are mapped back;
all other classes are the v1.1 bytes; no stale version string anywhere.
Harnesses (same set as v1.1): F7 keeper (v2 paths), F1 v2 equivalence,
touchpad, F5 (with the B9 check) and F6V3Replay incl. F6 v3 session D.
"""
import difflib
import hashlib
import json
import os
import re
import sys
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "scripts"))
import audit_navjava_ingress  # noqa: E402
import build_f7_v11_java as v11  # noqa: E402

ROOT, PRIVATE, JDK, VEHICLE = v11.ROOT, v11.PRIVATE, v11.JDK, v11.VEHICLE
OUT = PRIVATE / "f7-daily-v2-java"
STAGE = BASE / "mu1320-f7-daily-v2"
JAR = STAGE / "carplay_mu1320_f7_daily_v2.jar.DISABLED"
V11JAR = BASE / "mu1320-f7-daily-v1.1/carplay_mu1320_f7_daily_v1_1.jar.DISABLED"
V11SRC = PRIVATE / "f7-daily-v1.1-java/src"
OLD_BUILD, OLD_RUNTIME = v11.BUILD_ID, v11.RUNTIME
BUILD_ID = "MU1320-F7-DAILY-V2"
RUNTIME = "mu1320-rgi-f7-v2"
RGD, INPUT = v11.RGD, v11.INPUT
RENAMED = (v11.APP, v11.TOUCH, v11.SWITCHES, v11.DISPLAY)          # carry a name in source
INLINERS = (v11.PROBE, v11.KEEPER)                                 # inline those constants
RECOMPILED = RENAMED + INLINERS
sha, run, entries, owner, javac, unpack = v11.sha, v11.run, v11.entries, v11.owner, v11.javac, v11.unpack


def rename(text):
    text = re.sub(re.escape(OLD_BUILD) + r"(?![\w.])", BUILD_ID, text)
    return re.sub(re.escape(OLD_RUNTIME) + r"(?![\w.])", RUNTIME, text)


def javap_v(path):
    """javap -v -p -c without the file header; v2 names mapped back to v1.1."""
    text = run([JDK / "javap", "-v", "-p", "-c", path]).stdout
    text = "\n".join(l for l in text.splitlines()
                     if not re.match(r"^(Classfile |  Last modified|  MD5 checksum|  Compiled from)", l))
    text = re.sub(re.escape(BUILD_ID) + r"(?![\w.])", OLD_BUILD, text)
    return re.sub(re.escape(RUNTIME) + r"(?![\w.])", OLD_RUNTIME, text)


def main():
    assert not OUT.exists(), "Preserve an existing build directory."
    assert not JAR.exists(), "preserve an existing JAR"
    old_report = json.loads((BASE / "reports/f7-v1.1-build.json").read_text())
    assert sha(V11JAR) == old_report["jar_sha256"], "F7 v1.1 SD folder JAR changed"
    stock = PRIVATE / "MU1320-base.jar"
    assert sha(stock) == old_report["stock_jar_sha256"]
    old = entries(V11JAR)
    OUT.mkdir(parents=True)
    extra = sorted((ROOT / "resource/bundles").glob("*.jar")) + sorted((ROOT / "resource/bundles_prod").glob("*.jar"))
    extra += sorted((PRIVATE / "tools/jxe2jar/libs").glob("org.osgi.*.jar"))
    proven = OUT / "proven-f7-v1.1"
    unpack(old, proven)
    cp = [proven, stock] + extra

    # 1. The v1.1 sources reproduce the v1.1 JAR.
    repro_src = OUT / "repro-src"
    for name in RECOMPILED:
        p = repro_src / (name + ".java")
        p.parent.mkdir(parents=True, exist_ok=True)
        text = (V11SRC / (name + ".java")).read_text()
        for key, digest in old_report["source_sha256"].items():
            if key == name + ".java":
                assert sha(V11SRC / key) == digest, "v1.1 source drift " + key
        p.write_text(text)
    got = javac(repro_src, OUT / "repro-classes", cp, BASE / "reports/f7-v2-repro-compile.log")
    for n, data in got.items():
        assert old.get(n) == data, "v1.1 sources do not reproduce " + n
    reproduced = sorted(got)

    # 2. v2 sources = v1.1 sources with the two names replaced.
    src, classes = OUT / "src", OUT / "classes"
    diffs, renamed_lines = [], {}
    for name in RECOMPILED:
        before = (V11SRC / (name + ".java")).read_text()
        after = rename(before)
        n = sum(1 for a, b in zip(before.splitlines(), after.splitlines()) if a != b)
        assert (n > 0) == (name in RENAMED), (name, n)
        renamed_lines[name] = n
        p = src / (name + ".java")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(after)
        diffs.extend(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                          "f7-v1.1/" + name + ".java", "f7-v2/" + name + ".java"))
    (BASE / "reports/f7-v2-source.diff").write_text("".join(diffs))

    # 3. Compile against the v1.1 classes and assemble.
    rebuilt = javac(src, classes, cp, BASE / "reports/f7-v2-compile.log")
    assert sorted(rebuilt) == reproduced, sorted(set(rebuilt) ^ set(reproduced))
    for n, data in old.items():
        if n not in rebuilt:
            p = classes / n
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
    final = {p.relative_to(classes).as_posix(): p.read_bytes() for p in classes.rglob("*.class")}
    assert sorted(final) == sorted(old), "class set changed"

    # 4. Range checks.
    strings_only, identical = [], []
    for n in sorted(final):
        if final[n] == old[n]:
            identical.append(n)
            continue
        assert owner(n) in RECOMPILED, "unexpected change " + n
        assert javap_v(classes / n) == javap_v(proven / n), "more than version names changed: " + n
        strings_only.append(n)
    for n in final:
        if owner(n) in INLINERS or owner(n) in RENAMED:
            continue
        assert final[n] == old[n], n
    stale = {}
    for n, data in final.items():
        for s in re.findall(rb"mu1320-rgi-f[0-9]-v[0-9.]+|MU1320-F[0-9]-[A-Z]+-V[0-9.]+", data):
            s = s.decode()
            if s not in (RUNTIME, BUILD_ID, "MU1320-F5-VCHUD-V5", "MU1320-F2-SHADOW-V1"):
                stale.setdefault(n, []).append(s)
    assert not stale, stale

    # 5. Harnesses on the delivered classes (the v1.1 set, v2 paths).
    host, hsrc = OUT / "host", OUT / "host-src"
    host.mkdir()
    hsrc.mkdir()
    kh = (BASE / "f7-src/F7KeeperHarness.java").read_text()
    kh2 = kh.replace("/mnt/app/root/mu1320-rgi-f7-v1/", "/mnt/app/root/%s/" % RUNTIME)
    assert kh2.count(RUNTIME) == 3
    (hsrc / "F7KeeperHarness.java").write_text(kh2)
    f5h = PRIVATE / "f6-accept-v3/host-src/F5Harness.java"
    run([JDK / "javac", "-source", "1.8", "-target", "1.8", "-Xlint:-options", "-classpath",
         os.pathsep.join(map(str, [classes, stock])), "-d", host,
         hsrc / "F7KeeperHarness.java", BASE / "f6-v3-src/TouchpadHarness.java", BASE / "f1-src/F1V2Harness.java",
         BASE / "f2-src/F2Harness.java", BASE / "f2-src/F2Replay.java", f5h, BASE / "f5-src/F5Replay.java",
         BASE / "f6-v3-src/F6V3Replay.java"])
    hcp = os.pathsep.join(map(str, [host, classes, stock]))
    java = [JDK / "java", "-Xverify:all", "-cp", hcp]
    keeper = run(java + ["com.luka.carplay.rgd.F7KeeperHarness"], BASE / "reports/f7-v2-keeper-harness.txt").stdout
    f1 = run([JDK / "java", "-Xverify:all", "-cp", host, "F1V2Harness", stock, classes,
              ROOT / "resource/jars/NavActiveIgnore.jar"], BASE / "reports/f7-v2-f1-harness.txt").stdout
    touch = run(java + ["com.luka.carplay.input.TouchpadHarness"], BASE / "reports/f7-v2-touchpad-harness.txt").stdout
    f5 = run(java + ["com.luka.carplay.rgd.F5Harness",
                     VEHICLE / "f2-shadow-v1/armed-9150607/mu1320-f2-frames.cap",
                     VEHICLE / "f2-shadow-v1/armed-9150607/mu1320-f2-state.log",
                     VEHICLE / "f3-bap-v2/armed-9855120/mu1320-f3-frames.cap",
                     VEHICLE / "f3-bap-v2/armed-9855120/mu1320-f3-bap.log",
                     VEHICLE / "f3-bap-v2/armed-9855120/mu1320-f3-state.log",
                     PRIVATE / "f3-bap-v2/classes", PRIVATE / "f5-vchud-v5/f3-tools", stock],
             BASE / "reports/f7-v2-f5-harness.txt").stdout
    assert "B9_ARRIVAL_EXTRA n=14 " in f5, "B9 check did not run"
    args = []
    for label, d, opts in v11.CAPTURES:
        args += ["--", label, VEHICLE / d / "mu1320-f5-frames.cap", VEHICLE / d / "mu1320-f5-bap.log"] + opts
    replay = run(java + ["com.luka.carplay.rgd.F6V3Replay"] + args, BASE / "reports/f7-v2-vehicle-replay.txt").stdout
    assert "F6V3_REPLAY_PASS" in replay

    # 6. JAR, report, link audit.
    STAGE.mkdir(exist_ok=True)
    with zipfile.ZipFile(JAR, "x", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(classes.rglob("*.class")):
            info = zipfile.ZipInfo(p.relative_to(classes).as_posix(), (2026, 9, 27, 0, 0, 0))
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            z.writestr(info, p.read_bytes())
    report = {"build_id": BUILD_ID, "jar_sha256": sha(JAR), "jar_size": JAR.stat().st_size,
              "stock_jar_sha256": sha(stock), "f7_v1_1_jar_sha256": sha(V11JAR), "class_count": len(final),
              "reproduced_before_rename": reproduced, "renamed_source_lines": renamed_lines,
              "f7_v1_1_byte_identical": identical, "version_names_only": strings_only,
              "logic_changed": False,
              "b11": "native (reports/f7-v2-native-build.json)",
              "b12": "scripts: stop/rollback use the runtime BAP kill switch and wait for Java (reports/f7-v2-scripts.diff)",
              "vehicle_tested": False,
              "source_sha256": {p.relative_to(src).as_posix(): sha(p) for p in src.rglob("*.java")},
              "harness": {"keeper": keeper.strip().splitlines()[-1], "f1": f1.strip().splitlines()[-1],
                          "touch": touch.strip().splitlines()[-1], "f5": f5.strip().splitlines()[-1],
                          "vehicle_replay": replay.strip().splitlines()[-1]}}
    reportpath = BASE / "reports/f7-v2-build.json"
    reportpath.write_text(json.dumps(report, indent=2) + "\n")
    audit = audit_navjava_ingress.audit(JAR, reportpath, BASE / "reports/f7-v2-audit.json",
        v11.OWNERS + (INPUT, "de/audi/app/terminalmode/dsi/carplay/"),
        ["Host JVM verification does not replace J9/vehicle validation.",
         "Changes vs F7 v1.1: version names only (BUILD_ID, runtime workspace).",
         "B11 (gate records) is native; B12 (stop releases through Java) is in the scripts."],
        proven_jar=V11JAR, allowed_tokens=("CarplayDSILifecycleController", "Renderer", "DisplayManager"))
    assert audit["status"] == "PASS", audit
    print(json.dumps({k: report[k] for k in ("build_id", "class_count", "jar_sha256", "version_names_only",
                                               "harness")}, indent=2))


if __name__ == "__main__":
    main()
