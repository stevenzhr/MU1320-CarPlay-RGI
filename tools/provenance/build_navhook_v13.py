#!/usr/bin/env python3
"""navhook v1.3 = the vehicle-run navhook v1.2 hook + one route-guidance fix.

BACKLOG B8 (F6 v2 car run): rgd_prune_stale_lane_cache() (upstream) dropped
lane-guidance entries whose *lane* index was below the lowest *maneuver* index
in the current ManeuverList.  iOS numbers lane guidance independently of the
maneuvers (Google/Apple: lanes 0..6 against maneuvers 2..17), so every entry
but the first was pruned before use, and Apple entries sent mid-route were
pruned on arrival.  v1.3 no longer prunes by maneuver index; lane entries live
until the route is reset (rgd_maneuver_map_reset, unchanged) and a full lane
cache still evicts the least recently used non-active entry
(rgd_lane_slot_for_iap_index, unchanged).

Steps: (1) rebuild the untouched v1.2 source tree and require the vehicle
hook's SHA-256, proving the toolchain is reproducible; (2) apply the patch to
a second copy and build it with the same script (the build script rejects
emutls, eager constructors and a non-compiler .init_array); (3) record the
source diff, patch file, symbol-size differences and a report.
"""
import difflib
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
PRIVATE = BASE.parent / "private-data" / "mu1320-rgi"
V12 = PRIVATE / "navhook-v1-build/src"
OUT = PRIVATE / "navhook-v13-build"
V12_SHA = "ad87795a05227e09c57a72e773449a8126b4509f6d982e9ed1128edb5a385e1d"
IMAGE = "sha256:e52565b1f62dab0f93f12532d52611b94e90b89e4da04f972b11f54eaeb6a05d"
RGD = "hook/routeguidance/rgd_hook.c"

OLD = """static bool rgd_prune_stale_lane_cache(void) {
    int min_idx;
    bool pruned = false;

    if (!g_rgd.current_list_present) return false;
    if (g_rgd.current_list_count == 0) return false;
    if (g_rgd.last_route_state == RGD_STATE_REROUTING) return false;

    min_idx = rgd_min_current_index();
    if (min_idx < 0) return false;

    for (int i = 0; i < MANEUVER_CACHE_SIZE; i++) {
        uint16_t lane_idx = g_rgd.lane_slot_to_iap_idx[i];
        if (lane_idx == 0xFFFF) continue;
        if ((int)lane_idx >= min_idx) continue;
        if ((g_rgd.update_cache.present & RGD_UPD_LANE_INDEX) &&
            g_rgd.update_cache.lane_guidance_index == lane_idx) {
            continue;
        }

        LOG_DEBUG(LOG_MODULE, "Pruning stale lane guidance slot %d (idx %u < current min %d)",
                  i, (unsigned)lane_idx, min_idx);
        g_rgd.lane_slot_to_iap_idx[i] = 0xFFFF;
        g_rgd.lane_slot_seq[i] = 0;
        g_rgd.lane_cache[i].present = 0;
        pruned = true;
    }
    return pruned;
}"""

NEW = """/* MU1320 navhook v1.3 (BACKLOG B8): iOS numbers lane guidance (0x5204)
 * independently of maneuvers, so comparing a lane index with the lowest
 * ManeuverList index pruned entries that were still ahead (Google/Apple send
 * most of them at route start, Apple some mid-route).  Lane entries now live
 * until rgd_maneuver_map_reset(); a full cache evicts the least recently used
 * non-active entry in rgd_lane_slot_for_iap_index().  Nothing is pruned here. */
static bool rgd_prune_stale_lane_cache(void) {
    return false;
}"""


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fresh_copy(dest):
    shutil.copytree(V12, dest)
    for f in (dest / "build").iterdir():
        f.unlink()


def build(tree, log):
    r = subprocess.run(["/bin/bash", str(tree / "scripts/build_hook.sh")], capture_output=True, text=True)
    log.write_text(r.stdout + r.stderr)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-4000:]
    assert "emutls=0 init_array=compiler-only" in r.stdout
    return tree / "build/libcarplay_hook.so"


