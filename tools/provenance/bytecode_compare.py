#!/usr/bin/env python3
"""Normalized, method-level bytecode comparison of two class families.

javap -c -p output is reduced to (mnemonic, symbolic operand) pairs:
constant-pool indices and byte offsets disappear, branch targets become
instruction indices, synthetic accessor names (access$NNN) and anonymous
class numbers are canonicalised. Trailing J9 ROM padding (nop) is dropped.
Used to show which methods of a recompiled class family differ from stock.
"""
import re
import subprocess
import sys
from pathlib import Path

JAVAP = Path(__file__).resolve().parents[1] / (
    "private/tools/jxe2jar/jvms/zulu8.78.0.19-ca-jdk8.0.412-macosx_aarch64/"
    "zulu-8.jdk/Contents/Home/bin/javap")
BRANCH = {"ifeq", "ifne", "iflt", "ifge", "ifgt", "ifle", "if_icmpeq", "if_icmpne", "if_icmplt",
          "if_icmpge", "if_icmpgt", "if_icmple", "if_acmpeq", "if_acmpne", "goto", "jsr",
          "ifnull", "ifnonnull", "goto_w", "jsr_w"}
INSN = re.compile(r"^\s+(\d+): (\w+)\s*(.*)$")


def canon(text, owner=None):
    if owner:
        # javap prints members of the class itself unqualified; qualify uniformly.
        text = re.sub(r"^(Field|Method|InterfaceMethod) (?![\w/$]+\.)", r"\1 " + owner + ".", text)
    text = text.replace("this$0$", "this$0")
    text = re.sub(r"access\$\d+", "access$N", text)
    text = re.sub(r"(\$[A-Za-z_]\w*)?\$\d+\b", lambda m: (m.group(1) or "") + "$anon", text)
    return text


def methods(class_file):
    out = subprocess.check_output([str(JAVAP), "-c", "-p", str(class_file)], text=True)
    owner = re.search(r"(?:class|interface) ([\w.$]+)", out).group(1).replace(".", "/")
    result, name, code = {}, None, []

    def flush():
        if name is None:
            return
        offsets = {off: i for i, (off, _, _) in enumerate(code)}
        items = []
        for off, op, arg in code:
            if op in BRANCH:
                arg = "->%d" % offsets[int(arg.split()[0])]
            elif op in ("tableswitch", "lookupswitch"):
                cases = re.findall(r"(\S+):(\d+)", arg)
                arg = " ".join("%s:->%d" % (k, offsets[int(t)]) for k, t in cases)
            elif "//" in arg:
                arg = arg.split("//", 1)[1].strip()
            else:
                arg = re.sub(r"#\d+,?\s*", "", arg).strip()
            items.append((op, canon(arg, owner)))
        while items and items[-1][0] == "nop":
            items.pop()
        if items:  # field declarations carry no code
            result[canon(name)] = items

    in_switch = False
    for line in out.splitlines():
        if re.match(r"^  \S.*\);$|^  \S.*;$", line) and not line.startswith("    "):
            flush()
            name, code = line.strip(), []
            continue
        if in_switch:
            if line.strip() == "}":
                in_switch = False
            else:
                # switch case pairs belong to the switch instruction
                key, _, target = line.strip().partition(":")
                code[-1] = (code[-1][0], code[-1][1], code[-1][2] + " %s:%s" % (key.strip(), target.strip()))
            continue
        m = INSN.match(line)
        if m:
            code.append((int(m.group(1)), m.group(2), m.group(3)))
            if m.group(2) in ("tableswitch", "lookupswitch"):
                in_switch = True
    flush()
    # switch targets -> instruction indices
    return result


def family(directory, outer):
    return sorted(Path(directory).glob(outer + "*.class"))


def compare(stock_dir, new_dir, outer):
    """Returns (identical, differing, only_stock, only_new) keyed by 'Class#method'."""
    def load(d):
        table = {}
        for path in family(d, outer):
            cls = canon(path.stem)
            for m, code in methods(path).items():
                key = cls + "#" + m
                # Several anonymous classes collapse to $anon: keep all variants.
                table.setdefault(key, []).append(code)
        return table
    a, b = load(stock_dir), load(new_dir)
    same, diff = [], []
    for key in sorted(set(a) & set(b)):
        if sorted(map(repr, a[key])) == sorted(map(repr, b[key])):
            same.append(key)
        else:
            diff.append(key)
    return same, diff, sorted(set(a) - set(b)), sorted(set(b) - set(a)), a, b


if __name__ == "__main__":
    stock_dir, new_dir, outer = sys.argv[1:4]
    same, diff, only_a, only_b, a, b = compare(stock_dir, new_dir, outer)
    print("IDENTICAL", len(same))
    for k in diff:
        print("DIFF", k)
    for k in only_a:
        print("ONLY_STOCK", k)
    for k in only_b:
        print("ONLY_NEW", k)
