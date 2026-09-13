#!/usr/bin/env python3
"""ROM hacks are a list, and the ROM is never touched.

    python scripts/tests/test_rom_patch.py

Mostly the refusals, the order RetroArch reads the files in, and a byte-compare
of the ROM at every step: "the ROM is never touched" is the promise the whole
feature rests on.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import TMP, check, section, summary  # noqa: E402

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "py_modules"))

import rompatch  # noqa: E402

_ROOT = os.path.join(TMP, "patching")
os.makedirs(_ROOT, exist_ok=True)

_APP = "3222459943"
_ROM = os.path.join(_ROOT, "Chrono Trigger.sfc")
_ROM_BYTES = b"rom" * 64


def _write(path, data):
    with open(path, "wb") as handle:
        handle.write(data)
    return path


def _read(path):
    with open(path, "rb") as handle:
        return handle.read()


def _names_beside():
    return sorted(os.path.basename(one) for one in rompatch.beside(_ROM))


def _reset(app=_APP):
    _write(_ROM, _ROM_BYTES)
    for row in rompatch.listing(app):
        rompatch.remove(app, row["file"])
    for path in rompatch.beside(_ROM):
        os.remove(path)


_IPS = _write(os.path.join(_ROOT, "Retranslation v1.2.ips"), b"PATCH\x00\x00\x00EOF")
_IPS2 = _write(os.path.join(_ROOT, "Bugfixes.ips"), b"PATCH\x00\x00\x01EOF")
_BPS = _write(os.path.join(_ROOT, "Some Hack.bps"), b"BPS1payload")
_NOT = _write(os.path.join(_ROOT, "readme.txt"), b"Apply this with Lunar IPS.")
# Renamed by the browser on the way down, which is the ordinary case.
_MISNAMED = _write(os.path.join(_ROOT, "hack.ips.txt"), b"PATCH\x00\x00\x00EOF")


section("the format is read from the file, not from its name")

check("an IPS is an IPS however it was renamed", rompatch.kind_of(_MISNAMED), ".ips")
check("a BPS is told apart from it", rompatch.kind_of(_BPS), ".bps")
check("and something that is neither is nothing", rompatch.kind_of(_NOT), "")
check("nor is the ROM, which is the file people actually pick by mistake",
      rompatch.kind_of(_ROM), "")
check("a path that is not there answers the same way rather than raising",
      rompatch.kind_of(os.path.join(_ROOT, "nothing.ips")), "")


section("adding keeps a copy, so switching one off does not lose it")

_reset()
_row, _error = rompatch.add(_APP, _IPS)
check("it is taken", (bool(_row), _error), (True, ""))
check("under its own name, which is the only thing that says which hack it is",
      [one["name"] for one in rompatch.listing(_APP)], ["Retranslation v1.2.ips"])
check("switched on, because adding one is asking for it",
      [one["on"] for one in rompatch.listing(_APP)], [True])
check("and the copy is ours, not a reference to wherever it came from",
      os.path.isfile(os.path.join(rompatch.store_dir(_APP), _row["file"])), True)
check("nothing is beside the ROM until it is written out", _names_beside(), [])


section("what RetroArch reads, in the order it reads it")

rompatch.add(_APP, _IPS2)
rompatch.add(_APP, _BPS)
_count, _error = rompatch.sync(_APP, _ROM)
check("every switched-on patch is written", (_count, _error), (3, ""))
# `rom.ips`, then `rom.ips1`, then `rom.ips2` -- the documented order, and the
# reason the list is ordered at all. The .bps numbers separately.
check("the first of a format is bare and the rest are numbered",
      _names_beside(),
      ["Chrono Trigger.bps", "Chrono Trigger.ips", "Chrono Trigger.ips1"])
check("the ROM is byte for byte what it was", _read(_ROM), _ROM_BYTES)


section("switching one off takes it out without a gap in the numbering")

_first = rompatch.listing(_APP)[0]["file"]
rompatch.switch(_APP, _first, False)
_count, _error = rompatch.sync(_APP, _ROM)
check("one fewer is written", (_count, _error), (2, ""))
check("and the one left is bare, not still numbered 1",
      _names_beside(), ["Chrono Trigger.bps", "Chrono Trigger.ips"])
check("while the patch itself is still on the list, switched off",
      [(one["name"], one["on"]) for one in rompatch.listing(_APP)][0],
      ("Retranslation v1.2.ips", False))

rompatch.switch(_APP, _first, True)
rompatch.sync(_APP, _ROM)
check("turning it back on restores it", len(_names_beside()), 3)


section("order decides what wins, so the list can be reordered")

_files = [one["file"] for one in rompatch.listing(_APP)]
rompatch.reorder(_APP, [_files[1], _files[0], _files[2]])
check("the list follows",
      [one["name"] for one in rompatch.listing(_APP)][:2],
      ["Bugfixes.ips", "Retranslation v1.2.ips"])
rompatch.sync(_APP, _ROM)
check("and the bare name goes to whichever is first now",
      _read(os.path.join(_ROOT, "Chrono Trigger.ips")), _read(_IPS2))


section("deleting one removes the copy as well as the row")

_gone = rompatch.listing(_APP)[0]["file"]
_kept = os.path.join(rompatch.store_dir(_APP), _gone)
rompatch.remove(_APP, _gone)
check("the row goes", len(rompatch.listing(_APP)), 2)
check("and so does the copy", os.path.isfile(_kept), False)
rompatch.sync(_APP, _ROM)
check("with the ROM still the ROM", _read(_ROM), _ROM_BYTES)


section("a file that is not a patch is refused, and the list is unchanged")

_before = rompatch.listing(_APP)
_row, _error = rompatch.add(_APP, _NOT)
check("refused", _row, None)
check("and told why, in terms of the mistake actually made",
      "not the ROM" in _error, True)
check("the list is what it was", rompatch.listing(_APP), _before)

check("a patch that is not there is refused too",
      rompatch.add(_APP, os.path.join(_ROOT, "gone.ips"))[0], None)
_empty = _write(os.path.join(_ROOT, "empty.ips"), b"")
check("and an empty file, which is what a failed download leaves",
      rompatch.add(_APP, _empty)[0], None)


section("a hack somebody placed by hand is taken into the list, not hidden")

_ADOPT = "77"
_reset(_ADOPT)
_write(os.path.join(_ROOT, "Chrono Trigger.ips"), _read(_IPS))
check("it is found", rompatch.adopt(_ADOPT, _ROM), 1)
check("and listed, switched on, so the screen agrees with the emulator",
      [(one["name"], one["on"]) for one in rompatch.listing(_ADOPT)],
      [("Chrono Trigger.ips", True)])
check("adopting again takes nothing, because the list is no longer empty",
      rompatch.adopt(_ADOPT, _ROM), 0)


section("what RetroArch cannot soft-patch is said before it is tried")

# Measured on the Deck rather than assumed: the same hack applied to a zipped
# Pokemon Sapphire and to the .gba inside it, on mGBA, with the same result. The
# warning that used to be here was wrong.
check("a zipped ROM gets no warning, because archives do patch",
      rompatch.warning_for(os.path.join(_ROOT, "game.zip")), "")
check("a disc image still does, because the core loads it by path",
      "memory" in rompatch.warning_for(os.path.join(_ROOT, "game.chd")), True)
check("a cartridge dump gets no warning at all", rompatch.warning_for(_ROM), "")
check("and neither does a .bin, which is a Mega Drive cartridge",
      rompatch.warning_for(os.path.join(_ROOT, "Sonic.bin")), "")


section("the transfer list does not offer to make a game out of a patch")

_MODAL = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "src", "TransferModal.tsx")
with open(_MODAL, encoding="utf-8") as _handle:
    _source = _handle.read()

# The row's action is decided by what the file is for, the way a BIOS gets
# Install and a save backup gets Restore. A patch belongs to a game that already
# exists, and the add flow would make a Steam entry out of one -- so its row
# installs it, asking which game, rather than offering Add.
check("every format the editor takes is recognised there too",
      all(('"%s"' % suffix) in _source for suffix, _magic in rompatch.PATCH_MAGIC),
      True)
check("and the row installs it onto a game rather than adding it as one",
      "openPatchInstall(" in _source, True)


section("installing from outside the editor asks which game, the named one first")

_LIBRARY = [
    {"app_id": 1, "title": "Secret of Mana", "rom_path": os.path.join(_ROOT, "Secret of Mana (USA).sfc"),
     "platform": "SNES"},
    {"app_id": 2, "title": "Chrono Trigger", "rom_path": _ROM, "platform": "SNES"},
    {"app_id": 3, "title": "Crash Bandicoot", "rom_path": os.path.join(_ROOT, "Crash.chd"),
     "platform": "PS1"},
]
_ranked = rompatch.rank_targets(os.path.join(_ROOT, "Chrono Trigger Retranslation v1.2.ips"),
                                _LIBRARY)
check("the game named in the patch comes first, and is marked as the likely one",
      [(one["title"], one["likely"]) for one in _ranked][0], ("Chrono Trigger", True))
check("and every other game is still offered, since a name is only a hint",
      sorted(one["title"] for one in _ranked),
      ["Chrono Trigger", "Crash Bandicoot", "Secret of Mana"])
check("words like 'patch' and 'translation' are not a match on their own",
      [one["likely"] for one in rompatch.rank_targets("Translation Patch.ips", _LIBRARY)],
      [False, False, False])
check("a disc game says RetroArch may ignore it, before anyone chooses it",
      [one["warning"] != "" for one in _ranked if one["title"] == "Crash Bandicoot"], [True])


if __name__ == "__main__":
    summary()
