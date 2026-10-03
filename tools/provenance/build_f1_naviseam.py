#!/usr/bin/env python3
"""Build the F1 narrow NAVI seam that replaces NavActiveIgnore.jar.

The vehicle artifact holds exactly two classes:

* the stock MU1320 ``CarplayDSILifecycleController$DSICarplayListenerImpl``
  with one 23-byte call inserted at the top of the ``convertAppState`` loop
  body; every other byte of behaviour stays stock, and
* ``com.luka.carplay.mu1320.NaviAppStateSeam``, compiled for Java 1.4, which
  replaces only CarPlay NAVIGATION (ID 2) by ID 0 and writes a bounded log.

The patch is done at the bytecode level on purpose: recompiling the outer
class would renumber synthetic accessors and anonymous classes, forcing the
whole CarplayDSILifecycleController family to be replaced.
"""
import hashlib
import json
import os
import shutil
import struct
import subprocess
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
PRIVATE = BASE.parent / "private-data" / "mu1320-rgi"
ROOT = BASE.parent
OUT = PRIVATE / "f1-naviseam-v1"
STAGE = BASE / "f1-trial"
JAR = STAGE / "carplay_mu1320_f1_naviseam_v1.jar.DISABLED"
IMPL = "de/audi/app/terminalmode/dsi/carplay/CarplayDSILifecycleController$DSICarplayListenerImpl"
HELPER = "com/luka/carplay/mu1320/NaviAppStateSeam"
FILTER_DESC = "(Lorg/dsi/ifc/carplay/AppState;)Lde/audi/app/terminalmode/dsi/IAppState;"
STOCK_CLASS_SHA256 = "f7e92eec620943004973b61038b19dc5c70a2b372f69f5ce743b0c636edf1546"
# Original convertAppState body (javap listing reviewed in F1-NAVISEAM-REVIEW.md).
STOCK_CODE_HEX = (
    "2bbe bd0008 4d 03 3e 03 3604 1504 2bbe a20042 2b 1504 32 b6004d 04 a00010"
    " 2b 1504 32 b6004e 05 a00005 04 3e 1d 99 0011 2b 1504 32 b6004d 06 a00006"
    " a70012 2c 1504 bb008b 59 2b 1504 32 b70072 53 8404 01 a7ffbd 2a b4004b"
    " 12 04 12 0a 12 06 2c b80007 b6004c 2c b0"
).replace(" ", "")
INSERT_AT = 18
INSERTED = 23


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ClassFile:
    """Minimal class-file editor: raw constant pool entries plus methods."""

    def __init__(self, data):
        self.data = data
        assert data[:4] == b"\xca\xfe\xba\xbe"
        self.minor, self.major = struct.unpack(">HH", data[4:8])
        count = struct.unpack(">H", data[8:10])[0]
        self.cp = [None]
        i = 10
        while len(self.cp) < count:
            tag = data[i]
            if tag == 1:
                length = struct.unpack(">H", data[i + 1:i + 3])[0]
                size = 3 + length
            elif tag in (3, 4, 9, 10, 11, 12, 18):
                size = 5
            elif tag in (5, 6):
                size = 9
            elif tag in (7, 8, 16):
                size = 3
            elif tag == 15:
                size = 4
            else:
                raise ValueError(f"constant tag {tag}")
            self.cp.append(data[i:i + size])
            if tag in (5, 6):
                self.cp.append(None)
            i += size
        self.header_end = i
        self.access, self.this_class, self.super_class, interfaces = struct.unpack(">HHHH", data[i:i + 8])
        i += 8 + 2 * interfaces
        i = self._skip_members(i)  # fields
        self.methods_offset = i
        self.methods = []
        count = struct.unpack(">H", data[i:i + 2])[0]
        i += 2
        for _ in range(count):
            flags, name, desc, attrs = struct.unpack(">HHHH", data[i:i + 8])
            start = i
            i += 8
            attributes = []
            for _ in range(attrs):
                attr_name, length = struct.unpack(">HI", data[i:i + 6])
                attributes.append((attr_name, i, data[i + 6:i + 6 + length]))
                i += 6 + length
            self.methods.append(dict(flags=flags, name=name, desc=desc, start=start, end=i, attributes=attributes))
        self.methods_end = i

    def _skip_members(self, i):
        count = struct.unpack(">H", self.data[i:i + 2])[0]
        i += 2
        for _ in range(count):
            attrs = struct.unpack(">H", self.data[i + 6:i + 8])[0]
            i += 8
            for _ in range(attrs):
                i += 6 + struct.unpack(">I", self.data[i + 2:i + 6])[0]
        return i

    def utf8(self, index):
        entry = self.cp[index]
        assert entry[0] == 1
        return entry[3:].decode("utf8")

    def class_name(self, index):
        entry = self.cp[index]
        assert entry[0] == 7
        return self.utf8(struct.unpack(">H", entry[1:3])[0])

    def find_utf8(self, text):
        found = [i for i, e in enumerate(self.cp) if e and e[0] == 1 and e[3:] == text.encode()]
        return found[0] if found else None

    def append(self, entry):
        self.cp.append(entry)
        return len(self.cp) - 1

    def add_utf8(self, text):
        existing = self.find_utf8(text)
        if existing:
            return existing
        raw = text.encode()
        return self.append(b"\x01" + struct.pack(">H", len(raw)) + raw)

    def method(self, name, desc):
        found = [m for m in self.methods if self.utf8(m["name"]) == name and self.utf8(m["desc"]) == desc]
        assert len(found) == 1, (name, desc)
        return found[0]

    def rebuild(self, method, code_attribute):
        cp = b"".join(e for e in self.cp[1:] if e is not None)
        head = self.data[:8] + struct.pack(">H", len(self.cp)) + cp
        middle = self.data[self.header_end:method["start"]]
        m = method
        body = struct.pack(">HHHH", m["flags"], m["name"], m["desc"], len(m["attributes"]))
        for attr_name, _, payload in m["attributes"]:
            if attr_name == code_attribute[0]:
                payload = code_attribute[1]
            body += struct.pack(">HI", attr_name, len(payload)) + payload
        return head + middle + body + self.data[m["end"]:]


