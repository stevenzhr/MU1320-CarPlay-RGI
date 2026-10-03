#!/usr/bin/env python3
"""F7 v1.1 native = the F7 v1 hook + navhook v1.3 lane fix (patch 0004).

F7 v1 was built on navhook v1.2 (F6 v2 lineage); F6 closed with navhook v1.3.
Steps, all with the pinned toolchain image:

1. Rebuild the F7 v1 hook exactly as scripts/build_f7_native.py did (navhook
   v1.2 tree + f7-src/trial_gate.{c,h} + the bus.c live-DIO guard) and require
   the F7 v1 SHA-256 from reports/f7-v1-native-build.json.
2. Apply only patches/0004 (rgd_prune_stale_lane_cache() returns false) to a
   copy of that tree; rgd_hook.c must equal the navhook v1.3 one byte for
   byte.  Built and ABI-checked as an intermediate artifact ("0004 only").
3. The shipped tree differs from step 2 in one line: the gate's persistent
   off switch follows the new workspace (f7-v1.1-src/trial_gate.c,
   /mnt/app/root/mu1320-rgi-f7-v1.1/off-native).  Without it "off native"
   would write a file the hook never reads.
build_hook.sh rejects emutls, eager constructors and a non-compiler
.init_array; every undefined dynamic symbol must exist in the vehicle's
libc.so.3 / libsocket.so.3.  f7_spawn is carried from F7 v1 unchanged.
"""
import difflib
import hashlib
import json
import shutil
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "scripts"))
import build_f7_native as f7  # noqa: E402
import build_navhook_v13 as v13  # noqa: E402

PRIVATE = f7.PRIVATE
OUT = PRIVATE / "f7-daily-v1.1-native"
SRC = BASE / "f7-v1.1-src"
V1_REPORT = BASE / "reports/f7-v1-native-build.json"
REPORT = BASE / "reports/f7-v1.1-native-build.json"
V1_STAGE = BASE / "mu1320-f7-daily-v1"
RGD = v13.RGD
OLD_OFF = '#define F7_OFF_PERSIST "/mnt/app/root/mu1320-rgi-f7-v1/off-native"\n'
NEW_OFF = '#define F7_OFF_PERSIST "/mnt/app/root/mu1320-rgi-f7-v1.1/off-native"\n'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def f7_tree(dest, gate_dir):
    """navhook v1.2 tree + F7 gate + live-DIO guard (the build_f7_native.py recipe)."""
    f7.copy_tree(dest)
    framework = dest / "hook/framework"
    shutil.copyfile(gate_dir / "trial_gate.c", framework / "trial_gate.c")
    shutil.copyfile(gate_dir / "trial_gate.h", framework / "trial_gate.h")
    bus = framework / "bus.c"
    text = f7.once(bus.read_text(), '#include "bus.h"\n', '#include "bus.h"\n#include "trial_gate.h"\n')
    text = f7.once(text,
                   "        while (!g_shutdown && fd < 0) {\n            fd = try_connect_once();\n",
                   "        while (!g_shutdown && fd < 0) {\n"
                   "            /* MU1320 F7 live-DIO guard: only the newest active DIO generation\n"
                   "             * (re)connects; an older one that is still alive stops here instead of\n"
                   "             * taking Java's single-accept bus back every second. */\n"
                   "            if (!trial_gate_is_current()) {\n"
                   "                LOG_DEBUG(LOG_MODULE, \"superseded generation pid=%d; not connecting\", (int)getpid());\n"
                   "                usleep(2000 * 1000);\n"
                   "                continue;\n"
                   "            }\n"
                   "            fd = try_connect_once();\n")
    bus.write_text(text)


def apply_0004(tree):
    rgd = tree / RGD
    text = rgd.read_text()
    assert text.count(v13.OLD) == 1, "prune function differs from the reviewed text"
    rgd.write_text(text.replace(v13.OLD, v13.NEW, 1))


def build(tree, log):
    so = v13.build(tree, log)  # asserts rc 0 and "emutls=0 init_array=compiler-only"
    return so


def tree_diff(a, b):
    """Relative paths of sources that differ between two trees (build/ ignored)."""
    out = []
    for p in sorted(a.rglob("*")):
        rel = p.relative_to(a)
        if p.is_file() and rel.parts[0] != "build":
            if (b / rel).read_bytes() != p.read_bytes():
                out.append(rel.as_posix())
    extra = [p.relative_to(b).as_posix() for p in b.rglob("*")
             if p.is_file() and p.relative_to(b).parts[0] != "build" and not (a / p.relative_to(b)).exists()]
    return out + extra


