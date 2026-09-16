#!/usr/bin/env python3
"""A BIOS installed for one emulator is offered to the next one that wants it.

    python scripts/tests/test_firmware_shared.py

Installing moves a file out of the transfer folder, which is right -- a copy
left a duplicate of every BIOS ever sent -- and it meant a second emulator
wanting the same dump found nothing and asked for it to be sent again. The file
was on the Deck the whole time, in the first emulator's folder.

So a requirement with nothing sent and nothing in place looks at what the other
emulators hold, and installing puts the same file in place as a hard link. Not a
symlink: each emulator is a flatpak that cannot see another one's folder, so a
symlink between them only resolves where something granted the whole home --
which EmuDeck does, so it would pass on exactly the Decks it was tried on.

The entries here are made up, and so is every byte of every file.
"""

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import TMP, check, section, summary  # noqa: E402  -- installs the decky stub

import emu_firmware  # noqa: E402
import emu_install  # noqa: E402
import sysenv  # noqa: E402


def _entry(entry_id, name, dest, match=r"(?i)^dummy-bios\.bin$"):
    return {
        "id": entry_id,
        "name": name,
        "firmware": [{"name": "Dummy BIOS", "match": match, "dest": dest}],
    }


FIRST = _entry("first", "First Emulator", ".var/app/org.example.First/bios")
SECOND = _entry("second", "Second Emulator", ".var/app/org.example.Second/system")
# Wants a different file, so it must never be offered this one.
OTHER = _entry("other", "Other Emulator", ".var/app/org.example.Other/bios",
               match=r"(?i)^unrelated\.bin$")
CATALOG = [FIRST, SECOND, OTHER]


section("firmware -- one dump, every emulator that wants it")

_home = os.path.join(TMP, "fwshared")
_real_home = sysenv.user_home
sysenv.user_home = lambda: _home
# The install record is shared by the whole suite; set it aside and put it back.
_saved_state = emu_firmware.read_state()
emu_firmware._write_state({})
try:
    _inbox = emu_install.firmware_dir()
    for _name in os.listdir(_inbox):
        os.remove(os.path.join(_inbox, _name))
    with io.open(os.path.join(_inbox, "dummy-bios.bin"), "wb") as _handle:
        _handle.write(b"not a real dump")

    check("the first emulator installs what was sent",
          emu_firmware.install(FIRST, "Dummy BIOS", shared=[])["copied"],
          ["dummy-bios.bin"])
    _held = os.path.join(_home, ".var", "app", "org.example.First", "bios", "dummy-bios.bin")

    _shared = emu_firmware.installed_elsewhere(CATALOG)
    _row = emu_firmware.status(SECOND, shared=_shared)[0]
    check("the second is offered the file the first holds",
          _row["elsewhere"], [{"name": "dummy-bios.bin", "from": "First Emulator"}])
    check("while nothing is waiting in the transfer folder", _row["waiting"], [])
    check("an emulator wanting a different file is offered nothing",
          emu_firmware.status(OTHER, shared=_shared)[0]["elsewhere"], [])
    check("and the holder is not offered its own file",
          emu_firmware.status(FIRST, shared=_shared)[0]["elsewhere"], [])

    _result = emu_firmware.install(SECOND, "Dummy BIOS", shared=_shared)
    check("installing shares it", _result["linked"], ["dummy-bios.bin"])
    check("and names where it came from", _result["shared_from"], ["First Emulator"])
    check("the first emulator still has its copy", os.path.isfile(_held), True)
    _placed = os.path.join(_result["dest"], "dummy-bios.bin")
    check("the second has one too", os.path.isfile(_placed), True)
    # A link, not a copy: no second set of bytes to explain or reconcile.
    check("as the same file rather than a copy", os.path.samefile(_held, _placed), True)

    _shared = emu_firmware.installed_elsewhere(CATALOG)
    _second = emu_firmware.status(SECOND, shared=_shared)[0]
    check("the second now reports it installed", _second["installed"], ["dummy-bios.bin"])
    check("as its own, not a file somebody placed", _second["foreign"], [])
    check("and knows the first keeps a copy", _second["kept_by"], ["First Emulator"])

    # Removing it from one emulator must not take it from the other -- the
    # dialog says "keeps its copy", and that has to be true.
    emu_firmware.uninstall(SECOND, "Dummy BIOS")
    check("removing it from the second leaves the first's", os.path.isfile(_held), True)
    _shared = emu_firmware.installed_elsewhere(CATALOG)
    check("and the second is offered it again",
          [item["name"] for item in emu_firmware.status(SECOND, shared=_shared)[0]["elsewhere"]],
          ["dummy-bios.bin"])
    check("once the first is the only holder, removing it is the last copy",
          emu_firmware.status(FIRST, shared=_shared)[0]["kept_by"], [])

    # A fresh dump in the transfer folder is the user's latest word and wins
    # over a file borrowed from another emulator.
    with io.open(os.path.join(_inbox, "DUMMY-BIOS.BIN"), "wb") as _handle:
        _handle.write(b"a newer dump")
    _row = emu_firmware.status(SECOND, shared=_shared)[0]
    check("a file sent is offered instead of a shared one",
          (_row["waiting"], _row["elsewhere"]), (["DUMMY-BIOS.BIN"], []))
    _result = emu_firmware.install(SECOND, "Dummy BIOS", shared=_shared)
    check("and is what installing uses", (_result["copied"], _result["linked"]),
          (["DUMMY-BIOS.BIN"], []))
finally:
    emu_firmware._write_state(_saved_state)
    sysenv.user_home = _real_home


if __name__ == "__main__":
    summary()
