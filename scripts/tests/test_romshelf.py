#!/usr/bin/env python3
"""Filing a ROM under its system when its game is added, and deleting it again.

    python scripts/tests/test_romshelf.py
"""

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import TMP, check, section, summary  # noqa: E402

import romshelf  # noqa: E402

section("filing a ROM under its system, once the system is actually known")
# Sorting on the way in has to ask somebody holding a phone what a file is, and
# .iso is GameCube, PS2, PSP and Xbox. Sorting on the way out asks nobody: the
# system is whatever core was picked. This runs before the launcher is written,
# because the path is baked into the launcher's argv, hashed into its filename
# and recorded in the library -- moving a ROM after any of that breaks a game in
# three places.

_inbox = os.path.join(TMP, "inbox")
_shelf = os.path.join(TMP, "shelved")
os.makedirs(_inbox, exist_ok=True)
os.makedirs(_shelf, exist_ok=True)


def _drop(*names):
    for name in names:
        with io.open(os.path.join(_inbox, name), "w") as handle:
            handle.write("x")
    return os.path.join(_inbox, names[0])


_plain = _drop("Super Mario World.sfc")
_filed = romshelf.file_rom(_plain, "Nintendo - Super Nintendo Entertainment System",
                           _inbox, _shelf)
check("a plain ROM is filed under its system",
      _filed, os.path.join(_shelf, "snes", "Super Mario World.sfc"))
check("and is really there", os.path.isfile(_filed), True)
check("and gone from the inbox", os.path.isfile(_plain), False)

# The hazard this design introduces. A .cue names its .bin, a .m3u names its
# discs, and moving one without the others breaks the game in a way that reads
# as a bad dump.
_cue = _drop("Final Fantasy VII (Disc 1).cue")
with io.open(_cue, "w") as _handle:
    _handle.write('FILE "Final Fantasy VII (Disc 1).bin" BINARY\n  TRACK 01 MODE2/2352\n')
_drop("Final Fantasy VII (Disc 1).bin")
_moved = romshelf.file_rom(_cue, "Sony - PlayStation", _inbox, _shelf)
check("a cue sheet takes its track with it",
      sorted(os.listdir(os.path.join(_shelf, "ps1"))),
      ["Final Fantasy VII (Disc 1).bin", "Final Fantasy VII (Disc 1).cue"])
check("and the returned path is the file that was picked",
      os.path.basename(_moved), "Final Fantasy VII (Disc 1).cue")

# A playlist naming discs that share no stem with it -- which stem matching
# alone would never find.
_m3u = _drop("Metal Gear Solid.m3u")
with io.open(_m3u, "w") as _handle:
    _handle.write("Metal Gear Solid (Disc 1).chd\nMetal Gear Solid (Disc 2).chd\n")
_drop("Metal Gear Solid (Disc 1).chd", "Metal Gear Solid (Disc 2).chd")
romshelf.file_rom(_m3u, "Sony - PlayStation", _inbox, _shelf)
check("a playlist takes every disc it names",
      sorted(n for n in os.listdir(os.path.join(_shelf, "ps1")) if "Metal" in n),
      ["Metal Gear Solid (Disc 1).chd", "Metal Gear Solid (Disc 2).chd",
       "Metal Gear Solid.m3u"])

# And the rule that keeps the hazard from biting: all of it moves or none does.
_broken = _drop("Broken.m3u")
with io.open(_broken, "w") as _handle:
    _handle.write("Broken (Disc 1).chd\nBroken (Disc 2).chd\n")
_drop("Broken (Disc 1).chd")
check("a set with a disc missing is not moved at all",
      romshelf.file_rom(_broken, "Sony - PlayStation", _inbox, _shelf), _broken)
check("and nothing of it was taken",
      os.path.isfile(os.path.join(_inbox, "Broken (Disc 1).chd")), True)

