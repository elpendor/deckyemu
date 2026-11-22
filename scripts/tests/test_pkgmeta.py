#!/usr/bin/env python3
"""A package's own title, read before it installs.

    python scripts/tests/test_pkgmeta.py

Packages built here in each console's layout, around a made-up game: a PS4
entry table, a Vita metadata block, and a PS3 item table encrypted the way a
retail package is (skipped where libcrypto cannot be loaded).
"""

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import TMP, check, make_sfo, section, summary  # noqa: E402

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "py_modules"))

import pkgmeta  # noqa: E402
import switch_nsz  # noqa: E402

_DIR = os.path.join(TMP, "pkgmeta")
os.makedirs(_DIR, exist_ok=True)
_SFO = make_sfo([("TITLE", "Harbor\nDash"), ("TITLE_ID", "PCSA99999")])


def _write(name, data):
    path = os.path.join(_DIR, name)
    with open(path, "wb") as handle:
        handle.write(data)
    return path


def _ps4():
    head = bytearray(0x100)
    head[:4] = pkgmeta.PS4_MAGIC
    struct.pack_into(">I", head, 0x10, 2)          # two entries
    struct.pack_into(">I", head, 0x18, 0x100)      # entry table
    table = bytearray(64)
    struct.pack_into(">IIIIII", table, 0, 0x1200, 0, 0, 0, 0, 0)
    struct.pack_into(">IIIIII", table, 32, 0x1000, 0, 0, 0, 0x140, len(_SFO))
    return bytes(head + table) + _SFO


def _vita():
    head = bytearray(0x100)
    head[:4] = pkgmeta.PKG_MAGIC
    struct.pack_into(">II", head, 8, 0x100, 1)     # one metadata block
    block = struct.pack(">IIII", 14, 8, 0x110, len(_SFO))
    return bytes(head) + block + _SFO


def _ps3():
    iv = bytes(range(16))
    head = bytearray(0x100)
    head[:4] = pkgmeta.PKG_MAGIC
    struct.pack_into(">I", head, 20, 2)            # two items
    struct.pack_into(">Q", head, 32, 0x100)        # encrypted area
    head[0x70:0x80] = iv
    name_at, data_at = 0x40, 0x60
    items = bytearray(64)
    struct.pack_into(">IIQQ", items, 0, 0x50, 4, 0, 0)          # some other file
    struct.pack_into(">IIQQ", items, 32, name_at, 9, data_at, len(_SFO))
    plain = bytes(items) + b"PARAM.SFO".ljust(16, b"\x00") + b"ICON".ljust(16, b"\x00") + _SFO
    return bytes(head) + pkgmeta._ctr(pkgmeta._PS3_KEY, iv, 0, plain)


section("each console's package names its game")

check("PS4, from its entry table", pkgmeta.package_title(_write("a.pkg", _ps4())), "Harbor Dash")
check("Vita, from its metadata block", pkgmeta.package_title(_write("b.pkg", _vita())), "Harbor Dash")
if switch_nsz.available():
    check("PS3, from its encrypted items", pkgmeta.package_title(_write("c.pkg", _ps3())), "Harbor Dash")
check("anything else names nothing", pkgmeta.package_title(_write("d.pkg", b"not a package")), "")
check("nor does a file that is not there", pkgmeta.package_title(os.path.join(_DIR, "gone.pkg")), "")

if __name__ == "__main__":
    summary()
