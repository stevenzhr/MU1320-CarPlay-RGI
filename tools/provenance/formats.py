"""Offline format readers. Never run on the head unit. Python 3.9+."""
import json
import struct


def uncomment(text):
    """Remove # comments outside strings, preserving offsets and newlines."""
    out = list(text)
    quoted = escaped = comment = False
    for i, c in enumerate(text):
        if comment:
            if c in '\r\n':
                comment = False
            else:
                out[i] = ' '
        elif quoted:
            if escaped:
                escaped = False
            elif c == '\\':
                escaped = True
            elif c == '"':
                quoted = False
        elif c == '"':
            quoted = True
        elif c == '#':
            out[i] = ' '
            comment = True
    return ''.join(out)


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key: ' + key)
        result[key] = value
    return result


def config(text):
    return json.loads(uncomment(text), object_pairs_hook=unique_pairs)


class ClassFile:
    """Read descriptors, references and raw Code; no JVM needed for ABI comparison."""
    def __init__(self, data):
        self.data, self.pos = data, 0
        if self.u4() != 0xcafebabe:
            raise ValueError('not a class file')
        self.minor, self.major = self.u2(), self.u2()
        count = self.u2()
        self.cp = [None] * count
        i = 1
        while i < count:
            tag = self.u1()
            if tag == 1:
                value = self.read(self.u2()).decode('utf-8', errors='replace')
            elif tag in (3, 4):
                value = self.read(4).hex()
            elif tag in (5, 6):
                value = self.read(8).hex()
            elif tag in (7, 8, 16, 19, 20):
                value = self.u2()
            elif tag in (9, 10, 11, 12, 18, 17):
                value = (self.u2(), self.u2())
            elif tag == 15:
                value = (self.u1(), self.u2())
            else:
                raise ValueError('unsupported constant pool tag: %s' % tag)
            self.cp[i] = (tag, value)
            i += 2 if tag in (5, 6) else 1
        self.access = self.u2()
        self.name, self.super = self.cls(self.u2()), self.cls(self.u2())
        self.interfaces = [self.cls(self.u2()) for _ in range(self.u2())]
        self.fields, self.methods = self.members(), self.members()
        self.attributes = self.attrs()
        if self.pos != len(data):
            raise ValueError('trailing class bytes')

    def read(self, n):
        x = self.data[self.pos:self.pos+n]
        self.pos += n
        if len(x) != n:
            raise ValueError('truncated class')
        return x

    def u1(self): return self.read(1)[0]
    def u2(self): return struct.unpack('>H', self.read(2))[0]
    def u4(self): return struct.unpack('>I', self.read(4))[0]
    def utf(self, i): return self.cp[i][1]
    def cls(self, i): return self.utf(self.cp[i][1]) if i else None

    def attrs(self):
        out = {}
        for _ in range(self.u2()):
            name = self.utf(self.u2())
            out[name] = self.read(self.u4())
        return out

    def members(self):
        result = []
        for _ in range(self.u2()):
            flags, name, desc = self.u2(), self.utf(self.u2()), self.utf(self.u2())
            attrs = self.attrs()
            result.append({'access': flags, 'name': name, 'descriptor': desc,
                           'attributes': attrs})
        return result

    def api(self):
        def clean(ms):
            return [{k: v for k, v in m.items() if k != 'attributes'} for m in ms]
        return dict(name=self.name, super=self.super, interfaces=self.interfaces,
                    access=self.access, major=self.major,
                    fields=clean(self.fields), methods=clean(self.methods))

    def refs(self):
        result = []
        for c in self.cp:
            if c and c[0] in (9, 10, 11):
                owner, nt = c[1]
                name, desc = self.cp[nt][1]
                result.append((c[0], self.cls(owner), self.utf(name), self.utf(desc)))
        return result
