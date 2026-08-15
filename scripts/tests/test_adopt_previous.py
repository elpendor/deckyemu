#!/usr/bin/env python3
"""Adopting a previous install must not quietly downgrade the games it takes on.

    python scripts/tests/test_adopt_previous.py

Renaming the plugin's folder orphans its registry, and adoption is the way back.
It rebuilt each record from scratch instead of updating the one it had, which
dropped every field it did not think to copy: the per-game launch overrides went,
and the launcher was rewritten from the global settings -- while the new record
claimed the overrides were still in force, so nothing afterwards could tell.

The same construction also filed each game under its core's *first* database, so
adopting a Wii game moved it to GameCube for as long as the entry lived.

Both are properties of building the record by hand, which is why `_entry_for` is
now the only thing that builds one.
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import TMP, check, section, summary  # noqa: E402

import decky  # noqa: E402
import store  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from main import Plugin  # noqa: E402

# Dolphin's core, because it is the one that covers two systems and therefore the
# only one that can be filed under the wrong one.
_CORE = {
    "id": "dolphin_libretro",
    "path": os.path.join(TMP, "cores", "dolphin_libretro.so"),
    "display_name": "Dolphin",
    "system_name": "Nintendo GameCube / Wii",
    "databases": [
        "Nintendo - GameCube",
        "Nintendo - Wii",
    ],
    "extensions": ["iso", "rvz"],
}

plugin = Plugin()
plugin.loop = asyncio.new_event_loop()
plugin._cores = [_CORE]
plugin._emulators = []
# A native install rather than None: adoption writes a real launcher script, and
# what this is about is what goes *into* it.
plugin._install = {"kind": "native", "exe": "/usr/bin/retroarch"}


def run(coro):
    return plugin.loop.run_until_complete(coro)


_SETTINGS = {
    "add_to_collection": True,
    "collection_name": "DeckyEmu",
    "collection_per_platform": True,
    "collection_template": "[{name}] {platform}",
    "platform_names": "short",
    # The globals the game's own overrides must beat.
    "hide_osd": "all",
    "emulator_fullscreen": True,
}

# The ROM has to exist -- adoption skips a game whose file is gone, which would
# make every check below pass by finding nothing.
_ROM_DIR = os.path.join(TMP, "previous-roms")
os.makedirs(_ROM_DIR, exist_ok=True)
_ROM = os.path.join(_ROM_DIR, "A Wii Game.rvz")
with open(_ROM, "wb") as _handle:
    _handle.write(b"not a real disc image")

_OLD_ENTRY = {
    "app_id": 4242,
    "title": "A Wii Game",
    "rom_path": _ROM,
    "core_id": "dolphin_libretro",
    "core_path": "/somewhere/else/dolphin_libretro.so",
    # Recorded by the install that added it, which knew this was Wii.
    "system": "Nintendo - Wii",
    "platform": "Wii",
    "collection": "[DeckyEmu] Wii",
    "launcher_path": "/old/install/launchers/a-wii-game.sh",
    # The whole point: choices somebody made on this one game.
    "options": {"hide_osd": "keep", "fullscreen": False, "extra_args": "--verbose"},
}

# A previous install is any other plugin folder under decky's settings root.
_PREVIOUS_DIR = os.path.join(decky.DECKY_HOME, "settings", "retroarch-to-steam")
os.makedirs(_PREVIOUS_DIR, exist_ok=True)
_PREVIOUS = os.path.join(_PREVIOUS_DIR, "library.json")
with open(_PREVIOUS, "w", encoding="utf-8") as _handle:
    json.dump({"4242": _OLD_ENTRY}, _handle)


section("the previous install is found")

store.set_settings(dict(_SETTINGS))
store.clear_library()

# Picked out by path rather than by being the only one: the whole suite shares
# one scratch directory, so another file's previous install is also on disk when
# this runs inside it.
_found = [
    item
    for item in run(plugin._run(plugin._find_previous_installs))
    if os.path.normpath(item["path"]) == os.path.normpath(_PREVIOUS)
]
check("the library left behind under another folder name is found", len(_found), 1)
check("and the game in it is offered", _found[0]["games"][0]["app_id"], 4242)


section("adopting it keeps everything the old record knew")

_result = run(plugin.adopt_previous_install(_PREVIOUS))
check("the adoption succeeds", _result["ok"], True)
check("nothing is skipped", _result["skipped"], [])
check("the game is adopted", [game["app_id"] for game in _result["adopted"]], [4242])

_entry = store.get_library()["4242"]

# The bug this file exists for. A fresh dict has no `options` in it, so every
# per-game choice was reset to the global setting by the act of adopting -- and
# silently, because there is nothing left to compare against afterwards.
check("the per-game launch overrides survive",
      _entry.get("options"),
      {"hide_osd": "keep", "fullscreen": False, "extra_args": "--verbose"})

# The other half of the same bug: the record kept the overrides while the script
# was written from the globals, which is worse than losing both -- the record
# then says the game is doing something it is not.
with open(_entry["launcher_path"], "r", encoding="utf-8") as _handle:
    _script = _handle.read()
check("and the launcher is written from them, not from the globals",
      "--verbose" in _script, True)
# `hide_osd: keep` suppresses nothing, so the global "all" override file must not
# be the one this game appends.
check("the game's own OSD choice is the one baked in",
      "-all.cfg" in _script, False)


section("and it stays on the system it was filed under")

# Dolphin declares GameCube first, so taking `databases[0]` is how adopting a Wii
# game moved it to a GameCube shelf. The stored system is preferred wherever the
# core still claims it.
check("the recorded system is the one the old install worked out",
      _entry["system"], "Nintendo - Wii")
check("so the platform label does not change under the user", _entry["platform"], "Wii")
check("nor does the collection it belongs to", _entry["collection"], "[DeckyEmu] Wii")
check("which is the collection the caller is told to file it into",
      _result["adopted"][0]["collection"], "[DeckyEmu] Wii")


section("and the parts that must change, do")

check("the launcher is rewritten into this install's directory",
      os.path.dirname(_entry["launcher_path"]) != os.path.dirname(_OLD_ENTRY["launcher_path"]),
      True)
check("the core path is this install's, not the old one's",
      _entry["core_path"], _CORE["path"])


store.clear_library()
plugin.loop.close()


if __name__ == "__main__":
    summary()
