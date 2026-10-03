#!/usr/bin/env python3
"""F7 v1 native: the F1-F6 navigation hook with the F7 daily gate, plus the
renderer launcher f7_spawn.

1. The navhook source tree that produced the car-run hook (F2-F6, SHA
   ad87795a...) is rebuilt unchanged and must reproduce those bytes.
2. A second copy swaps framework/trial_gate.{c,h} for f7-src (same entry
   points, so hook_framework.c is unchanged) and adds the live-DIO guard to
   the bus connector: a superseded DIO generation stops (re)connecting.
3. f7_spawn.c is compiled with the same toolchain image.
Every undefined dynamic symbol of both artifacts must be exported by the
vehicle's libc.so.3 / libsocket.so.3 (resource/native-libs).
"""
import difflib
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
ROOT = BASE.parent
PRIVATE = ROOT / "private-data/mu1320-rgi"
NAVHOOK = PRIVATE / "navhook-v1-build/src"
OUT = PRIVATE / "f7-daily-v1-native"
SRC = BASE / "f7-src"
IMAGE = "sha256:e52565b1f62dab0f93f12532d52611b94e90b89e4da04f972b11f54eaeb6a05d"
CAR_HOOK_SHA = "ad87795a05227e09c57a72e773449a8126b4509f6d982e9ed1128edb5a385e1d"
LIBS = ROOT / "resource/native-libs"
REPORT = BASE / "reports/f7-v1-native-build.json"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def once(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new, 1)


def run(cmd, log):
    p = subprocess.run(list(map(str, cmd)), capture_output=True, text=True)
    log.write_text(p.stdout + p.stderr)
    assert p.returncode == 0, p.stdout[-3000:] + p.stderr[-3000:]
    return p.stdout


def elf_symbols(path):
    """(undefined {name: weak}, exported names, DT_NEEDED) from the dynamic segment."""
    import sys
    if str(PRIVATE / "python") not in sys.path:
        sys.path.append(str(PRIVATE / "python"))  # pinned pyelftools 0.31 (pure Python)
    from elftools.elf.elffile import ELFFile
    from elftools.elf.dynamic import DynamicSegment
    undefined, exported, needed = {}, [], []
    with open(path, "rb") as stream:
        elf = ELFFile(stream)
        dyn = next(s for s in elf.iter_segments() if isinstance(s, DynamicSegment))
        needed = [t.needed for t in dyn.iter_tags() if t.entry.d_tag == "DT_NEEDED"]
        for sym in dyn.iter_symbols():
            if not sym.name:
                continue
            bind = sym["st_info"]["bind"]
            if sym["st_shndx"] == "SHN_UNDEF":
                undefined[sym.name] = bind == "STB_WEAK"
            elif bind in ("STB_GLOBAL", "STB_WEAK"):
                exported.append(sym.name)
    return undefined, exported, needed


def copy_tree(dest):
    shutil.copytree(NAVHOOK, dest, ignore=shutil.ignore_patterns("build"))
    (dest / "build").mkdir()


def docker(mounts, script, log):
    cmd = ["docker", "run", "--rm", "--network=none", "--platform=linux/amd64"]
    for host, guest in mounts:
        cmd += ["-v", "%s:%s" % (host, guest)]
    cmd += [IMAGE, "bash", "-c", "set -e; export PATH=/opt/qnx650/host/linux/x86/usr/bin:$PATH; " + script]
    return run(cmd, log)


