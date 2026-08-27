#!/usr/bin/env python3
"""The patcher refuses far more often than it acts.

    python scripts/tests/test_emu_patch.py

This is the one place in the plugin that edits somebody else's binary, and the
only interesting question about it is when it declines to. Every check here is a
refusal except two.

The binaries are synthesised rather than fetched: a real Vita3K AppImage is 66MB
and only exists on a Deck, and everything that decides whether a patch is safe --
finding a symbol, mapping a virtual address into the file, counting matches
inside those bounds -- is ordinary ELF structure that can be built in a few
lines. The layout below is the same one `emu_patch` reads.
"""

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402  -- installs the decky stub

import emu_patch  # noqa: E402
import emulator_catalog  # noqa: E402


#: Where the synthetic image claims to be loaded. Deliberately not zero, so a
#: patcher that confused a virtual address with a file offset would be caught
#: rather than accidentally right.
_BASE = 0x400000
_TEXT_AT = 0x200


def elf(text, symbols, *, strip=False):
    """A minimal ELF64 holding `text`, with `symbols` as {name: (offset, size)}.

    Offsets are relative to the start of the text, which is where a caller
    thinks in; the symbol table records them as virtual addresses, which is what
    the patcher has to convert back.
    """
    text = bytes(text)
    body = bytearray(b"\0" * _TEXT_AT + text)

    names = bytearray(b"\0")
    entries = bytearray(b"\0" * 24)          # the mandatory null symbol
    for name, (at, size) in symbols.items():
        entries += struct.pack("<IBBHQQ", len(names), 0x12, 0, 1,
                               _BASE + _TEXT_AT + at, size)
        names += name.encode() + b"\0"

    strtab_at = len(body)
    body += names
    symtab_at = len(body)
    body += entries
    shstr = b"\0.text\0.strtab\0.symtab\0.shstrtab\0"
    shstr_at = len(body)
    body += shstr

    def header(name, kind, addr, offset, size, link=0, entsize=0):
        return struct.pack("<IIQQQQIIQQ", shstr.index(name.encode() + b"\0"),
                           kind, 0, addr, offset, size, link, 0, 1, entsize)

    sections = [struct.pack("<IIQQQQIIQQ", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
                header(".text", 1, _BASE + _TEXT_AT, _TEXT_AT, len(text))]
    if not strip:
        sections += [
            header(".strtab", 3, 0, strtab_at, len(names)),
            header(".symtab", 2, 0, symtab_at, len(entries), link=2, entsize=24),
        ]
    sections.append(header(".shstrtab", 3, 0, shstr_at, len(shstr)))

    shoff = len(body)
    body += b"".join(sections)

    head = bytearray(64)
    head[0:16] = b"\x7fELF\x02\x01\x01" + b"\0" * 9
    struct.pack_into("<HHI", head, 0x10, 3, 62, 1)        # ET_DYN, x86-64
    struct.pack_into("<Q", head, 0x20, 64)                # e_phoff
    struct.pack_into("<Q", head, 0x28, shoff)
    struct.pack_into("<HHHHHH", head, 0x34,
                     64, 56, 1, 64, len(sections), len(sections) - 1)

    # One PT_LOAD covering the file, so a virtual address maps back by
    # subtraction -- the same shape as a real image, one segment simpler.
    phdr = struct.pack("<IIQQQQQQ", 1, 5, 0, _BASE, _BASE,
                       len(body) + 56, len(body) + 56, 0x1000)

    # `body` was laid out from file offset zero and its first 120 bytes are
    # padding, which is exactly the room the two headers need.
    return bytearray(head + phdr + body[120:])


_SPEC = {"file": "usr/bin/App", "within": "target",
         "find": "41030c24", "replace": "31c99090"}


section("The site is found by symbol, not by scanning the file")

# The whole reason `within` is required. These four bytes appear three times
# here and nine times in a real Vita3K binary; only one of them is the
# instruction that matters, and a patcher without bounds would pick by luck.
_decoy = bytes.fromhex("41030c24")
_text = (_decoy + b"\x90" * 12          # a decoy before the function
         + b"\x55\x48\x89\xe5" + _decoy + b"\xc3"   # the function itself
         + b"\x90" * 8 + _decoy)        # and one after
_fn_at = len(_decoy) + 12
_image = elf(_text, {"target": (_fn_at, 9)})

check("the four bytes really are ambiguous file-wide",
      bytes(_image).count(_decoy), 3)

_at, _error = emu_patch.patch_bytes(_image, _SPEC)
check("but exactly one sits inside the symbol, and that is the one patched",
      _error, "")
check("the patched bytes are where the symbol is",
      bytes(_image[_TEXT_AT + _fn_at + 4:_TEXT_AT + _fn_at + 8]).hex(),
      "31c99090")
check("and the decoys either side of it are untouched",
      (bytes(_image[_TEXT_AT:_TEXT_AT + 4]).hex(),
       bytes(_image[_TEXT_AT + len(_text) - 4:_TEXT_AT + len(_text)]).hex()),
      ("41030c24", "41030c24"))


section("Everything else is a refusal")

# Zero matches is the expected future: upstream changes that function, or fixes
# the bug, and the description stops fitting. Nothing is written.
_none = elf(b"\x55\x48\x89\xe5\xc3", {"target": (0, 5)})
_before = bytes(_none)
_at, _error = emu_patch.patch_bytes(_none, _SPEC)
check("a build the bytes are not in is refused", bool(_error), True)
check("and says the build changed rather than something cryptic",
      "changed" in _error, True)
check("and the file is byte-for-byte what it was",
      bytes(_none) == _before, True)

# Two inside one function means the description is not specific enough to act
# on. Refusing is the only safe answer -- patching "the first one" is a guess.
_twice = elf(_decoy + b"\x90\x90" + _decoy, {"target": (0, 10)})
_at, _error = emu_patch.patch_bytes(_twice, _SPEC)
check("two matches inside the symbol is also refused", bool(_error), True)
check("and it says how many it found", "found 2" in _error, True)

# A stripped build is the other expected future, and the reason the symbol
# lookup returns None for "no table" and "no such name" alike.
_stripped = elf(_text, {"target": (_fn_at, 9)}, strip=True)
_at, _error = emu_patch.patch_bytes(_stripped, _SPEC)
check("a stripped build is refused", bool(_error), True)
check("and names the symbol it could not find", "target" in _error, True)

_absent = elf(_text, {"other": (_fn_at, 9)})
check("so is one where the function is simply gone",
      bool(emu_patch.patch_bytes(_absent, _SPEC)[1]), True)

# Nothing may change size. The file is full of addresses computed at link time,
# and inserting or removing a byte moves every one of them.
_uneven = elf(_text, {"target": (_fn_at, 9)})
check("replacing with a different length is refused",
      "same length" in emu_patch.patch_bytes(
          _uneven, dict(_SPEC, replace="31c9"))[1],
      True)
check("and bytes that are not hex are refused",
      "hex" in emu_patch.patch_bytes(_uneven, dict(_SPEC, find="zz"))[1], True)
check("and something that is not an ELF at all is refused",
      bool(emu_patch.patch_bytes(bytearray(b"not an elf" * 40), _SPEC)[1]), True)


section("Nothing is patched outside the package")

# The path comes from the catalog, which is ours -- and is still checked,
# because the cost of being wrong is writing to a file outside the AppImage.
check("an absolute path is refused", emu_patch._safe_member("/etc/passwd"), False)
check("and so is one climbing out",
      emu_patch._safe_member("usr/../../../etc/passwd"), False)
check("an ordinary member is fine", emu_patch._safe_member("usr/bin/Vita3K"), True)
check("and an empty one is not", emu_patch._safe_member(""), False)


section("Which build a game runs")

_entry = emulator_catalog.find("vita3k")

check("the patched copy is named after the stock build and the fix",
      emu_patch.patched_name("Vita3K-x86_64.AppImage", "vita-motion"),
      "Vita3K-x86_64.AppImage.vita-motion")

# `emulators.save` carries `target`, so a record that already names a patched
# build must not have the suffix appended a second time.
check("resolving a patched path back to the stock one is idempotent",
      emu_patch.stock_path(
          "/x/Vita3K-x86_64.AppImage.vita-motion", _entry),
      "/x/Vita3K-x86_64.AppImage")
check("and a stock path is left alone",
      emu_patch.stock_path("/x/Vita3K-x86_64.AppImage", _entry),
      "/x/Vita3K-x86_64.AppImage")

# Absent means stock, which is the whole fallback: a build that could not be
# patched runs unmodified rather than not at all.
check("a patched build that does not exist resolves to nothing",
      emu_patch.target_for("/nowhere/Vita3K-x86_64.AppImage", "vita-motion"), "")
check("and an id that could never be a filename is refused",
      emu_patch.target_for("/x/App", "../../etc"), "")

check("Vita3K is the entry that carries a patch",
      [e["id"] for e in emulator_catalog.CATALOG if emu_patch.patch_specs(e)],
      ["vita3k"])
check("and shadPS4 carries none, because its fix is reachable at launch",
      emu_patch.patch_specs(emulator_catalog.find("shadps4")), [])

if __name__ == "__main__":
    summary()