def symbols(tree):
    cmd = ("export PATH=/opt/qnx650/host/linux/x86/usr/bin:$PATH; "
           "arm-unknown-nto-qnx6.5.0eabi-nm -S --size-sort /src/build/libcarplay_hook.so; "
           "echo ===; arm-unknown-nto-qnx6.5.0eabi-readelf -W -S /src/build/libcarplay_hook.so")
    r = subprocess.run(["docker", "run", "--rm", "--network=none", "--platform=linux/amd64",
                        "-v", "%s:/src" % tree, IMAGE, "bash", "-c", cmd], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    syms, sections = r.stdout.split("===\n", 1)
    table = {}
    for line in syms.splitlines():
        p = line.split()
        if len(p) == 4:
            table[p[3]] = int(p[1], 16)
    return table, sections


def main():
    assert not OUT.exists(), "Preserve an existing private build; use a new version."
    assert sha(V12 / "build/libcarplay_hook.so") == V12_SHA
    assert sha(BASE / "mu1320-f5-vchud-v5/libcarplay_hook.so") == V12_SHA, "vehicle hook is not navhook v1.2"
    OUT.mkdir()

    repro = OUT / "repro-v1.2"
    fresh_copy(repro)
    got = sha(build(repro, OUT / "repro-build.log"))
    assert got == V12_SHA, "toolchain does not reproduce v1.2: " + got

    tree = OUT / "src"
    fresh_copy(tree)
    rgd = tree / RGD
    original = rgd.read_text()
    assert original.count(OLD) == 1, "prune function differs from the reviewed text"
    patched = original.replace(OLD, NEW, 1)
    rgd.write_text(patched)
    # The script and every other source are the v1.2 ones.
    for p in V12.rglob("*"):
        if p.is_file() and p.parent.name != "build" and p.relative_to(V12).as_posix() != RGD:
            assert (tree / p.relative_to(V12)).read_bytes() == p.read_bytes(), p
    artifact = build(tree, OUT / "build.log")

    diff = "".join(difflib.unified_diff(original.splitlines(True), patched.splitlines(True),
                                        "a/" + RGD, "b/" + RGD))
    (BASE / "reports/navhook-v13-rgd.diff").write_text(diff)
    (BASE / "patches/0004-navhook-lane-cache-no-maneuver-prune.patch").write_text(
        "From: MU1320 RGI\nSubject: [PATCH] navhook v1.3: do not prune lane guidance by maneuver index\n\n"
        "BACKLOG B8, F6 v2 car run 2026-09-27.\n---\n" + diff)
    old_syms, _ = symbols(repro)
    new_syms, sections = symbols(tree)
    changed = {k: [old_syms.get(k), new_syms.get(k)] for k in sorted(set(old_syms) | set(new_syms))
               if old_syms.get(k) != new_syms.get(k)}
    report = {
        "version": "navhook v1.3",
        "image_id": IMAGE,
        "base": {"navhook_v1_2_sha256": V12_SHA, "reproduced_bit_for_bit": True},
        "change": "rgd_prune_stale_lane_cache() returns false (no pruning of lane guidance by maneuver index)",
        "unchanged": "one-shot trial gate, framework, bus, TLV parser, build flags, map reset and LRU eviction",
        "sources": {RGD: sha(rgd)},
        "symbol_size_changes": changed,
        "artifact": {"sha256": sha(artifact), "size": artifact.stat().st_size},
        "abi_checks": "build_hook.sh: emutls=0, .init_array compiler-only, no eager rgd_module_init/fini",
        "vehicle_tested": False,
    }
    (OUT / "sections.txt").write_text(sections)
    (BASE / "reports/navhook-v13-build.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"artifact": report["artifact"], "symbol_size_changes": changed}, indent=2))


if __name__ == "__main__":
    main()
