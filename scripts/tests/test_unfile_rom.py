#!/usr/bin/env python3
"""Undoing an import puts its files back in the transfer folder.

    python scripts/tests/test_unfile_rom.py

`unfile_rom` is `file_rom` backwards, and it has to be as careful: the whole
group moves or none of it, and nothing in the inbox is overwritten.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import TMP, check, section, summary  # noqa: E402

import platforms  # noqa: E402
import romshelf  # noqa: E402

_INBOX = os.path.join(TMP, "unfile", "transfer")
_LIBRARY = os.path.join(TMP, "unfile", "roms")
os.makedirs(_INBOX, exist_ok=True)
os.makedirs(_LIBRARY, exist_ok=True)


def _write(folder, name, body="x"):
    with open(os.path.join(folder, name), "w", encoding="utf-8") as handle:
        handle.write(body)
    return os.path.join(folder, name)


section("a disc and its track go back together")

_write(_INBOX, "Harbor Dash.cue", 'FILE "Harbor Dash.bin" BINARY\n  TRACK 01 MODE2/2352\n')
_write(_INBOX, "Harbor Dash.bin")
_filed = romshelf.file_rom(os.path.join(_INBOX, "Harbor Dash.cue"), "Sony - PlayStation",
                           _INBOX, _LIBRARY)
check("filing moved it out of the inbox", os.path.dirname(_filed) != _INBOX, True)
_back = romshelf.unfile_rom(_filed, _INBOX, _LIBRARY)
check("unfiling returns its path in the inbox", _back, os.path.join(_INBOX, "Harbor Dash.cue"))
check("and the track came with it", os.path.isfile(os.path.join(_INBOX, "Harbor Dash.bin")), True)
check("leaving nothing behind", os.listdir(os.path.dirname(_filed)), [])


section("nothing is overwritten")

_filed = romshelf.file_rom(os.path.join(_INBOX, "Harbor Dash.cue"), "Sony - PlayStation",
                           _INBOX, _LIBRARY)
_write(_INBOX, "Harbor Dash.bin", "a different file")
check("a name taken in the inbox keeps the game where it is",
      romshelf.unfile_rom(_filed, _INBOX, _LIBRARY), _filed)
check("and the inbox file is untouched",
      open(os.path.join(_INBOX, "Harbor Dash.bin"), encoding="utf-8").read(), "a different file")


section("only filed games")

_elsewhere = _write(os.path.join(TMP, "unfile"), "Loose.sfc")
check("a ROM outside roms/<system>/ is left alone",
      romshelf.unfile_rom(_elsewhere, _INBOX, _LIBRARY), _elsewhere)

section("the shelf names its system, for the hint undo leaves")

check("a shelf filing made is read back",
      platforms.system_for_shelf("/r/roms/%s/x.zip" % platforms.folder_name("Nintendo - Game Boy Color")),
      "Nintendo - Game Boy Color")
check("a folder people name still counts", platforms.system_for_shelf("/r/roms/psx/x.bin"), "Sony - PlayStation")
check("anything else is no system", platforms.system_for_shelf("/r/roms/misc/x.bin"), "")


if __name__ == "__main__":
    summary()
