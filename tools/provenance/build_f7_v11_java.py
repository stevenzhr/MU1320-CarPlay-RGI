#!/usr/bin/env python3
"""F7 v1.1 Java = F7 v1 bytecode rebased on the F6 v3 Java changes.

Baseline: the F7 v1 JAR (mu1320-f7-daily-v1, offline only).  F7 v1 was built
on F6 v2; F6 closed with v3.  Every class either side changed is merged
three-way from source (git merge-file), never copied as a whole class:

  base   = the F6 v2 sources (what both sides started from)
  ours   = the F7 v1 sources (keeper, switches, touchpad persistent off, ...)
  theirs = the F6 v3 sources (B8 LaneMemory + F5BapOutput wiring, B9 arrival
           fallback in BapPlanner, B7 TouchpadGesture 188/250/38)

Version tokens (BUILD_ID, runtime workspace) are normalised before the merge
and set to the F7 v1.1 values after it; the merge must be conflict-free.
F5Probe, RendererKeeper and F7Switches have no source change beyond the
workspace, but inline constants (helper/keeper paths, BUILD_ID) and are
recompiled, as the F7 v1 build learned from F6 v2's stale F5Probe.

Checks: the F7 v1 and F6 v3 sources reproduce their JARs byte for byte
before merging; the four F6 v3-only classes come out byte-identical to the
F6 v3 JAR; the F7-side classes equal F7 v1 apart from the version strings
(javap -v with the strings mapped back); bytecode_compare method scope
against F7 v1; no stale version string anywhere in the JAR; all other
classes are F7 v1 bytes.  Harnesses: F7 keeper (v1.1 paths), F1 v2
equivalence, touchpad (F6 v3 thresholds), F5 (with the F6 v3 B9 check) and
F6V3Replay over the F6 v3 capture list plus F6 v3 session D.
"""
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
ROOT = BASE.parent
PRIVATE = ROOT / "private-data/mu1320-rgi"
OUT = PRIVATE / "f7-daily-v1.1-java"
STAGE = BASE / "mu1320-f7-daily-v1.1"
JAR = STAGE / "carplay_mu1320_f7_daily_v1_1.jar.DISABLED"
V1JAR = BASE / "mu1320-f7-daily-v1/carplay_mu1320_f7_daily_v1.jar.DISABLED"
V3JAR = BASE / "mu1320-f6-accept-v3/carplay_mu1320_f6_accept_v3.jar.DISABLED"
V2JAR = BASE / "mu1320-f6-accept-v2/carplay_mu1320_f6_accept_v2.jar.DISABLED"
V1SRC = PRIVATE / "f7-daily-v1-java/src"
V3SRC = PRIVATE / "f6-accept-v3/src"
V2SRC = PRIVATE / "f6-accept-v2/src"
BUILD_ID = "MU1320-F7-DAILY-V1.1"
RUNTIME = "mu1320-rgi-f7-v1.1"
JDK = PRIVATE / "tools/jxe2jar/jvms/zulu8.78.0.19-ca-jdk8.0.412-macosx_aarch64/zulu-8.jdk/Contents/Home/bin"
VEHICLE = ROOT / "resource/private/vehicle-dump"
sys.path.insert(0, str(BASE / "scripts"))
import audit_navjava_ingress  # noqa: E402
import build_f6_v3  # noqa: E402
import bytecode_compare  # noqa: E402

