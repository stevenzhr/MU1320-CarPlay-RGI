#!/usr/bin/env python3
"""Assemble the F8 SD folder (mu1320-f7-daily-v2.1) from this repository plus the
inputs this repository deliberately does not contain, then verify every file
against release/v0.9.0-rc.1/f8-SHA256SUMS (the checksums of the package that was run in
the car).

Not in this repository (see NOTICE.md and docs/en/building.md); put them in one
directory and pass it as --inputs:

    libcarplay_hook.so                        built from the upstream hook + patches/
    maneuver_render                           built from the upstream renderer
    flag_atlas.rgba                           upstream asset
    carplay_mu1320_f7_daily_v2.jar.DISABLED   Java patch, built against your own MU1320 JAR
    dio_manager.json                          your car's stock config, edited (see docs)
    smartphone_integrator.json                your car's stock config, edited (see docs)

    python3 tools/assemble_f8.py --inputs ~/mu1320-inputs --output build/mu1320-f7-daily-v2.1

Exit status is non-zero if any file differs from the car-tested package, so a
mismatch means you are NOT installing the F8 candidate, whatever it is called.
"""
import argparse
import hashlib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUMS = ROOT / "release/v0.9.0-rc.1/f8-SHA256SUMS"
EXTERNAL = ["libcarplay_hook.so", "maneuver_render", "flag_atlas.rgba",
            "carplay_mu1320_f7_daily_v2.jar.DISABLED", "dio_manager.json", "smartphone_integrator.json"]
EXEC = {"loader_check", "mount_state", "maneuver_render", "f7_spawn", "f5_sc.sh", "f7_render.sh",
        "f7_mark.sh", "f8_mon.sh", "f7.sh", "control.sh", "collect_f7.sh", "f5_dm.sh"}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inputs", type=Path, help="directory with the external files (omit with --check-only)")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--check-only", action="store_true",
                    help="only report which files can be produced from this repository alone")
    args = ap.parse_args()
    if args.output.exists():
        ap.error(f"{args.output} exists")
    if not args.check_only and not args.inputs:
        ap.error("--inputs is required")

    f8 = ROOT / "f8"
    sources = {p.name: p for p in f8.iterdir() if p.is_file()}
    sources.update({p.name: p for p in (f8 / "src").iterdir() if p.is_file()})
    sources.update({p.name: p for p in (f8 / "bin").iterdir() if p.is_file()})
    if args.inputs:
        for name in EXTERNAL:
            if not (args.inputs / name).is_file():
                ap.error(f"missing input {args.inputs / name}")
            sources[name] = args.inputs / name

    expected = {}
    for line in SUMS.read_text().splitlines():
        digest, name = line.split("  ", 1)
        expected[name] = digest

    missing = [n for n in expected if n not in sources]
    wrong = [n for n in expected if n in sources and sha256(sources[n]) != expected[n]]
    if args.check_only:
        print(f"{len(expected) - len(missing)}/{len(expected)} files come from this repository")
        for n in missing:
            print("  external:", n)
        for n in wrong:
            print("  DIFFERS:", n)
        sys.exit(1 if wrong else 0)
    if missing or wrong:
        for n in missing:
            print("MISSING", n)
        for n in wrong:
            print("MISMATCH", n)
        sys.exit("verification failed; nothing written")

    args.output.mkdir(parents=True)
    for name in expected:
        dst = args.output / name
        shutil.copyfile(sources[name], dst)
        dst.chmod(0o755 if name in EXEC else 0o644)
    shutil.copyfile(SUMS, args.output / "SHA256SUMS")
    print(f"OK: {len(expected)} files, all match release/v0.9.0-rc.1/f8-SHA256SUMS")


if __name__ == "__main__":
    main()
