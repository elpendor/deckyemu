"""PARAM.SFO / param.sfo -- the file that says what a game is called.

Sony used the same container on the PS3 and the PS4, and both emulators here
depend on it for the same reason: a game installed from a package has no
filename worth showing. RPCS3 unpacks to `dev_hdd0/game/NPUB30133`, shadPS4
looks for `sce_sys/param.sfo` beside an `eboot.bin`, and in both cases the only
place the words "Braid" exist is inside this file.

Shared rather than duplicated because it really is the same format, down to the
byte -- the PS4's is lowercase on disk and identical inside.
"""

import os
import struct

MAGIC = b"\x00PSF"
_HEADER = "<4sIIII"
_ENTRY = "<HHIII"
_ENTRY_SIZE = 16

# Value formats. 0x0004 is a string that is not null-terminated, 0x0204 one that
# is, 0x0404 a little-endian uint32. Anything else is left alone rather than
# guessed at.
_UTF8_SPECIAL = 0x0004
_UTF8 = 0x0204
_UINT32 = 0x0404

# A param.sfo is a page or two. Anything larger is not one.
MAX_BYTES = 1024 * 1024


def read(path):
    """Parse a param.sfo into a plain dict, or {} if it is not one.

    Never raises: this reads files produced by an emulator unpacking somebody
    else's package, and a malformed one means "skip this game", not a failure.
    """
    try:
        if os.path.getsize(path) > MAX_BYTES:
            return {}
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError:
        return {}
    return read_bytes(data)


def read_bytes(data):
    """The same, for an SFO already in hand.

    A Vita release keeps its param.sfo inside a zip, and reading it from the
    archive costs a couple of kilobytes where unpacking a 4GB release to reach
    the same bytes would not.
    """
    if len(data) < struct.calcsize(_HEADER) or not data.startswith(MAGIC):
        return {}

    try:
        _magic, _version, key_table, data_table, count = struct.unpack_from(_HEADER, data, 0)
        entries = {}
        for index in range(count):
            offset = struct.calcsize(_HEADER) + index * _ENTRY_SIZE
            key_offset, fmt, length, _max_length, value_offset = struct.unpack_from(
                _ENTRY, data, offset
            )

            start = key_table + key_offset
            end = data.index(b"\x00", start)
            key = data[start:end].decode("utf-8", "replace")

            raw = data[data_table + value_offset:data_table + value_offset + length]
            if fmt in (_UTF8, _UTF8_SPECIAL):
                entries[key] = raw.split(b"\x00", 1)[0].decode("utf-8", "replace")
            elif fmt == _UINT32 and len(raw) >= 4:
                entries[key] = struct.unpack("<I", raw[:4])[0]
        return entries
    except (struct.error, ValueError, IndexError):
        return {}
