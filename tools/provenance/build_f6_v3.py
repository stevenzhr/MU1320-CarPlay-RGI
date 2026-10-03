#!/usr/bin/env python3
"""F6 v3 = F6 v2 bytecode + three narrow Java fixes from the F6 v2 car run:

- B8 lanes: TripPlanner.LaneMemory keeps the lane entries of the current route
  by lane index (the upstream hook prunes them by maneuver index); F5BapOutput
  feeds it on every input and uses it only when the snapshot lost the entry.
- B9 arrival: BapPlanner counts the arrive maneuver down with the distance to
  destination when Apple sends dist_to_maneuver 0 (the core holds).
- B7 touchpad: TouchpadGesture thresholds x1.25 (80 % sensitivity).
Plus the version names: StockDisplay helper path, CarPlayApp / TouchpadBridge
BUILD_ID.  No native changes.  Every other class is the F6 v2 JAR byte for
byte; changed methods are checked with javap.  Host checks: F1 v2 lifecycle
equivalence, touchpad harness, the F5 harness and F6V3Replay on the vehicle
captures of the F5 v5 navigation bytecode (F5 v5, F6 v1, F6 v2 B/C).
"""
import difflib
import hashlib
import json
import os
import sys
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
ROOT = BASE.parent
PRIVATE = ROOT / "private-data/mu1320-rgi"
OUT = PRIVATE / "f6-accept-v3"
SRC = BASE / "f6-v3-src"
STAGE = BASE / "mu1320-f6-accept-v3"
JAR = STAGE / "carplay_mu1320_f6_accept_v3.jar.DISABLED"
V2 = BASE / "mu1320-f6-accept-v2"
V2JAR = V2 / "carplay_mu1320_f6_accept_v2.jar.DISABLED"
V2SRC = PRIVATE / "f6-accept-v2/src"
BUILD_ID = "MU1320-F6-ACCEPT-V3"
JDK = PRIVATE / "tools/jxe2jar/jvms/zulu8.78.0.19-ca-jdk8.0.412-macosx_aarch64/zulu-8.jdk/Contents/Home/bin"
VEHICLE = ROOT / "resource/private/vehicle-dump"
sys.path.insert(0, str(BASE / "scripts"))
import bytecode_compare  # noqa: E402
import audit_navjava_ingress  # noqa: E402

RGD = "com/luka/carplay/rgd/"
INPUT = "com/luka/carplay/input/"
REBUILT = (RGD + "TripPlanner", RGD + "BapPlanner", RGD + "F5BapOutput", RGD + "StockDisplay",
           "com/luka/carplay/core/CarPlayApp", INPUT + "TouchpadGesture", INPUT + "TouchpadBridge")