def main():
    assert not OUT.exists(), "Preserve an existing build; use a new version."
    OUT.mkdir(parents=True)

    # 1. Reproduce the car-run hook.
    repro = OUT / "repro"
    copy_tree(repro)
    run(["/bin/bash", repro / "scripts/build_hook.sh"], OUT / "repro-build.log")
    assert sha(repro / "build/libcarplay_hook.so") == CAR_HOOK_SHA, "navhook sources no longer reproduce the car hook"

    # 2. F7 gate + live-DIO guard.
    src = OUT / "src"
    copy_tree(src)
    framework = src / "hook/framework"
    shutil.copyfile(SRC / "trial_gate.c", framework / "trial_gate.c")
    shutil.copyfile(SRC / "trial_gate.h", framework / "trial_gate.h")
    bus = framework / "bus.c"
    original = bus.read_text()
    text = once(original, '#include "bus.h"\n', '#include "bus.h"\n#include "trial_gate.h"\n')
    text = once(text,
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
    gate_diff = "".join(difflib.unified_diff(
        (NAVHOOK / "hook/framework/trial_gate.c").read_text().splitlines(True),
        (SRC / "trial_gate.c").read_text().splitlines(True), "navhook/trial_gate.c", "f7/trial_gate.c"))
    bus_diff = "".join(difflib.unified_diff(original.splitlines(True), text.splitlines(True),
                                            "navhook/bus.c", "f7/bus.c"))
    (BASE / "reports/f7-v1-native.diff").write_text(bus_diff + gate_diff)
    run(["/bin/bash", src / "scripts/build_hook.sh"], OUT / "build.log")
    hook = src / "build/libcarplay_hook.so"

    # 3. Launcher.
    spawn_dir = OUT / "spawn"
    spawn_dir.mkdir()
    shutil.copyfile(SRC / "f7_spawn.c", spawn_dir / "f7_spawn.c")
    docker([(spawn_dir, "/src")],
           "arm-unknown-nto-qnx6.5.0eabi-gcc -O2 -std=gnu99 -Wall -Wextra -Werror /src/f7_spawn.c -o /src/f7_spawn",
           OUT / "spawn-build.log")
    spawn = spawn_dir / "f7_spawn"

    # 4. Symbol audit against the vehicle libraries (stripped: read the dynamic segment).
    shutil.copyfile(hook, OUT / "libcarplay_hook.so")
    checks = docker([(OUT, "/out")],
                    "NM=arm-unknown-nto-qnx6.5.0eabi-nm; RE=arm-unknown-nto-qnx6.5.0eabi-readelf; "
                    "echo emutls=$($NM /out/libcarplay_hook.so | grep -ci emutls || true); "
                    "echo init_array=$($RE -W -S /out/libcarplay_hook.so | awk '$2==\".init_array\"{print $6}')",
                    OUT / "elf-checks.txt")
    assert "emutls=0" in checks and "init_array=000004" in checks, checks
    exports = set()
    for lib in [LIBS / "proc/boot/libc.so.3", LIBS / "lib/libsocket.so.3"]:
        exports |= set(elf_symbols(lib)[1])
    needs, missing = {}, {}
    for name, path in [("libcarplay_hook.so", hook), ("f7_spawn", spawn)]:
        undefined, _, needed = elf_symbols(path)
        needs[name] = {"needed": needed, "undefined": sorted(undefined)}
        missing[name] = sorted(n for n, weak in undefined.items() if not weak and n not in exports)
    assert not any(missing.values()), missing
    (OUT / "symbols.json").write_text(json.dumps(needs, indent=2) + "\n")

    report = {
        "image_id": IMAGE,
        "base": "navhook-v1-build (car-run hook F2-F6), reproduced byte for byte first",
        "reproduced_car_hook_sha256": CAR_HOOK_SHA,
        "changes": "framework/trial_gate.{c,h} from f7-src (always-on gate: off switches, crash guard, "
                   "generation record); bus.c connector skips (re)connect while superseded",
        "sources": {"trial_gate.c": sha(SRC / "trial_gate.c"), "trial_gate.h": sha(SRC / "trial_gate.h"),
                    "f7_spawn.c": sha(SRC / "f7_spawn.c"), "bus.c": sha(bus)},
        "artifacts": {"libcarplay_hook.so": {"sha256": sha(hook), "size": hook.stat().st_size},
                      "f7_spawn": {"sha256": sha(spawn), "size": spawn.stat().st_size}},
        "dynamic_imports": needs,
        "missing_in_vehicle_libs": missing,
        "emutls": 0, "init_array": "000004", "constructor_added": False,
        "vehicle_tested": False,
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["artifacts"], indent=2))


if __name__ == "__main__":
    main()
