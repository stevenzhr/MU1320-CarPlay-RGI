#!/usr/bin/env python3
"""Read archived CarPlay logs; emit counts/hashes, never route text.

Usage: python3 mu1320-rgi/scripts/audit_stop_sign_metadata.py > report.json
Counts include overlapping snapshots. Absence of keywords is not evidence
that the route traversed no stop signs, nor a universal protocol limitation.
"""
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DUMP = ROOT / "resource/private/vehicle-dump"
MANEUVER = re.compile(r'\[RGD\] Maneuver: idx=(\d+) type=(\d+) desc="(.*)"$')
PATTERNS = {
    "stop_word_or_sign": re.compile(r"\bstop(?:s|[\s_-]*signs?)?\b|停|止まれ|🛑", re.I),
    "traffic_light_or_signal": re.compile(r"\blights?\b|\bsignals?\b|灯|燈|信号|🚦|🚥", re.I),
}


def main():
    files = []
    unique_lines = set()
    unique_descriptions = set()
    types = Counter()
    all_descriptions = []
    for path in sorted(DUMP.rglob("carplay_hook.log")):
        data = path.read_bytes()
        text = data.decode("utf-8")
        descriptions = []
        for line in text.splitlines():
            match = MANEUVER.search(line)
            if match:
                descriptions.append(match[3])
                unique_lines.add(line)
                unique_descriptions.add(match[3])
                types[int(match[2])] += 1
        all_descriptions.extend(descriptions)
        files.append({
            "path": str(path.relative_to(ROOT)),
            "sha256": hashlib.sha256(data).hexdigest(),
            "maneuver_records": len(descriptions),
            "keyword_matches": {key: sum(bool(pattern.search(x)) for x in descriptions)
                                for key, pattern in PATTERNS.items()},
            "unknown_tlv_lines": len(re.findall(r"Unknown (?:RGD|MAN|0x5204)[^\n]*TLV", text)),
            "raw_packet_header_lines": len(re.findall(r"RGD 0x520[124] raw len=", text)),
        })
    captures = sorted(DUMP.glob("**/*frames.cap"))
    name_fields = []
    sources = Counter()
    for path in captures:
        text = path.read_text(encoding="utf-8")
        name_fields.extend(re.findall(r"(?:\x1f| )m\d+_name\ts\t([^\x1f\n]*)", text))
        sources.update(re.findall(r"source_name\ts\t([^\x1f\n]+)", text))
    report = {
        "scope": "Local archived logs only; no new vehicle capture or iOS binary analysis",
        "snapshot_overlap": True,
        "distinct_line_count_is_not_independent_event_count": True,
        "files": files,
        "summary": {
            "log_files": len(files),
            "maneuver_records_including_overlap": len(all_descriptions),
            "distinct_exact_maneuver_log_lines": len(unique_lines),
            "distinct_description_strings_including_empty": len(unique_descriptions),
            "empty_description_records": sum(not x for x in all_descriptions),
            "max_description_utf8_bytes": max((len(x.encode("utf-8")) for x in all_descriptions), default=0),
            "keyword_matches": {key: sum(bool(pattern.search(x)) for x in all_descriptions)
                                for key, pattern in PATTERNS.items()},
            "maneuver_types_including_overlap": dict(sorted(types.items())),
            "unknown_tlv_lines": sum(x["unknown_tlv_lines"] for x in files),
            "raw_packet_header_lines": sum(x["raw_packet_header_lines"] for x in files),
            "sanitized_capture_files": len(captures),
            "capture_maneuver_name_field_changes": len(name_fields),
            "capture_nonempty_name_fields": sum(bool(x) for x in name_fields),
            "capture_nonempty_name_fields_are_tokens": all(x.startswith("~") for x in name_fields if x),
            "capture_source_name_occurrences": dict(sorted(sources.items())),
        },
        "limitations": [
            "No synchronized ground truth that a STOP sign was visible or announced at a logged time.",
            "Native description log cannot distinguish absent TLV from an empty TLV.",
            "Parser retains at most 255 description bytes; raw packets are not available here.",
            "Known skipped TLVs and other message families are not ruled out by zero unknown-TLV warnings.",
            "Source names in sanitized captures do not label each native maneuver record.",
            "Keyword search is a heuristic and does not cover every language or semantic encoding.",
        ],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