RGD = "com/luka/carplay/rgd/"
INPUT = "com/luka/carplay/input/"
PROBE, DISPLAY, KEEPER, SWITCHES = RGD + "F5Probe", RGD + "StockDisplay", RGD + "RendererKeeper", RGD + "F7Switches"
TRIP, BAP, OUTPUT = RGD + "TripPlanner", RGD + "BapPlanner", RGD + "F5BapOutput"
APP = "com/luka/carplay/core/CarPlayApp"
TOUCH, GESTURE = INPUT + "TouchpadBridge", INPUT + "TouchpadGesture"
F7_SIDE = (PROBE, DISPLAY, APP, TOUCH, KEEPER, SWITCHES)
V3_ONLY = (TRIP, BAP, OUTPUT, GESTURE)
OWNERS = F7_SIDE + V3_ONLY
# Session D of F6 v3 (hook v1.3 + v3 Java on the car): lane junctions Apple 2/2, Google 2/2.
CAPTURES = build_f6_v3.CAPTURES + [("f6v3-D", "f6-accept-v3/armed-15691920", ["lanes=all"])]
OLD_STRINGS = {  # every version string of the three sides -> merge token
    "MU1320-F6-ACCEPT-V2": "@BUILD_ID@", "MU1320-F6-ACCEPT-V3": "@BUILD_ID@", "MU1320-F7-DAILY-V1": "@BUILD_ID@",
    "mu1320-rgi-f6-v2": "@RUNTIME@", "mu1320-rgi-f6-v3": "@RUNTIME@", "mu1320-rgi-f7-v1": "@RUNTIME@",
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(cmd, log=None, ok=(0,)):
    p = subprocess.run(list(map(str, cmd)), text=True, capture_output=True)
    if log:
        log.write_text(p.stdout + p.stderr)
    assert p.returncode in ok, p.stdout[-6000:] + p.stderr[-6000:]
    return p


def entries(jar):
    with zipfile.ZipFile(jar) as z:
        return {n: z.read(n) for n in z.namelist() if n.endswith(".class")}


def owner(n):
    return n[:-6].split("$")[0]


def normalise(text):
    for old in sorted(OLD_STRINGS, key=len, reverse=True):
        text = re.sub(re.escape(old) + r"(?![\w.])", OLD_STRINGS[old], text)
    assert "F6-ACCEPT" not in text and "mu1320-rgi-f6" not in text and "F7-DAILY-V1" not in text
    return text


def finalise(text):
    return text.replace("@BUILD_ID@", BUILD_ID).replace("@RUNTIME@", RUNTIME)


def sources():
    """{class: (base F6 v2, ours F7 v1, theirs F6 v3)} source texts; None = class absent."""
    base = {PROBE: BASE / "f5-src/F5Probe.java", TRIP: BASE / "f5-src/TripPlanner.java",
            OUTPUT: BASE / "f5-src/F5BapOutput.java", BAP: BASE / "f3-src/BapPlanner.java",
            DISPLAY: V2SRC / (DISPLAY + ".java"), APP: V2SRC / (APP + ".java"),
            TOUCH: V2SRC / (TOUCH + ".java"), GESTURE: V2SRC / (GESTURE + ".java")}
    assert (BASE / "f6-v2-src/TouchpadBridge.java").read_text() == base[TOUCH].read_text()
    assert (BASE / "f6-v2-src/TouchpadGesture.java").read_text() == base[GESTURE].read_text()
    for name in (TRIP, OUTPUT, BAP):  # what F5 v5 / F6 v2 were built from
        assert (PRIVATE / "f5-vchud-v5/src" / (name + ".java")).read_text() == base[name].read_text(), name
    out = {}
    for name in OWNERS:
        b = base[name].read_text() if name in base else None
        o = (V1SRC / (name + ".java")).read_text() if name in F7_SIDE else b
        t = (V3SRC / (name + ".java")).read_text() if (V3SRC / (name + ".java")).exists() else b
        out[name] = (b, o, t)
    for short in ("TripPlanner", "F5BapOutput", "BapPlanner"):
        assert (BASE / "f6-v3-src" / (short + ".java")).read_text() == out[RGD + short][2], short
    for short in ("TouchpadGesture", "TouchpadBridge"):
        assert (BASE / "f6-v3-src" / (short + ".java")).read_text() == out[INPUT + short][2], short
    for short in ("RendererKeeper", "F7Switches"):
        assert (BASE / "f7-src" / (short + ".java")).read_text() == out[RGD + short][1], short
    return out


def merge(name, b, o, t, work):
    """Three-way merge of normalised texts; returns (merged, how)."""
    if b is None:  # new in F7 v1, absent from F6
        assert t is None
        return normalise(o), "F7 v1 only (new class)"
    nb, no, nt = normalise(b), normalise(o), normalise(t)
    d = work / name.replace("/", ".")
    d.mkdir(parents=True)
    for tag, text in (("base", nb), ("ours", no), ("theirs", nt)):
        (d / tag).write_text(text)
    p = run(["git", "merge-file", "-p", "-L", "f7-v1", "-L", "f6-v2", "-L", "f6-v3",
             d / "ours", d / "base", d / "theirs"], ok=(0, 1))
    assert p.returncode == 0 and "<<<<<<<" not in p.stdout, "merge conflict in " + name + "\n" + p.stdout
    how = {(False, False): "unchanged", (True, False): "F7 v1 only", (False, True): "F6 v3 only",
           (True, True): "both (three-way)"}[(no != nb, nt != nb)]
    if how == "F6 v3 only":
        assert p.stdout == nt
    if how in ("F7 v1 only", "unchanged"):
        assert p.stdout == no
    return p.stdout, how


def javac(src, out, cp, log, files=None):
    out.mkdir(parents=True, exist_ok=True)
    run([JDK / "javac", "-source", "1.4", "-target", "1.4", "-Xlint:-options",
         "-bootclasspath", cp[1], "-classpath", os.pathsep.join(map(str, cp)),
         "-sourcepath", src, "-d", out] + (files or sorted(Path(src).rglob("*.java"))), log)
    return {p.relative_to(out).as_posix(): p.read_bytes() for p in Path(out).rglob("*.class")}


def unpack(classes, d):
    for n, data in classes.items():
        p = d / n
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)


