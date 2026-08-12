"""Whether an Xbox disc image has anything on it to boot.

An Xbox game disc boots exactly one way: the BIOS loads `default.xbe` from the
root of the disc. An image without one is not a game, and the console says so in
the least useful way available -- it draws "Please insert an Xbox disc" on a
black screen, which reads as a broken emulator, a missing BIOS, or a bad
controller long before it reads as a bad file.

That happened here with a Championship Manager image whose root held a single
`data/` folder and no executable anywhere. Every part of the emulator was
correct; the disc simply had no game in it. This module exists so the panel can
say that when the file is added, in the one place where the user is still
thinking about the file.

**Silence is the default.** `.iso` is the most overloaded extension in the
catalog -- GameCube, Wii, PS2, PSP and Xbox all use it -- so nothing here
comments on an image that is not an Xbox one. The XDVDFS magic is what makes the
difference between "this Xbox disc is empty" and "this is not an Xbox disc",
and only the first is worth saying.
"""

import os
import struct

import decky

# Xbox discs are XDVDFS, whose header sits one sector into the filesystem. The
# offset varies by how the image was produced: a plain XISO starts at zero, and
# a redump-style image keeps the video partition first, putting the game
# 0x18300000 bytes in. Both are real things people have, so both are looked for.
MAGIC = b"MICROSOFT*XBOX*MEDIA"
HEADER_AT = 0x10000
SECTOR = 2048
BASES = (0, 0x18300000, 0x2070000)

# A root directory table is a few kilobytes. Anything claiming more is not one,
# and this is read from a file that arrived over the network.
MAX_ROOT_BYTES = 1024 * 1024

# The one file the BIOS looks for.
BOOT_FILE = "default.xbe"


def inspect(path):
    """{xbox, bootable, entries} for a disc image.

    `xbox` false means "not an Xbox disc image", which is not a complaint: it is
    the answer for every GameCube, PS2 and PSP .iso as well, and for a file that
    could not be read at all. Callers should say nothing in that case.

    Never raises. This parses a binary format from a file somebody sent, and a
    malformed one means "no opinion", not a failure.
    """
    result = {"xbox": False, "bootable": False, "certain": False, "entries": []}
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            base = _find_base(handle, size)
            if base is None:
                return result
            result["xbox"] = True

            handle.seek(base + HEADER_AT)
            header = handle.read(0x20)
            if len(header) < 0x20:
                return result
            root_sector, root_size = struct.unpack_from("<II", header, 0x14)
            if not root_size or root_size > MAX_ROOT_BYTES:
                return result

            handle.seek(base + root_sector * SECTOR)
            table = handle.read(root_size)
    except (OSError, struct.error):
        return result

    entries, complete = _entries(table)
    result["entries"] = sorted(name for name, _ in entries)
    result["bootable"] = any(name.lower() == BOOT_FILE for name, _ in entries)
    # A root this could not read to the end proves nothing about what is not in
    # it. `certain` is what lets the panel refuse a file: absence of default.xbe
    # is only evidence when the whole root was seen.
    result["certain"] = complete
    return result


def _find_base(handle, size):
    for base in BASES:
        if base + HEADER_AT + len(MAGIC) > size:
            continue
        handle.seek(base + HEADER_AT)
        if handle.read(len(MAGIC)) == MAGIC:
            return base
    return None


# Entry: uint16 left, uint16 right, uint32 sector, uint32 size, uint8 attributes,
# uint8 name length, then the name. Offsets are in units of four bytes.
_ENTRY = "<HHIIB"
_ENTRY_HEAD = 14


# Every node is visited at most once, so this only has to exceed the number of
# files a real disc root can hold. A cap on tree *depth* was tried first and was
# wrong in a way that matters: XDVDFS trees need not be balanced, so a root
# chained down one side would have been truncated, and a disc reported as having
# no default.xbe when it has one. Whether that report is trustworthy decides
# whether the panel may refuse the file, so the bound has to be one that a real
# disc cannot reach.
MAX_ENTRIES = 8192


def _entries(table):
    """[(name, is_dir)] from a root directory table, and whether it is complete.

    The table is a binary tree, from an image somebody else made. Visited
    offsets are tracked, so a cycle or a self-referential node cannot spin here.
    """
    found = []
    seen = set()
    stack = [0]
    complete = True
    while stack:
        if len(seen) >= MAX_ENTRIES:
            # Say so rather than return a short list that reads as a full one.
            decky.logger.warning("XDVDFS root exceeded %d entries", MAX_ENTRIES)
            complete = False
            break
        offset = stack.pop()
        at = offset * 4
        if at in seen or at + _ENTRY_HEAD > len(table):
            continue
        seen.add(at)
        try:
            left, right, _sector, _size, attributes = struct.unpack_from(_ENTRY, table, at)
        except struct.error:
            continue
        length = table[at + 13]
        name = table[at + _ENTRY_HEAD:at + _ENTRY_HEAD + length].decode("latin-1", "replace")
        if name:
            found.append((name, bool(attributes & 0x10)))
        if left:
            stack.append(left)
        if right:
            stack.append(right)

    if not found:
        decky.logger.info("XDVDFS root parsed but held no entries")
    return found, complete