# Removing a game deletes the game. The alternative was a checkbox defaulting
# to keeping the file, which is kinder on a mis-press and leaves a growing pile
# of files nothing points at -- a second thing to reconcile forever. What
# protects the user now is that the dialog says exactly what goes, so what is
# tested here is the boundary of what it may touch.
_filed_rom = os.path.join(_shelf, "snes", "Super Mario World.sfc")
check("a filed ROM is ours to delete", romshelf.owned(_filed_rom, _shelf), True)
check("one still in the inbox is not",
      romshelf.owned(os.path.join(_inbox, "Whatever.sfc"), _shelf), False)
check("nor is one loose in the library root",
      romshelf.owned(os.path.join(_shelf, "Loose.sfc"), _shelf), False)
_notours = os.path.join(TMP, "someone-elses", "Chrono Trigger.sfc")
os.makedirs(os.path.dirname(_notours), exist_ok=True)
io.open(_notours, "w").close()
check("nor is one anywhere else at all", romshelf.owned(_notours, _shelf), False)
check("and deleting one that is not ours is refused",
      romshelf.delete_rom(_notours, _shelf)[1] != "", True)
check("with the file still there afterwards", os.path.isfile(_notours), True)

# A disc image and its tracks go together, exactly as they were filed: deleting
# the cue and leaving the bin would leave a file nothing can ever point at.
_ff_cue = os.path.join(_shelf, "ps1", "Final Fantasy VII (Disc 1).cue")
_freed, _error = romshelf.delete_rom(_ff_cue, _shelf)
check("deleting a cue sheet takes its track too",
      (_error, sorted(n for n in os.listdir(os.path.join(_shelf, "ps1")) if "Final" in n)),
      ("", []))
check("and it reports what that freed", _freed > 0, True)

# The system folder goes with the last game in it, for the same reason an empty
# collection does.
_only = os.path.join(_shelf, "xbox")
os.makedirs(_only, exist_ok=True)
io.open(os.path.join(_only, "Halo.iso"), "w").close()
romshelf.delete_rom(os.path.join(_only, "Halo.iso"), _shelf)
check("an emptied system folder is removed too", os.path.isdir(_only), False)

# Files the user keeps elsewhere are theirs. A plugin that tidies other
# people's directories is one nobody trusts twice.
_elsewhere = os.path.join(TMP, "mylibrary")
os.makedirs(_elsewhere, exist_ok=True)
_mine = os.path.join(_elsewhere, "Chrono Trigger.sfc")
io.open(_mine, "w").close()
check("a ROM outside the inbox is left where it is",
      romshelf.file_rom(_mine, "Nintendo - Super Nintendo Entertainment System",
                        _inbox, _shelf),
      _mine)
check("and it is still there", os.path.isfile(_mine), True)

# Nothing is overwritten, and an unknown system is not a folder name.
# The same file sent twice. Refusing to file it was the first behaviour and it
# read as the feature being broken: the ROM sat in the inbox, the launcher
# pointed at the inbox copy, and the folder never emptied -- reported as "it
# copied it instead of moving it", which is what two identical files in two
# places is. The arriving copy is redundant, so it goes.
_again = _drop("Super Mario World.sfc")
check("sending the same ROM again files it to the copy already there",
      romshelf.file_rom(_again, "Nintendo - Super Nintendo Entertainment System",
                        _inbox, _shelf),
      os.path.join(_shelf, "snes", "Super Mario World.sfc"))
check("and the duplicate is gone from the inbox", os.path.isfile(_again), False)

# A different file that happens to share the name is a different dump, and
# nothing is overwritten for that.
_clash = os.path.join(_inbox, "Super Mario World.sfc")
with io.open(_clash, "w") as _handle:
    _handle.write("a completely different dump")
check("a different file of the same name is left alone",
      romshelf.file_rom(_clash, "Nintendo - Super Nintendo Entertainment System",
                        _inbox, _shelf),
      _clash)
check("and the one already filed is untouched",
      io.open(os.path.join(_shelf, "snes", "Super Mario World.sfc"),
              encoding="utf-8").read(), "x")
os.remove(_clash)
_again = _drop("Super Mario World.sfc")
check("an unknown system leaves the file alone",
      romshelf.file_rom(_again, "", _inbox, _shelf), _again)


if __name__ == "__main__":
    summary()
