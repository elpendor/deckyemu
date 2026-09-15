#!/usr/bin/env python3
"""Unpacking a Switch .nsz: every byte back, checked, in the room there is.

    python scripts/tests/test_switch_nsz.py

Needs libzstd and libcrypto, which a Deck and CI's Ubuntu both have; anywhere
else it says SKIP. Every package here is built from made-up sections and keys.
"""

import ctypes
import hashlib
import os
import random
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import TMP, check, section, summary  # noqa: E402

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "py_modules"))

import switch_nsz  # noqa: E402

if not switch_nsz.available():
    print("SKIP libzstd or libcrypto is not on this host, so nothing can be unpacked")
    sys.exit(0)

_zstd = ctypes.CDLL("libzstd.so.1")
_zstd.ZSTD_compressBound.argtypes = [ctypes.c_size_t]
_zstd.ZSTD_compressBound.restype = ctypes.c_size_t
# The destination by address: a string buffer passed as `c_char_p` is handed
# over as a copy, so zstd wrote into that and the buffer read back as zeros.
_zstd.ZSTD_compress.argtypes = [
    ctypes.c_void_p, ctypes.c_size_t, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_int]
_zstd.ZSTD_compress.restype = ctypes.c_size_t

_ROOT = os.path.join(TMP, "switch-nsz")
os.makedirs(_ROOT, exist_ok=True)


def compress(data):
    bound = _zstd.ZSTD_compressBound(len(data))
    out = ctypes.create_string_buffer(bound)
    size = _zstd.ZSTD_compress(ctypes.addressof(out), bound, data, len(data), 3)
    assert size <= bound, "zstd could not compress the made-up data"
    return out.raw[:size]


def pfs0(files):
    """A PFS0 package for [(name, bytes)], with no padding."""
    names = b"".join(name.encode() + b"\0" for name, _data in files)
    header = b"PFS0" + struct.pack("<II", len(files), len(names)) + b"\0" * 4
    offset = name_at = 0
    for name, data in files:
        header += struct.pack("<QQII", offset, len(data), name_at, 0)
        offset += len(data)
        name_at += len(name) + 1
    return header + names + b"".join(data for _name, data in files)


def listing(data):
    count, strings = struct.unpack_from("<II", data, 4)
    start = 16 + 24 * count + strings
    names = data[16 + 24 * count:start]
    out = {}
    for index in range(count):
        offset, size, name_at, _ = struct.unpack_from("<QQII", data, 16 + 24 * index)
        name = names[name_at:names.index(b"\0", name_at)].decode()
        out[name] = data[start + offset:start + offset + size]
    return out