# Methods that may change (substring match on bytecode_compare keys).
ALLOWED = {
    "TripPlanner": ["#public static com.luka.carplay.rgd.TripPlanner$Lanes lanes(",
                    "$Lanes#public java.lang.String describe()"],
    "BapPlanner": ["#public static com.luka.carplay.rgd.BapPlanner$Frame plan("],
    "F5BapOutput": ["#public void onInput(", "#public void onClear(", "#private void start(",
                    "#private void update(", "#public com.luka.carplay.rgd.F5BapOutput("],
}
# (label, directory, extra F6V3Replay options)
CAPTURES = [
    ("f5v5-a", "f5-vchud-v5/armed-5972107", []),
    ("f5v5-b", "f5-vchud-v5/armed-9138299", []),
    ("f6v1-A", "f6-accept-v1/armed-13799568", []),
    # Apple lane event 6 was pruned by the v1.2 hook before reaching Java (navhook v1.3 fixes it).
    ("f6v2-B-apple", "f6-accept-v2/armed-16162960", ["lanes=all-but:6", "arrival=765:781"]),
    ("f6v2-C-google", "f6-accept-v2/armed-10178705", ["lanes=all"]),
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def once(s, old, new):
    assert s.count(old) == 1, old
    return s.replace(old, new, 1)


def run(cmd, log=None):
    import subprocess
    p = subprocess.run(list(map(str, cmd)), text=True, capture_output=True)
    if log:
        log.write_text(p.stdout + p.stderr)
    assert p.returncode == 0, p.stdout[-6000:] + p.stderr[-6000:]
    return p.stdout


def entries(jar):
    with zipfile.ZipFile(jar) as z:
        return {n: z.read(n) for n in z.namelist() if n.endswith(".class")}


def main():
    assert not OUT.exists(), "Preserve an existing build directory."
    assert not JAR.exists(), "Never overwrite an issued artifact."
    v2report = json.loads((BASE / "reports/f6-v2-build.json").read_text())
    assert sha(V2JAR) == v2report["jar_sha256"]
    baseline = entries(V2JAR)
    stock = PRIVATE / "MU1320-base.jar"
    assert sha(stock) == v2report["stock_jar_sha256"]

    src, classes, proven = OUT / "src", OUT / "classes", OUT / "proven"
    for d in (src, classes, proven):
        d.mkdir(parents=True)
    for n, data in baseline.items():
        p = proven / n
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    # (published source name, original text, v3 text)
    inputs = {}
    for name, orig in [("TripPlanner", BASE / "f5-src/TripPlanner.java"),
                       ("F5BapOutput", BASE / "f5-src/F5BapOutput.java"),
                       ("BapPlanner", BASE / "f3-src/BapPlanner.java")]:
        inputs[RGD + name + ".java"] = (orig.read_text(), (SRC / (name + ".java")).read_text())
    for name in ("TouchpadGesture", "TouchpadBridge"):
        inputs[INPUT + name + ".java"] = ((BASE / "f6-v2-src" / (name + ".java")).read_text(),
                                         (SRC / (name + ".java")).read_text())
    old = (V2SRC / (RGD + "StockDisplay.java")).read_text()
    inputs[RGD + "StockDisplay.java"] = (old, once(old, "/mnt/app/root/mu1320-rgi-f6-v2/render/f5_sc.sh",
                                                   "/mnt/app/root/mu1320-rgi-f6-v3/render/f5_sc.sh"))
    old = (V2SRC / "com/luka/carplay/core/CarPlayApp.java").read_text()
    inputs["com/luka/carplay/core/CarPlayApp.java"] = (old, once(
        old, 'public static final String BUILD_ID = "MU1320-F6-ACCEPT-V2";',
        'public static final String BUILD_ID = "%s";' % BUILD_ID))
    # The shipped F5/F3 sources must be what the v2 JAR was built from.
    for rel in (RGD + "TripPlanner.java", RGD + "F5BapOutput.java", RGD + "BapPlanner.java"):
        built = PRIVATE / "f5-vchud-v5/src" / rel
        assert built.read_text() == inputs[rel][0], "v5 source drift: " + rel
    changes = []
    for name, (before, after) in inputs.items():
        p = src / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(after)
        changes.extend(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                            "f6-v2/" + name, "f6-v3/" + name))
    (BASE / "reports/f6-v3-source.diff").write_text("".join(changes))

    cp = [proven, stock] + sorted((ROOT / "resource/bundles").glob("*.jar"))
    cp += sorted((ROOT / "resource/bundles_prod").glob("*.jar"))
    cp += sorted((PRIVATE / "tools/jxe2jar/libs").glob("org.osgi.*.jar"))
    run([JDK / "javac", "-source", "1.4", "-target", "1.4", "-Xlint:-options",
         "-bootclasspath", stock, "-classpath", os.pathsep.join(map(str, cp)),
         "-sourcepath", src, "-d", classes] + sorted(src.rglob("*.java")),
        BASE / "reports/f6-v3-compile.log")
    rebuilt = {p.relative_to(classes).as_posix(): p.read_bytes() for p in classes.rglob("*.class")}
    assert all(n.startswith(REBUILT) for n in rebuilt), sorted(rebuilt)
    for n in baseline:
        if n.startswith(REBUILT):
            assert n in rebuilt, "lost existing class " + n
    for n, data in baseline.items():
        if not n.startswith(REBUILT):
            p = classes / n
            assert not p.exists(), n
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)

    bytecode_compare.JAVAP = JDK / "javap"
    scope = {}
    for outer, allowed in ALLOWED.items():
        same, diff, gone, added, _, _ = bytecode_compare.compare(proven / RGD, classes / RGD, outer)
        assert all(any(k in m for k in allowed) or "access$" in m for m in diff), (outer, diff)
        assert not gone, (outer, gone)
        scope[outer] = {"identical_methods": len(same), "changed_methods": diff, "added": added}
    assert all("LaneMemory" in m or "build(" in m or "lanes(com.luka.carplay.rgd.RouteStateCore, " in m
               or "access$" in m for m in scope["TripPlanner"]["added"]), scope["TripPlanner"]["added"]
    assert all("isArrival(" in m for m in scope["BapPlanner"]["added"]), scope["BapPlanner"]["added"]
    (BASE / "reports/f6-v3-method-scope.json").write_text(json.dumps(scope, indent=2) + "\n")

    host = OUT / "host"
    host.mkdir()
    run([JDK / "javac", "-source", "1.8", "-target", "1.8", "-Xlint:-options", "-classpath",
         os.pathsep.join(map(str, [classes, stock])), "-d", host,
         SRC / "TouchpadHarness.java", BASE / "f1-src/F1V2Harness.java"])
    f1 = run([JDK / "java", "-Xverify:all", "-cp", host, "F1V2Harness", stock,
              classes, ROOT / "resource/jars/NavActiveIgnore.jar"], BASE / "reports/f6-v3-f1-harness.txt")
    touch = run([JDK / "java", "-Xverify:all", "-cp", os.pathsep.join(map(str, [host, classes, stock])),
                 "com.luka.carplay.input.TouchpadHarness"], BASE / "reports/f6-v3-touchpad-harness.txt")
    # F5Harness compares F5 with F3 decisions on the F2 capture.  B9 adds, by
    # design, DIST_TURN calls F3 never sent (the Apple arrive maneuver counted
    # down); they must be the only difference and must decrease.
    harness_src = OUT / "host-src"
    harness_src.mkdir()
    h5 = (BASE / "f5-src/F5Harness.java").read_text()
    h5v3 = once(h5, """        check(f3calls.equals(f5calls), "F2 capture: F5 BAP calls = F3 calls apart from lanes/ETA (" + f3calls.size()""",
                """        {   /* F6 v3 (B9): arrival countdown lines exist only in F5. */
            List<String> extra = new ArrayList<String>(f5calls);
            extra.removeAll(f3calls);
            int last = Integer.MAX_VALUE;
            boolean down = true;
            for (String e : extra) {
                String b = e.substring(e.indexOf(' ') + 1);
                if (!b.startsWith("CALL DIST_TURN ")) { down = false; break; }
                int d = Integer.parseInt(b.substring(15, b.indexOf(' ', 15)));
                if (d >= last) down = false;
                last = d;
            }
            check(down && extra.size() == 14, "F2 capture: B9 adds only a decreasing arrival DIST_TURN (" + extra + ")");
            f5calls.removeAll(extra);
            System.out.println("B9_ARRIVAL_EXTRA n=" + extra.size() + " " + extra);
        }
        check(f3calls.equals(f5calls), "F2 capture: F5 BAP calls = F3 calls apart from lanes/ETA (" + f3calls.size()""")
    (harness_src / "F5Harness.java").write_text(h5v3)
    (BASE / "reports/f6-v3-harness.diff").write_text("".join(difflib.unified_diff(
        h5.splitlines(True), h5v3.splitlines(True), "f5-src/F5Harness.java", "f6-v3/F5Harness.java")))
    run([JDK / "javac", "-source", "1.8", "-target", "1.8", "-Xlint:-options", "-classpath",
         os.pathsep.join(map(str, [classes, stock])), "-d", host,
         BASE / "f2-src/F2Harness.java", BASE / "f2-src/F2Replay.java",
         harness_src / "F5Harness.java", BASE / "f5-src/F5Replay.java", SRC / "F6V3Replay.java"])
    f5 = run([JDK / "java", "-Xverify:all", "-cp", os.pathsep.join(map(str, [host, classes, stock])),
              "com.luka.carplay.rgd.F5Harness",
              VEHICLE / "f2-shadow-v1/armed-9150607/mu1320-f2-frames.cap",
              VEHICLE / "f2-shadow-v1/armed-9150607/mu1320-f2-state.log",
              VEHICLE / "f3-bap-v2/armed-9855120/mu1320-f3-frames.cap",
              VEHICLE / "f3-bap-v2/armed-9855120/mu1320-f3-bap.log",
              VEHICLE / "f3-bap-v2/armed-9855120/mu1320-f3-state.log",
              PRIVATE / "f3-bap-v2/classes", PRIVATE / "f5-vchud-v5/f3-tools", stock],
             BASE / "reports/f6-v3-f5-harness.txt")
    args = []
    for label, d, extra in CAPTURES:
        args += ["--", label, VEHICLE / d / "mu1320-f5-frames.cap", VEHICLE / d / "mu1320-f5-bap.log"] + extra
    replay = run([JDK / "java", "-Xverify:all", "-cp", os.pathsep.join(map(str, [host, classes, stock])),
                  "com.luka.carplay.rgd.F6V3Replay"] + args, BASE / "reports/f6-v3-vehicle-replay.txt")

    STAGE.mkdir(exist_ok=True)
    assert not any(STAGE.iterdir()), "preserve existing SD folder"
    with zipfile.ZipFile(JAR, "x", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(classes.rglob("*.class")):
            info = zipfile.ZipInfo(p.relative_to(classes).as_posix(), (2026, 9, 27, 0, 0, 0))
            info.create_system = 3; info.compress_type = zipfile.ZIP_DEFLATED; info.external_attr = 0o100644 << 16
            z.writestr(info, p.read_bytes())
    final = entries(JAR)
    unchanged = sorted(n for n in baseline if baseline[n] == final.get(n))
    report = {"build_id": BUILD_ID, "jar_sha256": sha(JAR), "jar_size": JAR.stat().st_size,
              "stock_jar_sha256": sha(stock), "f6_v2_jar_sha256": sha(V2JAR), "class_count": len(final),
              "f6_v2_byte_identical": unchanged, "changed_classes": sorted(set(baseline) - set(unchanged)),
              "new_classes": sorted(set(final) - set(baseline)), "native_changed": False, "vehicle_tested": False,
              "backlog": ["B7 touchpad x1.25", "B8 lane memory", "B9 arrival distance"],
              "source_sha256": {p.relative_to(src).as_posix(): sha(p) for p in src.rglob("*.java")},
              "harness": {"f1": f1.strip().splitlines()[-1], "touch": touch.strip().splitlines()[-1],
                          "f5": f5.strip().splitlines()[-1], "vehicle_replay": replay.strip().splitlines()[-1]}}
    reportpath = BASE / "reports/f6-v3-build.json"
    reportpath.write_text(json.dumps(report, indent=2) + "\n")
    audit = audit_navjava_ingress.audit(JAR, reportpath, BASE / "reports/f6-v3-audit.json",
        REBUILT + (INPUT,),
        ["Host JVM verification does not replace J9/vehicle validation.",
         "Changes vs F6 v2: lane memory (B8), arrival distance (B9), touchpad x1.25 (B7), version names.",
         "Lane memory and arrival distance need a short drive with several lane junctions and an Apple arrival."],
        proven_jar=V2JAR, allowed_tokens=("CarplayDSILifecycleController", "Renderer", "DisplayManager"))
    assert audit["status"] == "PASS", audit
    print(json.dumps({k: report[k] for k in ("build_id", "class_count", "jar_sha256", "harness")}, indent=2))


if __name__ == "__main__":
    main()