def javap_v(path):
    """javap -v -p -c without the file header; version strings mapped back to F7 v1."""
    text = run([JDK / "javap", "-v", "-p", "-c", path]).stdout
    text = "\n".join(l for l in text.splitlines()
                     if not re.match(r"^(Classfile |  Last modified|  MD5 checksum|  Compiled from)", l))
    text = re.sub(re.escape(BUILD_ID) + r"(?![\w.])", "MU1320-F7-DAILY-V1", text)
    return re.sub(re.escape(RUNTIME) + r"(?![\w.])", "mu1320-rgi-f7-v1", text)


def main():
    assert not OUT.exists(), "Preserve an existing build directory."
    assert not STAGE.exists() or not any(STAGE.iterdir()), "preserve existing SD folder"
    v1report = json.loads((BASE / "reports/f7-v1-build.json").read_text())
    v3report = json.loads((BASE / "reports/f6-v3-build.json").read_text())
    v2report = json.loads((BASE / "reports/f6-v2-build.json").read_text())
    assert sha(V1JAR) == v1report["jar_sha256"] and sha(V3JAR) == v3report["jar_sha256"]
    assert sha(V2JAR) == v2report["jar_sha256"] == v1report["f6_v2_jar_sha256"] == v3report["f6_v2_jar_sha256"]
    stock = PRIVATE / "MU1320-base.jar"
    assert sha(stock) == v1report["stock_jar_sha256"] == v3report["stock_jar_sha256"]
    v1, v3, v2 = entries(V1JAR), entries(V3JAR), entries(V2JAR)
    # Each side left the other side's classes at the F6 v2 bytes.
    for n in v2:
        if owner(n) in V3_ONLY:
            assert v1[n] == v2[n], "F7 v1 changed " + n
        if owner(n) in (PROBE, KEEPER, SWITCHES):
            assert v3.get(n) == v2[n], "F6 v3 changed " + n
    OUT.mkdir(parents=True)
    extra = sorted((ROOT / "resource/bundles").glob("*.jar")) + sorted((ROOT / "resource/bundles_prod").glob("*.jar"))
    extra += sorted((PRIVATE / "tools/jxe2jar/libs").glob("org.osgi.*.jar"))
    proven = {"f7v1": OUT / "proven-f7-v1", "f6v3": OUT / "proven-f6-v3"}
    unpack(v1, proven["f7v1"])
    unpack(v3, proven["f6v3"])
    src_all = sources()

    # 1. Both sides' sources reproduce their JARs.
    reproduced = {}
    for tag, jar_classes, names, side in [("f7v1", v1, F7_SIDE, 1), ("f6v3", v3, (DISPLAY, APP, TOUCH) + V3_ONLY, 2)]:
        rsrc = OUT / ("repro-src-" + tag)
        for name in names:
            p = rsrc / (name + ".java")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(src_all[name][side])
        got = javac(rsrc, OUT / ("repro-classes-" + tag), [proven[tag], stock] + extra,
                    BASE / ("reports/f7-v1.1-repro-%s-compile.log" % tag))
        for n, data in got.items():
            if tag == "f7v1" or owner(n) != PROBE:
                assert jar_classes.get(n) == data, "%s sources do not reproduce %s" % (tag, n)
        reproduced[tag] = sorted(got)

    # 2. Three-way merge.
    src, classes = OUT / "src", OUT / "classes"
    merged, table, diffs = {}, {}, []
    for name in OWNERS:
        b, o, t = src_all[name]
        text, how = merge(name, b, o, t, OUT / "merge")
        text = finalise(text)
        merged[name] = text
        table[name] = how
        p = src / (name + ".java")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        diffs.extend(difflib.unified_diff(o.splitlines(True), text.splitlines(True),
                                          "f7-v1/" + name + ".java", "f7-v1.1/" + name + ".java"))
    for name in V3_ONLY:
        assert merged[name] == src_all[name][2], name
    (BASE / "reports/f7-v1.1-source.diff").write_text("".join(diffs))
    v3diff = []
    for name in OWNERS:
        b, o, t = src_all[name]
        if t is not None:
            v3diff.extend(difflib.unified_diff(t.splitlines(True), merged[name].splitlines(True),
                                               "f6-v3/" + name + ".java", "f7-v1.1/" + name + ".java"))
    (BASE / "reports/f7-v1.1-vs-f6-v3-source.diff").write_text("".join(v3diff))

    # 3. Compile against the F7 v1 classes and assemble.
    rebuilt = javac(src, classes, [proven["f7v1"], stock] + extra, BASE / "reports/f7-v1.1-compile.log")
    assert all(owner(n) in OWNERS for n in rebuilt), sorted(rebuilt)
    for n in v1:
        if owner(n) in OWNERS:
            assert n in rebuilt, "lost existing class " + n
    for n, data in v1.items():
        if n not in rebuilt:
            p = classes / n
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
    final = {p.relative_to(classes).as_posix(): p.read_bytes() for p in classes.rglob("*.class")}

    # 4. Range checks.
    v3_names = sorted(n for n in v3 if owner(n) in V3_ONLY)
    assert sorted(n for n in final if owner(n) in V3_ONLY) == v3_names
    for n in v3_names:
        assert final[n] == v3[n], "not the F6 v3 bytes: " + n
    f7_side = sorted(n for n in final if owner(n) in F7_SIDE)
    assert f7_side == sorted(n for n in v1 if owner(n) in F7_SIDE)
    strings_only = []
    for n in f7_side:
        if final[n] != v1[n]:
            assert javap_v(classes / n) == javap_v(proven["f7v1"] / n), "more than version strings changed: " + n
            strings_only.append(n)
    bytecode_compare.JAVAP = JDK / "javap"
    scope = {}
    for outer in sorted({o.rsplit("/", 1)[1] for o in OWNERS}):
        pkg = RGD if (RGD + outer) in OWNERS else (INPUT if (INPUT + outer) in OWNERS else "com/luka/carplay/core/")
        same, diff, gone, added, _, _ = bytecode_compare.compare(proven["f7v1"] / pkg, classes / pkg, outer)
        assert not gone, (outer, gone)
        if outer in build_f6_v3.ALLOWED:
            assert all(any(k in m for k in build_f6_v3.ALLOWED[outer]) or "access$" in m for m in diff), (outer, diff)
        elif outer == "TouchpadGesture":  # B7 thresholds (bytes already equal F6 v3)
            assert diff and all("sample(" in m for m in diff), diff
        else:  # F7 side: only methods that load a version string may differ
            for m in diff:
                cls = m.split("#", 1)[0]
                code = dict((k, v) for k, v in bytecode_compare.methods(classes / pkg / (cls + ".class")).items())
                meth = m.split("#", 1)[1]
                assert any(BUILD_ID in a or RUNTIME in a for _, a in code[meth]), (outer, m)
        scope[outer] = {"identical_methods": len(same), "changed_methods": diff, "added": added}
    assert all("LaneMemory" in m or "build(" in m or "lanes(com.luka.carplay.rgd.RouteStateCore, " in m
               or "access$" in m for m in scope["TripPlanner"]["added"]), scope["TripPlanner"]["added"]
    assert all("isArrival(" in m for m in scope["BapPlanner"]["added"]), scope["BapPlanner"]["added"]
    (BASE / "reports/f7-v1.1-method-scope.json").write_text(json.dumps(scope, indent=2) + "\n")
    stale = {}
    for n, data in final.items():
        for s in re.findall(rb"mu1320-rgi-f[0-9]-v[0-9.]+|MU1320-F[0-9]-[A-Z]+-V[0-9.]+", data):
            s = s.decode()
            # MU1320-F5-VCHUD-V5 / -F2-SHADOW-V1 are Java-bound log names kept since F5 / F2.
            if s not in (RUNTIME, BUILD_ID, "MU1320-F5-VCHUD-V5", "MU1320-F2-SHADOW-V1"):
                stale.setdefault(n, []).append(s)
    assert not stale, stale

    # 5. Harnesses on the delivered classes.
    host, hsrc = OUT / "host", OUT / "host-src"
    host.mkdir()
    hsrc.mkdir()
    kh = (BASE / "f7-src/F7KeeperHarness.java").read_text()
    kh11 = kh.replace("/mnt/app/root/mu1320-rgi-f7-v1/", "/mnt/app/root/%s/" % RUNTIME)
    assert kh11.count(RUNTIME) == 3
    (hsrc / "F7KeeperHarness.java").write_text(kh11)
    f5h = PRIVATE / "f6-accept-v3/host-src/F5Harness.java"
    h5diff = "".join(difflib.unified_diff((BASE / "f5-src/F5Harness.java").read_text().splitlines(True),
                                          f5h.read_text().splitlines(True), "f5-src/F5Harness.java", "f6-v3/F5Harness.java"))
    assert h5diff == (BASE / "reports/f6-v3-harness.diff").read_text(), "F5 harness is not the F6 v3 one"
    (BASE / "reports/f7-v1.1-harness.diff").write_text(h5diff + "".join(difflib.unified_diff(
        kh.splitlines(True), kh11.splitlines(True), "f7-src/F7KeeperHarness.java", "f7-v1.1/F7KeeperHarness.java")))
    run([JDK / "javac", "-source", "1.8", "-target", "1.8", "-Xlint:-options", "-classpath",
         os.pathsep.join(map(str, [classes, stock])), "-d", host,
         hsrc / "F7KeeperHarness.java", BASE / "f6-v3-src/TouchpadHarness.java", BASE / "f1-src/F1V2Harness.java",
         BASE / "f2-src/F2Harness.java", BASE / "f2-src/F2Replay.java", f5h, BASE / "f5-src/F5Replay.java",
         BASE / "f6-v3-src/F6V3Replay.java"])
    hcp = os.pathsep.join(map(str, [host, classes, stock]))
    java = [JDK / "java", "-Xverify:all", "-cp", hcp]
    keeper = run(java + ["com.luka.carplay.rgd.F7KeeperHarness"], BASE / "reports/f7-v1.1-keeper-harness.txt").stdout
    f1 = run([JDK / "java", "-Xverify:all", "-cp", host, "F1V2Harness", stock, classes,
              ROOT / "resource/jars/NavActiveIgnore.jar"], BASE / "reports/f7-v1.1-f1-harness.txt").stdout
    touch = run(java + ["com.luka.carplay.input.TouchpadHarness"], BASE / "reports/f7-v1.1-touchpad-harness.txt").stdout
    f5 = run(java + ["com.luka.carplay.rgd.F5Harness",
                     VEHICLE / "f2-shadow-v1/armed-9150607/mu1320-f2-frames.cap",
                     VEHICLE / "f2-shadow-v1/armed-9150607/mu1320-f2-state.log",
                     VEHICLE / "f3-bap-v2/armed-9855120/mu1320-f3-frames.cap",
                     VEHICLE / "f3-bap-v2/armed-9855120/mu1320-f3-bap.log",
                     VEHICLE / "f3-bap-v2/armed-9855120/mu1320-f3-state.log",
                     PRIVATE / "f3-bap-v2/classes", PRIVATE / "f5-vchud-v5/f3-tools", stock],
             BASE / "reports/f7-v1.1-f5-harness.txt").stdout
    assert "B9_ARRIVAL_EXTRA n=14 " in f5, "B9 check did not run"
    args = []
    for label, d, opts in CAPTURES:
        args += ["--", label, VEHICLE / d / "mu1320-f5-frames.cap", VEHICLE / d / "mu1320-f5-bap.log"] + opts
    replay = run(java + ["com.luka.carplay.rgd.F6V3Replay"] + args, BASE / "reports/f7-v1.1-vehicle-replay.txt").stdout
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
    final = entries(JAR)
    unchanged = sorted(n for n in v1 if v1[n] == final.get(n))
    report = {"build_id": BUILD_ID, "jar_sha256": sha(JAR), "jar_size": JAR.stat().st_size,
              "stock_jar_sha256": sha(stock), "f7_v1_jar_sha256": sha(V1JAR), "f6_v3_jar_sha256": sha(V3JAR),
              "f6_v2_jar_sha256": sha(V2JAR), "class_count": len(final),
              "merge": table,
              "f7_v1_byte_identical": unchanged, "changed_classes": sorted(set(v1) - set(unchanged)),
              "new_classes": sorted(set(final) - set(v1)),
              "f6_v3_byte_identical": v3_names, "f7_side_version_strings_only": strings_only,
              "reproduced_before_merge": reproduced, "native_changed": "see reports/f7-v1.1-native-build.json",
              "vehicle_tested": False,
              "backlog": ["B7 touchpad x1.25 (F6 v3)", "B8 lane memory (F6 v3)", "B9 arrival distance (F6 v3)"],
              "source_sha256": {p.relative_to(src).as_posix(): sha(p) for p in src.rglob("*.java")},
              "harness": {"keeper": keeper.strip().splitlines()[-1], "f1": f1.strip().splitlines()[-1],
                          "touch": touch.strip().splitlines()[-1], "f5": f5.strip().splitlines()[-1],
                          "vehicle_replay": replay.strip().splitlines()[-1]}}
    reportpath = BASE / "reports/f7-v1.1-build.json"
    reportpath.write_text(json.dumps(report, indent=2) + "\n")
    audit = audit_navjava_ingress.audit(JAR, reportpath, BASE / "reports/f7-v1.1-audit.json",
        OWNERS + (INPUT, "de/audi/app/terminalmode/dsi/carplay/"),
        ["Host JVM verification does not replace J9/vehicle validation.",
         "Changes vs F7 v1: F6 v3 lane memory (B8), arrival distance (B9), touchpad x1.25 (B7) and version names.",
         "Keeper, launcher and always-on gate still need the F7 parked session P; B9 needs one Apple arrival."],
        proven_jar=V1JAR, allowed_tokens=("CarplayDSILifecycleController", "Renderer", "DisplayManager"))
    assert audit["status"] == "PASS", audit
    print(json.dumps({k: report[k] for k in ("build_id", "class_count", "jar_sha256", "merge", "changed_classes",
                                               "new_classes", "harness")}, indent=2))


if __name__ == "__main__":
    main()