def main():
    assert not OUT.exists(), "Preserve an existing private build; use a new version."
    v1 = json.loads(V1_REPORT.read_text())
    v1_sha = v1["artifacts"]["libcarplay_hook.so"]["sha256"]
    assert sha(V1_STAGE / "libcarplay_hook.so") == v1_sha, "F7 v1 SD folder hook changed"
    assert (SRC / "trial_gate.h").read_bytes() == (f7.SRC / "trial_gate.h").read_bytes()
    gate_v1 = (f7.SRC / "trial_gate.c").read_text()
    assert gate_v1.count(OLD_OFF) == 1
    assert (SRC / "trial_gate.c").read_text() == gate_v1.replace(OLD_OFF, NEW_OFF), "gate source drift"
    OUT.mkdir(parents=True)

    # 1. F7 v1, byte for byte.
    repro = OUT / "repro-f7-v1"
    f7_tree(repro, f7.SRC)
    got = sha(build(repro, OUT / "repro-build.log"))
    assert got == v1_sha, "sources no longer reproduce the F7 v1 hook: " + got

    # 2. + 0004 only.
    only = OUT / "f7-v1+0004"
    f7_tree(only, f7.SRC)
    apply_0004(only)
    assert tree_diff(repro, only) == [RGD], tree_diff(repro, only)
    assert (only / RGD).read_bytes() == (PRIVATE / "navhook-v13-build/src" / RGD).read_bytes(), \
        "rgd_hook.c differs from navhook v1.3"
    rgd_diff = "".join(difflib.unified_diff((repro / RGD).read_text().splitlines(True),
                                            (only / RGD).read_text().splitlines(True), "a/" + RGD, "b/" + RGD))
    assert rgd_diff == (BASE / "reports/navhook-v13-rgd.diff").read_text(), "0004 hunk differs"
    only_so = build(only, OUT / "build-0004-only.log")

    # 3. Shipped: + the workspace path of the persistent off switch.
    src = OUT / "src"
    f7_tree(src, SRC)
    apply_0004(src)
    assert tree_diff(only, src) == ["hook/framework/trial_gate.c"], tree_diff(only, src)
    assert tree_diff(repro, src) == ["hook/framework/trial_gate.c", RGD], tree_diff(repro, src)
    hook = build(src, OUT / "build.log")
    gate_diff = "".join(difflib.unified_diff(gate_v1.splitlines(True), (SRC / "trial_gate.c").read_text().splitlines(True),
                                             "f7-v1/trial_gate.c", "f7-v1.1/trial_gate.c"))
    (BASE / "reports/f7-v1.1-native.diff").write_text(rgd_diff + gate_diff)

    # 4. ELF checks and vehicle-library symbol audit.
    shutil.copyfile(hook, OUT / "libcarplay_hook.so")
    checks = f7.docker([(OUT, "/out")],
                       "NM=arm-unknown-nto-qnx6.5.0eabi-nm; RE=arm-unknown-nto-qnx6.5.0eabi-readelf; "
                       "echo emutls=$($NM /out/libcarplay_hook.so | grep -ci emutls || true); "
                       "echo init_array=$($RE -W -S /out/libcarplay_hook.so | awk '$2==\".init_array\"{print $6}')",
                       OUT / "elf-checks.txt")
    assert "emutls=0" in checks and "init_array=000004" in checks, checks
    exports = set()
    for lib in [f7.LIBS / "proc/boot/libc.so.3", f7.LIBS / "lib/libsocket.so.3"]:
        exports |= set(f7.elf_symbols(lib)[1])
    undefined, _, needed = f7.elf_symbols(hook)
    missing = sorted(n for n, weak in undefined.items() if not weak and n not in exports)
    assert not missing, missing
    v1_undefined = set(v1["dynamic_imports"]["libcarplay_hook.so"]["undefined"])
    assert set(undefined) <= v1_undefined, sorted(set(undefined) - v1_undefined)

    old_syms, _ = v13.symbols(repro)
    mid_syms, _ = v13.symbols(only)
    new_syms, sections = v13.symbols(src)
    (OUT / "sections.txt").write_text(sections)

    def changes(a, b):
        return {k: [a.get(k), b.get(k)] for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)}

    vs_v1 = changes(old_syms, new_syms)
    real = {k for k in vs_v1 if ".part." not in k and "initialized." not in k}
    assert real == {"write_bus_snapshot_from_cache"}, vs_v1
    assert changes(mid_syms, new_syms) == {}, changes(mid_syms, new_syms)

    spawn = V1_STAGE / "f7_spawn"
    assert sha(spawn) == v1["artifacts"]["f7_spawn"]["sha256"]
    report = {
        "version": "F7 v1.1 native",
        "image_id": f7.IMAGE,
        "base": {"f7_v1_hook_sha256": v1_sha, "reproduced_bit_for_bit": True,
                 "recipe": "scripts/build_f7_native.py (navhook v1.2 tree + f7-src gate + bus.c live-DIO guard)"},
        "patch": "patches/0004-navhook-lane-cache-no-maneuver-prune.patch (rgd_hook.c == navhook v1.3 rgd_hook.c)",
        "intermediate_0004_only": {"sha256": sha(only_so), "size": only_so.stat().st_size},
        "workspace_path_change": "trial_gate.c F7_OFF_PERSIST -> /mnt/app/root/mu1320-rgi-f7-v1.1/off-native "
                                 "(one line; follows the new runtime workspace)",
        "sources": {RGD: sha(src / RGD), "trial_gate.c": sha(SRC / "trial_gate.c"),
                    "trial_gate.h": sha(SRC / "trial_gate.h"), "bus.c": sha(src / "hook/framework/bus.c")},
        "symbol_size_changes_vs_f7_v1": vs_v1,
        "symbol_size_changes_vs_0004_only": {},
        "artifacts": {"libcarplay_hook.so": {"sha256": sha(hook), "size": hook.stat().st_size},
                      "f7_spawn": {"sha256": sha(spawn), "size": spawn.stat().st_size,
                                   "carried_from": "mu1320-f7-daily-v1 (unchanged)"}},
        "dynamic_imports": {"libcarplay_hook.so": {"needed": needed, "undefined": sorted(undefined)}},
        "missing_in_vehicle_libs": missing,
        "emutls": 0, "init_array": "000004", "constructor_added": False,
        "vehicle_tested": False,
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("intermediate_0004_only", "artifacts", "symbol_size_changes_vs_f7_v1")},
                     indent=2))


if __name__ == "__main__":
    main()
