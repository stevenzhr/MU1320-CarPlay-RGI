#!/usr/bin/env python3
"""Audit the minimal ingress JAR against the exact retained vehicle class set."""
import hashlib
import json
import zipfile
from pathlib import Path

from formats import ClassFile

BASE = Path(__file__).resolve().parents[1]
PRIVATE = BASE.parent / "private-data" / "mu1320-rgi"
ROOT = BASE.parent


def sha(data):
    return hashlib.sha256(data).hexdigest()


FORBIDDEN_TOKENS = ["BAPBridge", "RouteGuidance", "Renderer", "ScreenModule",
                    "DisplayManager", "CarplayDSILifecycleController", "AppState",
                    "CoverArt", "Cursor", "SteeringWheel"]
NAVJAVA_FRESH = ("com/luka/carplay/core/CarPlayApp", "com/luka/carplay/rgd/RgdIngressProbe")
NAVJAVA_LIMITATIONS = [
    "Symbol resolution does not replace a J9 runtime test.",
    "The existing NavActiveIgnore behavior is retained, not endorsed or revalidated by this audit.",
    "BAP, renderer and VC/HUD output are outside this receive-only gate."
]


def audit(artifact, build_report, report_path, fresh_prefixes, limitations,
          proven_jar=BASE / "stage2/carplay_mu1320_stage2.jar.DISABLED", allowed_tokens=()):
    """Link-check a receive-only trial JAR; shared by navjava and F2."""
    build = json.loads(build_report.read_text())
    assert sha(artifact.read_bytes()) == build["jar_sha256"]
    with zipfile.ZipFile(artifact) as archive:
        built_raw = {name[:-6]: archive.read(name) for name in archive.namelist()
                     if name.endswith(".class")}
    built = {name: ClassFile(data) for name, data in built_raw.items()}

    active_archives = sorted((ROOT / "resource/jars").glob("*.jar"))
    support_archives = [PRIVATE / "MU1320-base.jar"]
    support_archives += sorted((ROOT / "resource/bundles").glob("*.jar"))
    support_archives += sorted((ROOT / "resource/bundles_prod").glob("*.jar"))
    providers = {}
    all_classes = []
    for path in active_archives + support_archives:
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if not name.endswith(".class"):
                    continue
                internal = name[:-6]
                data = archive.read(name)
                providers.setdefault(internal, []).append(path.name)
                all_classes.append((path.name, internal, data))

    retained_overlap = {}
    with zipfile.ZipFile(ROOT / "resource/jars/NavActiveIgnore.jar") as archive:
        retained = {name[:-6] for name in archive.namelist() if name.endswith(".class")}
    for name in sorted(set(built) & retained):
        retained_overlap[name] = providers.get(name, [])

    stock = {}
    for _, name, data in all_classes:
        stock.setdefault(name, data)
    cache = dict(built)

    def get(name):
        if name not in cache and name in stock:
            cache[name] = ClassFile(stock[name])
        return cache.get(name)

    def resolve(owner, member, descriptor, kind, seen=None):
        seen = set() if seen is None else seen
        if owner is None or owner in seen:
            return False
        seen.add(owner)
        if owner.startswith("["):
            return member == "clone"
        cls = get(owner)
        if cls is None:
            return False
        members = cls.fields if kind == 9 else cls.methods
        if any(item["name"] == member and item["descriptor"] == descriptor for item in members):
            return True
        if member == "<init>":
            return False
        return any(resolve(parent, member, descriptor, kind, seen)
                   for parent in [cls.super] + list(cls.interfaces))

    missing = []
    references = 0
    for caller, cls in built.items():
        assert cls.major == 48
        for kind, owner, member, descriptor in cls.refs():
            references += 1
            if not resolve(owner, member, descriptor, kind):
                missing.append([caller, owner, member, descriptor])

    shape = []
    access_changes = []
    removed = set()
    for name, cls in built.items():
        if name not in stock:
            continue
        old = ClassFile(stock[name])
        if cls.super != old.super or cls.interfaces != old.interfaces:
            shape.append(name)
        for old_members, new_members in [(old.methods, cls.methods), (old.fields, cls.fields)]:
            current = {(item["name"], item["descriptor"]): item for item in new_members}
            for item in old_members:
                key = (item["name"], item["descriptor"])
                match = current.get(key)
                if not item["access"] & 2 and match and ((item["access"] & 0x000d)
                                                         != (match["access"] & 0x000d)):
                    access_changes.append([name, key[0], key[1], item["access"], match["access"]])
                if not item["access"] & 2 and key not in current:
                    removed.add((name, key[0], key[1]))

    broken = []
    scanned = 0
    for archive, name, data in all_classes:
        if name in built:
            continue
        scanned += 1
        for _, owner, member, descriptor in ClassFile(data).refs():
            if (owner, member, descriptor) in removed:
                broken.append([archive, name, owner, member, descriptor])

    reused = {}
    with zipfile.ZipFile(proven_jar) as archive:
        for name, data in built_raw.items():
            entry = name + ".class"
            if entry in archive.namelist() and not name.startswith(fresh_prefixes):
                reused[name] = sha(data) == sha(archive.read(entry))

    forbidden = [name for name in built
                 if any(token in name for token in FORBIDDEN_TOKENS if token not in allowed_tokens)]
    status = "PASS" if not (missing or retained_overlap or shape or access_changes
                             or broken or forbidden) and all(reused.values()) else "FAIL"
    report = {
        "status": status,
        "classes": len(built),
        "references": references,
        "missing": missing,
        "shape_changes": shape,
        "access_changes": access_changes,
        "surviving_classfiles_scanned": scanned,
        "surviving_references_to_removed_members": broken,
        "removed_nonprivate_members": sorted(removed),
        "retained_nav_active_ignore_overlap": retained_overlap,
        "vehicle_proven_stage2_class_bytes_reused": all(reused.values()),
        "reused_class_count": len(reused),
        "forbidden_feature_classes": forbidden,
        "classfile_major": 48,
        "limitations": limitations,
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(status, len(built), "classes", references, "refs", "missing", len(missing),
          "retained-overlap", len(retained_overlap), "broken", len(broken))
    return report


def main():
    report = audit(BASE / "navjava-trial/carplay_mu1320_navjava_ingress_v1.jar.DISABLED",
                   BASE / "reports/navjava-ingress-build.json",
                   BASE / "reports/navjava-ingress-audit.json",
                   NAVJAVA_FRESH, NAVJAVA_LIMITATIONS)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
