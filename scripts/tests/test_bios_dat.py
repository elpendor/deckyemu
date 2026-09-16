#!/usr/bin/env python3
"""A BIOS recognised by its checksum when its name says nothing.

    python scripts/tests/test_bios_dat.py

libretro's `System.dat` gives the MD5 of every BIOS its cores read. With it a
dump sent as `PS1 US.bin` still lands where SwanStation opens `scph5501.bin`,
and DuckStation, which tells its BIOS files apart itself, takes any PS1 BIOS.
Without it -- no network, never fetched -- matching is by name, as before.

The list here is made up, and so is every byte hashed against it.
"""

import hashlib
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import TMP, check, section, summary  # noqa: E402  -- installs the decky stub

import bios_dat  # noqa: E402
import emu_firmware  # noqa: E402
import emu_install  # noqa: E402
import sysenv  # noqa: E402

_BIOS = b"\x5a" * 4096
_OTHER = b"\x3c" * 4096
_MD5 = hashlib.md5(_BIOS).hexdigest()

_DAT = """clrmamepro (
\tname "System"
)

game (
\tname "System"

\tcomment "Made Up - Console"
\trom ( name made_bios.bin size 4096 crc 00000000 md5 %s sha1 0000000000000000000000000000000000000000 )
\trom ( name "sub/alias_bios.bin" size 4096 crc 00000000 md5 %s sha1 0000000000000000000000000000000000000000 )
)
""" % (_MD5, _MD5)

section("BIOS checksum list -- reading it")

_table = bios_dat.parse(_DAT)
check("a checksum is read with every name it goes by",
      _table[_MD5]["names"], ["made_bios.bin", "alias_bios.bin"])
check("and the system it belongs to", _table[_MD5]["system"], "Made Up - Console")

section("BIOS checksum list -- matching by content")

_home = os.path.join(TMP, "biosdat")
_real_home = sysenv.user_home
sysenv.user_home = lambda: _home
_saved_state = emu_firmware.read_state()
emu_firmware._write_state({})
try:
    _inbox = emu_install.firmware_dir()
    for _name in os.listdir(_inbox):
        os.remove(os.path.join(_inbox, _name))

    def _send(name, payload):
        with io.open(os.path.join(_inbox, name), "wb") as handle:
            handle.write(payload)

    _core = {"id": "retroarch", "name": "RetroArch", "firmware": [{
        "name": "made_bios.bin", "match": r"(?i)^made_bios\.bin$", "as": "made_bios.bin",
        "dest": "system",
    }]}
    _standalone = {"id": "standalone", "name": "Standalone", "firmware": [{
        "name": "BIOS", "match": r"(?i)^scph\d{4}\.bin$", "system": "Made Up - Console",
        "dest": ".var/app/org.example.Standalone/bios",
    }]}

    _send("My Console BIOS.bin", _BIOS)
    _send("not a bios.bin", _OTHER)

    bios_dat.use({})
    check("with no list loaded a misnamed dump matches nothing",
          emu_firmware.status(_core, shared=[])[0]["waiting"], [])

    bios_dat.use(_table)
    check("with the list, a core's row takes the dump whatever it is called",
          emu_firmware.status(_core, shared=[])[0]["waiting"], ["My Console BIOS.bin"])
    check("an emulator that knows its own BIOS files takes any of that system",
          emu_firmware.status(_standalone, shared=[])[0]["waiting"], ["My Console BIOS.bin"])
    check("a file of the same size that is not a known BIOS is left alone",
          "not a bios.bin" in emu_firmware.status(_standalone, shared=[])[0]["waiting"], False)

    # A right name over the wrong contents: installs, and then fails in the
    # game with nothing pointing back here. Said on the row instead.
    _send("made_bios.bin", _OTHER)
    _row = emu_firmware.status(_core, shared=[])[0]
    check("a dump under the right name but unknown contents is flagged",
          _row["unrecognised"], ["made_bios.bin"])
    check("a recognised one is not",
          "My Console BIOS.bin" in _row["unrecognised"], False)
    bios_dat.use({})
    check("and nothing is flagged without a list to judge by",
          emu_firmware.status(_core, shared=[])[0]["unrecognised"], [])
    bios_dat.use(_table)
    os.remove(os.path.join(_inbox, "made_bios.bin"))

    _result = emu_firmware.install(_core, "made_bios.bin", shared=[])
    check("it lands under the name the core opens", _result["copied"], ["made_bios.bin"])
    check("and reads as in place",
          emu_firmware.status(_core, shared=[])[0]["installed"], ["made_bios.bin"])

    # And the same file reaches an emulator that wants it by content, through
    # sharing -- the case a PS1 BIOS installed for DuckStation under its own
    # name was stuck on.
    _shared = emu_firmware.installed_elsewhere([_core, _standalone])
    check("a file one emulator holds is recognised for another by content",
          [item["name"] for item in emu_firmware.status(_standalone, shared=_shared)[0]["elsewhere"]],
          ["made_bios.bin"])

    # A dump the list does not know is installed only by a press, never spread.
    _named = {"id": "named", "name": "Named", "firmware": [{
        "name": "scph0000.bin", "match": r"(?i)^scph0000\.bin$", "as": "scph0000.bin",
        "dest": ".var/app/org.example.Named/bios",
    }]}
    _twin = {"id": "twin", "name": "Twin", "firmware": [dict(
        _named["firmware"][0], dest=".var/app/org.example.Twin/bios")]}
    _send("scph0000.bin", _OTHER)
    emu_firmware.install(_named, "scph0000.bin", shared=[])
    _shared = emu_firmware.installed_elsewhere([_named, _twin])
    check("a held file that is not a known dump is flagged where it is offered",
          emu_firmware.status(_twin, shared=_shared)[0]["unrecognised"], ["scph0000.bin"])
    check("and is not shared unasked", emu_firmware.share_held(_twin, _shared), [])
finally:
    bios_dat.use({})
    emu_firmware._write_state(_saved_state)
    if os.path.isfile(emu_firmware.DECLINED_PATH):
        os.remove(emu_firmware.DECLINED_PATH)
    sysenv.user_home = _real_home


if __name__ == "__main__":
    summary()
