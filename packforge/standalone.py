"""Attach a pack as a data entry to our unsigned PyInstaller 6 template."""
import struct
import zlib
from pathlib import Path

from .common import PackError

COOKIE = struct.Struct("!8sIIII64s")
ENTRY = struct.Struct("!IIIIBc")
MAGIC = b"MEI\014\013\012\013\016"


def attach_pack(template: Path, bundle: Path, output: Path):
    data = template.read_bytes()
    if len(data) < COOKIE.size:
        raise PackError("Повреждён встроенный шаблон установщика")
    magic, length, toc_offset, toc_length, python_version, library = COOKIE.unpack(data[-COOKIE.size:])
    if magic != MAGIC or length > len(data):
        raise PackError("Неподдерживаемый шаблон установщика")
    start = len(data) - length
    toc = data[start + toc_offset:start + toc_offset + toc_length]
    raw = bundle.read_bytes()
    compressed = zlib.compress(raw)
    name = b"payload\\pack.zip\0"
    entry_length = (ENTRY.size + len(name) + 15) // 16 * 16
    entry = ENTRY.pack(entry_length, toc_offset, len(compressed), len(raw), 1, b"x")
    entry += name.ljust(entry_length - ENTRY.size, b"\0")
    new_toc = toc + entry
    new_offset = toc_offset + len(compressed)
    cookie = COOKIE.pack(MAGIC, new_offset + len(new_toc) + COOKIE.size,
                         new_offset, len(new_toc), python_version, library)
    output.write_bytes(data[:start + toc_offset] + compressed + new_toc + cookie)
