#!/usr/bin/env python3
"""Assemble the MU1320 Toolbox v1 SD package.

Toolbox v1 = upstream jilleb/mib2-toolbox at a pinned commit, byte for byte
(only git-tracked files under Toolbox/, plus metainfo2.txt and LICENSE), plus the
overlay in toolbox/overlay/ (the green-menu page and its dispatcher scripts).

    python3 tools/assemble_toolbox_v1.py --output build/mu1320-toolbox-v1
    python3 tools/assemble_toolbox_v1.py --upstream ~/src/mib2-toolbox --output ...

Without --upstream the pinned commit is fetched from GitHub into a temporary clone.
The result is verified against release/v0.9.0-rc.1/toolbox-v1.SHA256SUMS.
"""
import argparse
import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = "https://github.com/jilleb/mib2-toolbox.git"
COMMIT = "af244e7cb8c912ab47f5c09cd7677370fe86b441"
OVERLAY = ROOT / "toolbox/overlay"
SUMS = ROOT / "release/v0.9.0-rc.1/toolbox-v1.SHA256SUMS"


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--upstream", type=Path, help="existing mib2-toolbox checkout (must be at the pinned commit)")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    if args.output.exists():
        ap.error(f"{args.output} exists")

    tmp = None
    up = args.upstream
    if up is None:
        tmp = tempfile.mkdtemp(prefix="mib2-toolbox-")
        up = Path(tmp)
        subprocess.check_call(["git", "clone", "--quiet", REPO, str(up)])
        subprocess.check_call(["git", "-C", str(up), "checkout", "--quiet", COMMIT])
    try:
        head = git(up, "rev-parse", "HEAD").strip()
        if head != COMMIT:
            ap.error(f"upstream is at {head[:12]}, expected {COMMIT[:12]}")
        tracked = git(up, "ls-files", "--", "Toolbox", "metainfo2.txt").splitlines()
        out = args.output
        for rel in tracked:
            dst = out / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(up / rel, dst)
        shutil.copyfile(up / "LICENSE", out / "LICENSE-mib2-toolbox.txt")
        for src in sorted(p for p in OVERLAY.rglob("*") if p.is_file()):
            dst = out / src.relative_to(OVERLAY)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            if dst.suffix == ".sh":
                dst.chmod(0o755)
        shutil.copyfile(ROOT / "toolbox/README.zh-CN.md", out / "MU1320-README.md")
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)

    bad = 0
    expected = {}
    for line in SUMS.read_text().splitlines():
        digest, name = line.split("  ", 1)
        expected[name] = digest
        f = args.output / name
        if not f.is_file() or sha256(f) != digest:
            print("MISMATCH", name)
            bad += 1
    extra = sorted(str(p.relative_to(args.output)) for p in args.output.rglob("*")
                   if p.is_file() and str(p.relative_to(args.output)) not in expected)
    for name in extra:
        print("UNEXPECTED", name)
    if bad or extra:
        sys.exit(f"verification failed ({bad} mismatches, {len(extra)} unexpected)")
    shutil.copyfile(SUMS, args.output / "MU1320-SHA256SUMS")
    print(f"OK: {len(expected)} files match {SUMS.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