def made_up_nca(seed, sizes):
    """(the NCA, its NCZ sections, the plaintext body) for sections of `sizes`.

    The first section is unencrypted, the rest alternate AES-CTR types 3 and 4
    with keys of their own -- the mix a real game has.
    """
    rng = random.Random(seed)
    header = rng.randbytes(0x4000)
    sections, plain, nca = [], b"", header
    offset = 0x4000
    for index, size in enumerate(sizes):
        # Half random, half repeating, so blocks both shrink and do not.
        data = rng.randbytes(size // 2) + (b"DeckyEmu" * size)[:size - size // 2]
        kind = 1 if index == 0 else (3 if index % 2 else 4)
        key = rng.randbytes(16)
        counter = rng.randbytes(16)
        if kind == 1:
            nca += data
        else:
            nca += switch_nsz._aes_ctr(key, counter[:8] + (offset >> 4).to_bytes(8, "big"), data)
        sections.append((offset, size, kind, key, counter))
        plain += data
        offset += size
    return nca, sections, plain


def ncz(nca, sections, plain, block_exponent=None, name=None):
    table = b"".join(struct.pack("<qqqq", o, s, k, 0) + key + counter
                     for o, s, k, key, counter in sections)
    body = b"NCZSECTN" + struct.pack("<q", len(sections)) + table
    if block_exponent is None:
        body += compress(plain)
    else:
        size = 1 << block_exponent
        stored = []
        for at in range(0, len(plain), size):
            chunk = plain[at:at + size]
            packed = compress(chunk)
            stored.append(packed if len(packed) < len(chunk) else chunk)
        body += b"NCZBLOCK" + struct.pack("<BBBBIq", 2, 1, 0, block_exponent, len(stored), len(plain))
        body += b"".join(struct.pack("<I", len(s)) for s in stored) + b"".join(stored)
    digest = hashlib.sha256(nca).hexdigest()[:32]
    return (name or digest) + ".ncz", nca[:0x4000] + body, digest + ".nca"


def folder(name):
    path = os.path.join(_ROOT, name)
    os.makedirs(path, exist_ok=True)
    return path


section("the AES wiring")

# NIST SP 800-38A F.5.1, CTR-AES128.Encrypt, the first two blocks: the second
# carries the counter across a byte, which a wrong increment would get wrong.
check("AES-128-CTR gives the published answer",
      switch_nsz._aes_ctr(
          bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c"),
          bytes.fromhex("f0f1f2f3f4f5f6f7f8f9fafbfcfdfeff"),
          bytes.fromhex("6bc1bee22e409f96e93d7e117393172aae2d8a571e03ac9c9eb76fac45af8e51")).hex(),
      "874d6191b620e3261bef6864990db6ce9806f66b7970fdff8617187bb9fffdff")


section("a solid .ncz comes back as the NCA it was made from")

_nca, _sections, _plain = made_up_nca(1, [0x8000, 0x20000, 0x6200])
_ncz_name, _ncz_data, _nca_name = ncz(_nca, _sections, _plain)
_ticket = b"a ticket" * 40
_solid = folder("solid")
_source = os.path.join(_solid, "Game [0100000000010000].nsz")
with open(_source, "wb") as _handle:
    _handle.write(pfs0([(_ncz_name, _ncz_data), ("0100000000010000.tik", _ticket)]))

_planned_name, _planned_size, _error = switch_nsz.plan(_source)
check("the plan names the .nsp after the .nsz", (_planned_name, _error),
      ("Game [0100000000010000].nsp", ""))

_reports = []
_names, _error = switch_nsz.into_folder(_source, _solid, lambda done, total: _reports.append((done, total)))
check("it unpacks", (_names, _error), (["Game [0100000000010000].nsp"], ""))
with open(os.path.join(_solid, _names[0]), "rb") as _handle:
    _out = _handle.read()
check("the size is the one planned", len(_out), _planned_size)
_inside = listing(_out)
check("the .ncz is an .nca again, and the ticket is still there",
      sorted(_inside), sorted([_nca_name, "0100000000010000.tik"]))
check("every byte of the NCA is the original", _inside[_nca_name] == _nca, True)
check("and the ticket is untouched", _inside["0100000000010000.tik"], _ticket)
check("the header is padded to a 0x20 boundary, as nsz pads it",
      (16 + 24 * 2 + struct.unpack_from("<I", _out, 8)[0]) % 0x20, 0)
check("the .nsz is left for the caller to delete", os.path.exists(_source), True)
check("no temporary file is left", [n for n in os.listdir(_solid) if n.endswith(".deckyemu-tmp")], [])
check("progress ends at the whole size", _reports[-1], (len(_out), len(_out)))


section("an NCZBLOCK .ncz, with blocks that shrank and blocks that did not")

_nca, _sections, _plain = made_up_nca(2, [0x6000, 0x9E00, 0x3200])
_ncz_name, _ncz_data, _nca_name = ncz(_nca, _sections, _plain, block_exponent=14)
_blocky = folder("blocks")
_source = os.path.join(_blocky, "Update.nsz")
with open(_source, "wb") as _handle:
    _handle.write(pfs0([(_ncz_name, _ncz_data)]))
_stored = struct.unpack_from("<I", _ncz_data, 0x4000 + 16 + 64 * 3 + 12)[0]
check("the made-up package really has a partial last block", len(_plain) % (1 << 14) != 0, True)
_names, _error = switch_nsz.into_folder(_source, _blocky)
check("it unpacks", (_names, _error), (["Update.nsp"], ""))
with open(os.path.join(_blocky, "Update.nsp"), "rb") as _handle:
    check("every byte of the NCA is the original", listing(_handle.read())[_nca_name] == _nca, True)


section("an update's NCA, split into a great many sections")

# A real update listed 169, and a limit of 64 refused it.
for _exponent, _label in ((None, "solid"), (14, "block")):
    _nca, _sections, _plain = made_up_nca(7, [0x2000] + [0x200] * 168)
    _ncz_name, _ncz_data, _nca_name = ncz(_nca, _sections, _plain, block_exponent=_exponent)
    _many = folder("many-%s" % _label)
    _source = os.path.join(_many, "Update.nsz")
    with open(_source, "wb") as _handle:
        _handle.write(pfs0([(_ncz_name, _ncz_data)]))
    _names, _error = switch_nsz.into_folder(_source, _many)
    check("169 sections unpack (%s)" % _label, (_names, _error), (["Update.nsp"], ""))
    with open(os.path.join(_many, "Update.nsp"), "rb") as _handle:
        check("and every byte is the original (%s)" % _label,
              listing(_handle.read())[_nca_name] == _nca, True)


section("what it refuses")

_nca, _sections, _plain = made_up_nca(3, [0x2000, 0x4000])
_bad = folder("mismatch")
_ncz_name, _ncz_data, _ = ncz(_nca, _sections, _plain, name="0" * 32)
_source = os.path.join(_bad, "Wrong.nsz")
with open(_source, "wb") as _handle:
    _handle.write(pfs0([(_ncz_name, _ncz_data)]))
_names, _error = switch_nsz.into_folder(_source, _bad)
check("an NCA that does not hash to its name is refused",
      (_names, "did not come out as the file it was made from" in _error), ([], True))
check("and nothing is left behind", sorted(os.listdir(_bad)), ["Wrong.nsz"])

_taken = folder("taken")
_ncz_name, _ncz_data, _ = ncz(_nca, _sections, _plain)
_source = os.path.join(_taken, "Game.nsz")
with open(_source, "wb") as _handle:
    _handle.write(pfs0([(_ncz_name, _ncz_data)]))
with open(os.path.join(_taken, "Game.nsp"), "wb") as _handle:
    _handle.write(b"somebody's own")
_names, _error = switch_nsz.into_folder(_source, _taken)
check("an .nsp of the same name is not replaced",
      (_names, "is already there" in _error), ([], True))
with open(os.path.join(_taken, "Game.nsp"), "rb") as _handle:
    check("and is still what it was", _handle.read(), b"somebody's own")

_plain_nsp = os.path.join(folder("plain"), "Plain.nsz")
with open(_plain_nsp, "wb") as _handle:
    _handle.write(pfs0([("0123.nca", b"x" * 100)]))
check("a package with nothing compressed in it says so",
      "nothing inside this .nsz is compressed" in switch_nsz.plan(_plain_nsp)[2], True)
_junk = os.path.join(folder("junk"), "Junk.nsz")
with open(_junk, "wb") as _handle:
    _handle.write(b"not a package at all" * 10)
check("a file that is not a package says so",
      "no package listing" in switch_nsz.plan(_junk)[2], True)


section("room for the .nsp but not for both")

_nca, _sections, _plain = made_up_nca(4, [0x10000, 0x60000, 0x10000])
_tight = folder("tight")
_ncz_name, _ncz_data, _nca_name = ncz(_nca, _sections, _plain)
_source = os.path.join(_tight, "Big.nsz")
with open(_source, "wb") as _handle:
    _handle.write(pfs0([(_ncz_name, _ncz_data), ("pad.cert", bytes(0x3000))]))
_total = switch_nsz.plan(_source)[1]
_source_size = os.path.getsize(_source)


class _Usage:
    def __init__(self, free):
        self.free = free


_real_usage, _real_margin = switch_nsz.shutil.disk_usage, switch_nsz._SPACE_MARGIN
_real_chunk, _real_step = switch_nsz._CHUNK, switch_nsz._RELEASE_STEP
try:
    switch_nsz._SPACE_MARGIN = 0
    switch_nsz._CHUNK = 1 << 14
    switch_nsz._RELEASE_STEP = 1 << 13
    if not switch_nsz._releasable(_source, _tight):
        print("SKIP this host's temporary folder cannot release part of a file")
    else:
        switch_nsz.shutil.disk_usage = lambda _path: _Usage(_total - _source_size // 2)
        _names, _error = switch_nsz.into_folder(_source, _tight)
        check("it unpacks by using the source up", (_names, _error), (["Big.nsp"], ""))
        with open(os.path.join(_tight, "Big.nsp"), "rb") as _handle:
            check("and every byte is still the original",
                  listing(_handle.read())[_nca_name] == _nca, True)
        check("the source really was released as it went",
              os.stat(_source).st_blocks * 512 < _source_size, True)
    # Written again: the case above used the first copy up, header and all.
    with open(_source, "wb") as _handle:
        _handle.write(pfs0([(_ncz_name, _ncz_data), ("pad.cert", bytes(0x3000))]))
    switch_nsz.shutil.disk_usage = lambda _path: _Usage(_total - _source_size - 1)
    _names, _error = switch_nsz.into_folder(_source, folder("full"))
    check("with not even that much room it refuses before writing",
          (_names, "not enough room" in _error), ([], True))
finally:
    switch_nsz.shutil.disk_usage = _real_usage
    switch_nsz._SPACE_MARGIN, switch_nsz._CHUNK = _real_margin, _real_chunk
    switch_nsz._RELEASE_STEP = _real_step


section("an .nsz update is kept as the .nsp, unpacked into its game's folder")

import gamecontent  # noqa: E402

_GAME = 0x0100000000020000
_UPDATE = _GAME | 0x800
_APP = "4000000002"


def update_nsz(path, seed):
    nca, sections, plain = made_up_nca(seed, [0x2000, 0x8000])
    name, data, nca_name = ncz(nca, sections, plain)
    with open(path, "wb") as handle:
        handle.write(pfs0([(name, data), ("%016x%016x.tik" % (_UPDATE, 12), b"t" * 64),
                           ("44.cnmt.nca", b"meta")]))
    return nca, nca_name


_inbox = folder("inbox")
_source = os.path.join(_inbox, "Some Game v1.0.1.nsz")
_nca, _nca_name = update_nsz(_source, 5)
check("an .nsz update is one the checks accept",
      gamecontent.check(_source, "%016x" % _GAME)[1], "")
_row, _error = gamecontent.add(_APP, _source, "%016x" % _GAME, _inbox)
check("it is kept", (_error, _row and _row["file"]), ("", "Some Game v1.0.1.nsp"))
_kept = os.path.join(gamecontent.store_dir(_APP), "Some Game v1.0.1.nsp")
with open(_kept, "rb") as _handle:
    check("as the .nsp, every byte of it", listing(_handle.read())[_nca_name] == _nca, True)
check("what Ryujinx is told about is the kept .nsp", _row["path"], _kept)
check("and the .nsz is gone from the transfer folder", os.path.exists(_source), False)

_elsewhere = os.path.join(folder("elsewhere"), "Some Game v1.0.2.nsz")
update_nsz(_elsewhere, 6)
with open(_elsewhere, "rb") as _handle:
    _before = _handle.read()
_row, _error = gamecontent.add(_APP, _elsewhere, "%016x" % _GAME, _inbox)
check("one kept anywhere else is unpacked too", (_error, _row and _row["file"]),
      ("", "Some Game v1.0.2.nsp"))
with open(_elsewhere, "rb") as _handle:
    check("and left exactly as it was", _handle.read() == _before, True)

summary()
