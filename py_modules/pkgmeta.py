"""A PlayStation package's own name, read without installing it.

A `.pkg` arrives named whatever its sender called it -- `nfsmw-HckXX...pkg` --
and its real title is inside, in the game's param.sfo. Reading that takes a few
kilobytes, not the unpack: so the review can name the game, and look up its
artwork, before anything installs.

  * PS4: param.sfo is an unencrypted entry in the package's file table.
  * Vita: an app package keeps a plain copy, pointed at by metadata block 14.
  * PS3: param.sfo is an item encrypted with the public PS3 package key, the
    same AES-CTR the Switch unpacker runs through the system's libcrypto.

Layouts follow psdevwiki and pkg2zip (public domain).
"""

import struct

import sfo

PKG_MAGIC = b"\x7fPKG"
PS4_MAGIC = b"\x7fCNT"

# The PS3 retail package key: every PS3 package's items are encrypted with it.
_PS3_KEY = bytes.fromhex("2e7b71d7c9c9a14ea3221f188828b8f8")

_PS4_SFO_ENTRY = 0x1000
_ITEM_SIZE = 32
# Enough for any real package's table; a corrupt count cannot run away.
_MAX_ITEMS = 50000
_MAX_SFO = 64 * 1024


def package_title(path):
    """The title in a PS3, PS4 or Vita package's param.sfo, or ''."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(0x100)
            if head.startswith(PS4_MAGIC):
                param = _ps4_sfo(handle)
            elif head.startswith(PKG_MAGIC):
                param = _vita_sfo(handle, head) or _ps3_sfo(handle, head)
            else:
                return ""
    except (OSError, struct.error, ValueError):
        return ""
    title = (sfo.read_bytes(param) if param else {}).get("TITLE", "")
    # Titles carry line breaks where the console's menu wraps them.
    return " ".join(str(title).split())


def ps3_needs_licence(path):
    """True, False, or None when unknown: whether a PS3 package needs a .rap.

    Metadata block 1 is the package's DRM type, in plain text: 1 network and
    2 local need a licence, 3 is free. Anything else is not said.
    """
    try:
        with open(path, "rb") as handle:
            head = handle.read(0x100)
            if not head.startswith(PKG_MAGIC):
                return None
            offset, count = struct.unpack_from(">II", head, 8)
            for _ in range(min(count, 64)):
                handle.seek(offset)
                kind, size = struct.unpack(">II", handle.read(8))
                if kind == 1 and size >= 4:
                    drm = struct.unpack(">I", handle.read(4))[0]
                    return {1: True, 2: True, 3: False}.get(drm)
                offset += 8 + size
    except (OSError, struct.error, ValueError):
        return None
    return None


def _ps4_sfo(handle):
    """param.sfo from a PS4 package's entry table."""
    handle.seek(0x10)
    count = struct.unpack(">I", handle.read(4))[0]
    handle.seek(0x18)
    table = struct.unpack(">I", handle.read(4))[0]
    for index in range(min(count, _MAX_ITEMS)):
        handle.seek(table + index * 32)
        entry_id, _name, _flags1, _flags2, offset, size = struct.unpack(
            ">IIIIII", handle.read(24))
        if entry_id == _PS4_SFO_ENTRY and 0 < size <= _MAX_SFO:
            handle.seek(offset)
            return handle.read(size)
    return b""


def _metadata(handle, head):
    """{block type: (offset, size)} from a PS3 or Vita package header."""
    offset, count = struct.unpack_from(">II", head, 8)
    blocks = {}
    for _ in range(min(count, 64)):
        handle.seek(offset)
        kind, size = struct.unpack(">II", handle.read(8))
        if size >= 8:
            blocks[kind] = struct.unpack(">II", handle.read(8))
        offset += 8 + size
    return blocks


def _vita_sfo(handle, head):
    """The plain param.sfo a Vita app package carries in metadata block 14."""
    sfo_at, sfo_size = _metadata(handle, head).get(14, (0, 0))
    if not sfo_at or not 0 < sfo_size <= _MAX_SFO:
        return b""
    handle.seek(sfo_at)
    return handle.read(sfo_size)


def _ctr(key, iv, offset, data):
    """AES-128-CTR of `data` at `offset` into the encrypted area."""
    import switch_nsz  # libcrypto through ctypes; loaded only for PS3

    counter = (int.from_bytes(iv, "big") + offset // 16) % (1 << 128)
    return switch_nsz._aes_ctr(key, counter.to_bytes(16, "big"), data)


def _ps3_sfo(handle, head):
    """PARAM.SFO from a PS3 package's encrypted item table."""
    item_count = struct.unpack_from(">I", head, 20)[0]
    data_start = struct.unpack_from(">Q", head, 32)[0]
    iv = head[0x70:0x80]
    try:
        for index in range(min(item_count, _MAX_ITEMS)):
            at = index * _ITEM_SIZE
            handle.seek(data_start + at)
            item = _ctr(_PS3_KEY, iv, at, handle.read(_ITEM_SIZE))
            name_at, name_size, data_at, data_size = struct.unpack(">IIQQ", item[:24])
            if name_size != len("PARAM.SFO") or not 0 < data_size <= _MAX_SFO:
                continue
            handle.seek(data_start + name_at)
            if _ctr(_PS3_KEY, iv, name_at, handle.read(name_size)) != b"PARAM.SFO":
                continue
            handle.seek(data_start + data_at)
            return _ctr(_PS3_KEY, iv, data_at, handle.read(data_size))
    except Exception:  # noqa: BLE001 -- no libcrypto, or a damaged table
        return b""
    return b""
