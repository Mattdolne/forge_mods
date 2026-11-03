"""Skyrim plugin headers and Proton load-order files; no game execution."""
from pathlib import Path
import os
import struct
import tempfile

EXTENSIONS = {'.esp', '.esm', '.esl'}
BASE_SE = {'skyrim.esm', 'update.esm', 'dawnguard.esm', 'hearthfires.esm', 'dragonborn.esm'}


def plugin_info(path):
    path = Path(path)
    with path.open('rb') as f:
        header = f.read(24)
        if len(header) != 24 or header[:4] != b'TES4':
            raise ValueError('Plugin inválido (cabeçalho TES4): ' + path.name)
        size, flags = struct.unpack_from('<II', header, 4)
        if size > 16 * 1024 * 1024: raise ValueError('Cabeçalho de plugin grande demais: ' + path.name)
        data = f.read(size)
    if len(data) != size: raise ValueError('Plugin truncado: ' + path.name)
    masters, pos, extended = [], 0, None
    while pos < len(data):
        if pos + 6 > len(data): raise ValueError('Subregistro inválido: ' + path.name)
        tag, length = struct.unpack_from('<4sH', data, pos); pos += 6
        if tag == b'XXXX':
            if length != 4 or pos + 4 > len(data): raise ValueError('Subregistro XXXX inválido: ' + path.name)
            extended = struct.unpack_from('<I', data, pos)[0]; pos += 4; continue
        if extended is not None: length, extended = extended, None
        if pos + length > len(data): raise ValueError('Subregistro truncado: ' + path.name)
        if tag == b'MAST':
            name = data[pos:pos+length].rstrip(b'\0').decode('cp1252')
            if '/' in name or '\\' in name or '\n' in name or '\r' in name: raise ValueError('Nome de master inválido.')
            masters.append(name)
        pos += length
    return {'name': path.name, 'masters': masters, 'master': bool(flags & 1) or path.suffix.lower() in {'.esm', '.esl'},
            'light': bool(flags & 0x200) or path.suffix.lower() == '.esl'}


def child(parent, name):
    parent = Path(parent)
    matches = [p for p in parent.iterdir() if p.name.casefold() == name.casefold()] if parent.is_dir() else []
    if len(matches) > 1: raise ValueError('Nomes duplicados: ' + str(parent / name))
    result = matches[0] if matches else parent / name
    if result.is_symlink(): raise ValueError('Link simbólico não suportado: ' + str(result))
    return result


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.forge-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        if path.exists(): os.chmod(tmp, path.stat().st_mode & 0o777)
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


class TextList:
    def __init__(self, path, starred=False):
        self.path = Path(path); self.starred = starred
        self.original = self.path.read_bytes() if self.path.exists() else None
        raw = self.original or b''
        # Bethesda's plugin lists use Windows-1252. Preserve an explicit UTF-8 BOM.
        self.encoding = 'utf-8-sig' if raw.startswith(b'\xef\xbb\xbf') else 'cp1252'
        text = raw.decode(self.encoding)
        self.newline = '\r\n' if '\r\n' in text or not raw else '\n'
        self.lines = text.splitlines(keepends=True)

    def entry(self, line):
        text = line.strip()
        if not text or text.startswith('#'): return None
        active = not self.starred or text.startswith('*')
        name = text.lstrip('*')
        return (name, active) if Path(name).suffix.lower() in EXTENSIONS else None

    def entries(self): return [e for line in self.lines if (e := self.entry(line))]

    def remove(self, names):
        names = {n.casefold() for n in names}
        self.lines = [line for line in self.lines if not ((entry := self.entry(line)) and entry[0].casefold() in names)]

    def insert(self, name, before=None):
        if any(c in name for c in '\r\n/\\*'): raise ValueError('Nome de plugin inválido.')
        line = ('*' if self.starred else '') + name + self.newline
        index = next((i for i, value in enumerate(self.lines) if (e := self.entry(value)) and before and e[0].casefold() == before.casefold()), len(self.lines))
        if index and not self.lines[index-1].endswith(('\n', '\r')): self.lines[index-1] += self.newline
        self.lines.insert(index, line)

    def bytes(self): return ''.join(self.lines).encode(self.encoding)


class PluginConfig:
    def __init__(self, directory, special=True):
        self.directory = Path(directory); self.special = special
        self.plugins = TextList(child(directory, 'plugins.txt'), starred=special)
        self.order = TextList(child(directory, 'loadorder.txt'))

    def active(self): return [name for name, active in self.plugins.entries() if active]

    def enable(self, infos):
        # Input is dependency-sorted. Existing unrelated entries retain their order.
        for info in infos:
            for listing in (self.plugins, self.order):
                listing.remove([info['name']])
                before = None
                if info['master']:
                    before = next((name for name, _ in listing.entries() if name.casefold() not in self.master_names), None)
                listing.insert(info['name'], before)

    def disable(self, names):
        for listing in (self.plugins, self.order): listing.remove(names)

    def changes(self):
        return [(lst.path, lst.bytes()) for lst in (self.plugins, self.order) if lst.bytes() != lst.original]

    def reorder(self, name, direction):
        active = self.active(); index = next((i for i,n in enumerate(active) if n.casefold() == name.casefold()), None)
        if index is None: raise ValueError('Plugin não está ativo.')
        other = index + direction
        if other < 0 or other >= len(active): return
        a, b = active[index], active[other]
        for listing in (self.plugins, self.order):
            positions = {e[0].casefold(): i for i,line in enumerate(listing.lines) if (e := listing.entry(line))}
            if a.casefold() in positions and b.casefold() in positions:
                x, y = positions[a.casefold()], positions[b.casefold()]
                listing.lines[x], listing.lines[y] = listing.lines[y], listing.lines[x]
