#!/usr/bin/env python3
"""A disc whose tracks are not all here, and a disc sent as a zip.

    python scripts/tests/test_disc_sheets.py

Both end in a game that cannot start if added as they are: a sheet naming
tracks that never arrived, and a zip RetroArch takes only the sheet out of.
"""

import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import TMP, check, section, summary  # noqa: E402

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "py_modules"))

import ra_cores  # noqa: E402
import romshelf  # noqa: E402

_DIR = os.path.join(TMP, "disc_sheets")
os.makedirs(_DIR, exist_ok=True)


def _write(name, data=b""):
    path = os.path.join(_DIR, name)
    with open(path, "wb") as handle:
        handle.write(data)
    return path


section("a sheet says which of its tracks are missing")

_sheet = _write("Harbor Dash (USA).cue",
                b'FILE "Harbor Dash (USA) (Track 1).bin" BINARY\n'
                b'FILE "Harbor Dash (USA) (Track 2).bin" BINARY\n')
check("both missing", romshelf.missing_from_sheet(_sheet),
      ["Harbor Dash (USA) (Track 1).bin", "Harbor Dash (USA) (Track 2).bin"])
_write("harbor dash (usa) (track 1).BIN")
check("one arrived, in another case", romshelf.missing_from_sheet(_sheet),
      ["Harbor Dash (USA) (Track 2).bin"])
_write("Harbor Dash (USA) (Track 2).bin")
check("none missing once all are here", romshelf.missing_from_sheet(_sheet), [])
check("a file that is not a sheet names nothing",
      romshelf.missing_from_sheet(_write("Harbor Dash.gba")), [])


section("a zipped disc is told apart from a zipped ROM")


def _zip(name, members):
    path = os.path.join(_DIR, name)
    with zipfile.ZipFile(path, "w") as archive:
        for member in members:
            archive.writestr(member, b"x")
    return path


check("a zip with a sheet and its track is a disc",
      ra_cores.zipped_disc(_zip("disc.zip", ["Game.cue", "Game.bin"])), True)
check("a zipped cartridge is not",
      ra_cores.zipped_disc(_zip("cart.zip", ["Game.gba"])), False)
check("nor is a file that is not a zip",
      ra_cores.zipped_disc(_write("plain.zip", b"not a zip")), False)

if __name__ == "__main__":
    summary()
