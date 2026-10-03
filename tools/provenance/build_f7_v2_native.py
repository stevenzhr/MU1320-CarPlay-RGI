#!/usr/bin/env python3
"""F7 v2 native = the F7 v1.1 hook + the B11 gate fix.

F7 v1.1 car session P4 (2026-09-27): the gate's write_small() wrote
"<path>.<pid>" and renamed it; /tmp is /dev/shmem on this unit and has no
rename(), so gate.last / gate.strikes never existed and the crash guard and
the live-DIO guard were inert (BACKLOG B11).  Steps, all with the pinned
toolchain image:

1. Rebuild the F7 v1.1 hook exactly as scripts/build_f7_v11_native.py did
   (F7 v1 tree + f7-v1.1-src gate + patch 0004) and require the F7 v1.1
   SHA-256 from reports/f7-v1.1-native-build.json.
2. The shipped tree differs from step 1 in hook/framework/trial_gate.c only
   (f7-v2-src/trial_gate.c): write_small() writes in place, and the
   persistent off switch follows the v2 workspace.  Nothing else.
build_hook.sh rejects emutls, eager constructors and a non-compiler
.init_array; every undefined dynamic symbol must exist in the vehicle's
libc.so.3 / libsocket.so.3 and be a subset of v1.1's (rename drops out).
f7_spawn is carried from F7 v1 unchanged.
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
import build_f7_v11_native as v11  # noqa: E402
import build_navhook_v13 as v13  # noqa: E402

PRIVATE = f7.PRIVATE
OUT = PRIVATE / "f7-daily-v2-native"
SRC = BASE / "f7-v2-src"
V11_SRC = BASE / "f7-v1.1-src"
V11_REPORT = BASE / "reports/f7-v1.1-native-build.json"
REPORT = BASE / "reports/f7-v2-native-build.json"
V11_STAGE = BASE / "mu1320-f7-daily-v1.1"
V1_STAGE = BASE / "mu1320-f7-daily-v1"
GATE = "hook/framework/trial_gate.c"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    assert not OUT.exists(), "Preserve an existing private build; use a new version."
    old = json.loads(V11_REPORT.read_text())
    old_sha = old["artifacts"]["libcarplay_hook.so"]["sha256"]
    assert sha(V11_STAGE / "libcarplay_hook.so") == old_sha, "F7 v1.1 SD folder hook changed"
    assert (SRC / "trial_gate.h").read_bytes() == (V11_SRC / "trial_gate.h").read_bytes()
    gate_old = (V11_SRC / "trial_gate.c").read_text()
    gate_new = (SRC / "trial_gate.c").read_text()
    assert "rename(" in gate_old and "rename(" not in gate_new.split("*/", 1)[1].replace("rename()", "")
    OUT.mkdir(parents=True)

    # 1. F7 v1.1, byte for byte.
    repro = OUT / "repro-f7-v1.1"
    v11.f7_tree(repro, V11_SRC)
    v11.apply_0004(repro)
    got = sha(v11.build(repro, OUT / "repro-build.log"))
    assert got == old_sha, "sources no longer reproduce the F7 v1.1 hook: " + got

    # 2. Shipped: only the gate source differs.
    src = OUT / "src"
    v11.f7_tree(src, SRC)
    v11.apply_0004(src)
    assert v11.tree_diff(repro, src) == [GATE], v11.tree_diff(repro, src)
    hook = v11.build(src, OUT / "build.log")
    gate_diff = "".join(difflib.unified_diff(gate_old.splitlines(True), gate_new.splitlines(True),
                                             "f7-v1.1/trial_gate.c", "f7-v2/trial_gate.c"))
    (BASE / "reports/f7-v2-native.diff").write_text(gate_diff)

    # 3. ELF checks and vehicle-library symbol audit.
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
    old_undefined = set(old["dynamic_imports"]["libcarplay_hook.so"]["undefined"])
    assert set(undefined) <= old_undefined, sorted(set(undefined) - old_undefined)
    dropped = sorted(old_undefined - set(undefined))  # rename stays: other hook code uses it

    old_syms, _ = v13.symbols(repro)
    new_syms, sections = v13.symbols(src)
    (OUT / "sections.txt").write_text(sections)
    changes = {k: [old_syms.get(k), new_syms.get(k)] for k in sorted(set(old_syms) | set(new_syms))
               if old_syms.get(k) != new_syms.get(k)}
    real = {k for k in changes if ".part." not in k and "initialized." not in k and ".isra." not in k
            and ".constprop." not in k}
    # write_small is static and may be inlined; whatever moved must be gate code.
    assert real <= {"write_small", "decide_once"}, changes

    spawn = V1_STAGE / "f7_spawn"
    assert sha(spawn) == old["artifacts"]["f7_spawn"]["sha256"]
    report = {
        "version": "F7 v2 native",
        "image_id": f7.IMAGE,
        "base": {"f7_v1_1_hook_sha256": old_sha, "reproduced_bit_for_bit": True,
                 "recipe": "scripts/build_f7_v11_native.py (F7 v1 tree + f7-v1.1-src gate + patch 0004)"},
        "change": "trial_gate.c only: write_small() writes LAST/STRIKES in place (O_TRUNC), no temp+rename "
                  "(/tmp = /dev/shmem has no rename; BACKLOG B11); F7_OFF_PERSIST follows the v2 workspace",
        "sources": {"trial_gate.c": sha(SRC / "trial_gate.c"), "trial_gate.h": sha(SRC / "trial_gate.h"),
                    "bus.c": sha(src / "hook/framework/bus.c"), v13.RGD: sha(src / v13.RGD)},
        "symbol_size_changes_vs_f7_v1_1": changes,
        "undefined_dropped_vs_f7_v1_1": dropped,
        "artifacts": {"libcarplay_hook.so": {"sha256": sha(hook), "size": hook.stat().st_size},
                      "f7_spawn": {"sha256": sha(spawn), "size": spawn.stat().st_size,
                                   "carried_from": "mu1320-f7-daily-v1 (unchanged)"}},
        "dynamic_imports": {"libcarplay_hook.so": {"needed": needed, "undefined": sorted(undefined)}},
        "missing_in_vehicle_libs": missing,
        "emutls": 0, "init_array": "000004", "constructor_added": False,
        "vehicle_tested": False,
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("artifacts", "symbol_size_changes_vs_f7_v1_1",
                                             "undefined_dropped_vs_f7_v1_1")}, indent=2))


if __name__ == "__main__":
    main()