def patch_impl(stock_bytes):
    cf = ClassFile(stock_bytes)
    assert cf.major == 49 and cf.class_name(cf.this_class) == IMPL
    method = cf.method("convertAppState",
                       "([Lorg/dsi/ifc/carplay/AppState;)[Lde/audi/app/terminalmode/dsi/IAppState;")
    assert method["flags"] == 0x0002  # private, non-static
    code_name = cf.find_utf8("Code")
    (code,) = [a for a in method["attributes"] if a[0] == code_name]
    assert len(method["attributes"]) == 1, "no Exceptions/Signature attributes expected"
    payload = code[2]
    max_stack, max_locals, code_length = struct.unpack(">HHI", payload[:8])
    original = payload[8:8 + code_length]
    rest = payload[8 + code_length:]
    assert (max_stack, max_locals) == (6, 5)
    assert original.hex() == STOCK_CODE_HEX, original.hex()
    assert rest == b"\x00\x00\x00\x00", "no exception table or LineNumber/LocalVariable tables"

    # Constant pool additions for invokestatic NaviAppStateSeam.filter.
    helper_class = cf.append(b"\x07" + struct.pack(">H", cf.add_utf8(HELPER)))
    nat = cf.append(b"\x0c" + struct.pack(">HH", cf.add_utf8("filter"), cf.add_utf8(FILTER_DESC)))
    methodref = cf.append(b"\x0a" + struct.pack(">HH", helper_class, nat))

    # Loop body entry (offset 18) and the stock increment (offset 75) move by INSERTED.
    body = INSERT_AT + INSERTED
    increment = 75 + INSERTED
    insert = bytearray()
    insert += bytes([0x2b, 0x15, 0x04, 0x32])                     # aload_1; iload 4; aaload
    insert += b"\xb8" + struct.pack(">H", methodref)               # invokestatic filter
    insert += bytes([0x3a, 0x05, 0x19, 0x05])                     # astore 5; aload 5
    pc = INSERT_AT + len(insert)
    insert += b"\xc6" + struct.pack(">h", body - pc)               # ifnull stock body
    insert += bytes([0x2c, 0x15, 0x04, 0x19, 0x05, 0x53])         # aload_2; iload 4; aload 5; aastore
    pc = INSERT_AT + len(insert)
    insert += b"\xa7" + struct.pack(">h", increment - pc)          # goto increment
    assert len(insert) == INSERTED

    code = bytearray(original[:INSERT_AT]) + insert + bytearray(original[INSERT_AT:])
    # Only two branches cross the insertion point.
    assert code[15] == 0xa2 and struct.unpack(">h", code[16:18])[0] == 81 - 15
    code[16:18] = struct.pack(">h", 81 + INSERTED - 15)            # if_icmpge -> loop exit
    at = 78 + INSERTED
    assert code[at] == 0xa7 and struct.unpack(">h", code[at + 1:at + 3])[0] == 11 - 78
    code[at + 1:at + 3] = struct.pack(">h", 11 - at)               # goto -> loop head
    new_payload = struct.pack(">HHI", 6, 6, len(code)) + bytes(code) + rest
    return cf.rebuild(method, (code_name, new_payload)), dict(
        methodref=methodref, max_stack=6, max_locals=6, code_length=len(code),
        original_code_length=code_length, class_major=cf.major)


def main():
    assert not OUT.exists(), "Preserve the existing F1 build; use a new version."
    assert not JAR.exists(), "Never overwrite an issued Java artifact."
    stock = PRIVATE / "MU1320-base.jar"
    stock_sha = json.loads((BASE / "reports/java-mu1320-build.json").read_text())["stock_sha256"]
    assert sha(stock) == stock_sha
    navignore = ROOT / "resource/jars/NavActiveIgnore.jar"
    jdk = PRIVATE / "tools/jxe2jar/jvms/zulu8.78.0.19-ca-jdk8.0.412-macosx_aarch64/zulu-8.jdk/Contents/Home/bin"

    src, classes, tests, work = OUT / "src", OUT / "classes", OUT / "test-classes", OUT / "harness-work"
    for directory in [src, classes, tests, work]:
        directory.mkdir(parents=True)
    helper_src = src / (HELPER + ".java")
    helper_src.parent.mkdir(parents=True)
    shutil.copyfile(BASE / "f1-src/NaviAppStateSeam.java", helper_src)
    compiled = subprocess.run(
        [str(jdk / "javac"), "-source", "1.4", "-target", "1.4", "-Xlint:-options",
         "-bootclasspath", str(stock), "-d", str(classes), str(helper_src)],
        text=True, capture_output=True)
    (BASE / "reports/f1-naviseam-compile.log").write_text(compiled.stdout + compiled.stderr)
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    helper_classes = sorted(p.relative_to(classes).as_posix() for p in classes.rglob("*.class"))
    assert helper_classes == [HELPER + ".class"], helper_classes

    with zipfile.ZipFile(stock) as archive:
        stock_impl = archive.read(IMPL + ".class")
    assert hashlib.sha256(stock_impl).hexdigest() == STOCK_CLASS_SHA256
    patched, patch_info = patch_impl(stock_impl)
    target = classes / (IMPL + ".class")
    target.parent.mkdir(parents=True)
    target.write_bytes(patched)
    (OUT / "stock-impl.class").write_bytes(stock_impl)

    # No other HMI archive may define either class.
    names = {IMPL + ".class", HELPER + ".class"}
    for archive_path in sorted((ROOT / "resource/jars").glob("*.jar")):
        with zipfile.ZipFile(archive_path) as archive:
            assert not names & set(archive.namelist()), archive_path

    # Bytecode review artefact: stock vs patched full javap, then the differential run.
    def listing(path):
        text = subprocess.check_output([str(jdk / "javap"), "-v", "-p", "-c", str(path)], text=True)
        return [line for line in text.splitlines(True)
                if not line.lstrip().startswith(("Classfile ", "Last modified", "MD5", "SHA-256"))]
    import difflib
    diff = "".join(difflib.unified_diff(listing(OUT / "stock-impl.class"), listing(target),
                                        fromfile="stock/DSICarplayListenerImpl", tofile="f1/DSICarplayListenerImpl"))
    (BASE / "reports/f1-naviseam-bytecode.diff").write_text(diff)

    harness = BASE / "f1-src/NaviSeamHarness.java"
    built = subprocess.run([str(jdk / "javac"), "-d", str(tests), str(harness)], text=True, capture_output=True)
    assert built.returncode == 0, built.stdout + built.stderr
    tested = subprocess.run(
        [str(jdk / "java"), "-Xverify:all", "-cp", str(tests), "NaviSeamHarness",
         str(stock), str(classes), str(navignore), str(work)], text=True, capture_output=True)
    (BASE / "reports/f1-naviseam-harness.txt").write_text(tested.stdout + tested.stderr)
    assert tested.returncode == 0 and "F1_NAVISEAM_DIFFERENTIAL_TESTS_PASS" in tested.stdout, tested.stdout + tested.stderr

    STAGE.mkdir(exist_ok=True)
    assert not any(STAGE.iterdir()), "Preserve existing staged files; use a new version."
    with zipfile.ZipFile(JAR, "x", zipfile.ZIP_DEFLATED) as archive:
        for item in sorted(classes.rglob("*.class")):
            entry = zipfile.ZipInfo(item.relative_to(classes).as_posix(), (2026, 9, 24, 0, 0, 0))
            entry.create_system = 3
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, item.read_bytes())
    with zipfile.ZipFile(JAR) as archive:
        assert archive.testzip() is None
        entries = sorted(archive.namelist())
    assert entries == sorted(names), entries

    report = {
        "profile": "f1-narrow-carplay-navi-appstate-seam",
        "build_id": "MU1320-F1-NAVISEAM-V1",
        "classes": entries,
        "stock_jar_sha256": stock_sha,
        "stock_impl_class_sha256": STOCK_CLASS_SHA256,
        "patched_impl_class_sha256": hashlib.sha256(patched).hexdigest(),
        "helper_source_sha256": sha(BASE / "f1-src/NaviAppStateSeam.java"),
        "helper_class_sha256": sha(classes / (HELPER + ".class")),
        "bytecode_patch": patch_info,
        "jar_sha256": sha(JAR),
        "jar_size": JAR.stat().st_size,
        "differential_host_tests": "PASS (-Xverify:all, HotSpot 1.8; not J9)",
        "replaces": "NavActiveIgnore.jar AppState getters (ID/owner forced to 0 for every CarPlay app state and in AppStateSerializer)",
        "android_auto": "stock (NavActiveIgnore AndroidAuto2NavHandler not carried; user does not use Android Auto)",
        "includes_native_bap_renderer_or_display": False,
        "vehicle_tested": False,
    }
    (BASE / "reports/f1-naviseam-build.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ["build_id", "classes", "jar_sha256", "jar_size"]}, indent=2))


if __name__ == "__main__":
    main()
