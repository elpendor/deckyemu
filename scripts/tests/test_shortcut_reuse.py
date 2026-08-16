#!/usr/bin/env python3
"""Re-adding a game that has been renamed takes back its own shortcut.

    python scripts/tests/test_shortcut_reuse.py

A launcher is named `<title>-<hash of the ROM path>.sh`, and re-adding a game
used to look for that whole filename in Steam's shortcuts. That works only while
the title never changes -- and identifying a game through the artwork picker
changes it.

So on a real device: `tobudx.gb` was added as "tobudx", identified as "Tobu Tobu
Girl" in the picker, and re-added. The lookup asked for
`tobu-tobu-girl-e76b843b.sh`, Steam had `tobudx-e76b843b.sh`, and a second entry
appeared beside the first. The original was later unregistered, its launcher
went with the record, and what was left was a shortcut that could not start
anything -- reported by the library check, which is how it was noticed at all.

The digest is the ROM. The slug is only what the game was called at the time.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402

import launchers  # noqa: E402
import steam_shortcuts  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from main import Plugin  # noqa: E402

import asyncio  # noqa: E402

plugin = Plugin()
plugin.loop = asyncio.new_event_loop()


def run(coro):
    return plugin.loop.run_until_complete(coro)


ROM = "/home/deck/deckyemu/roms/game-boy/tobudx.gb"
BEFORE = launchers.launcher_path("tobudx", ROM)
AFTER = launchers.launcher_path("Tobu Tobu Girl", ROM)


section("a launcher's name is a title and a ROM, and only one of them matters")

check("renaming the game renames its launcher",
      os.path.basename(BEFORE) != os.path.basename(AFTER), True)
check("but the ROM half is the same",
      launchers.rom_digest(BEFORE) == launchers.rom_digest(AFTER), True)
check("and it is the hash, not the words",
      launchers.rom_digest(AFTER), launchers.rom_digest(ROM and BEFORE))

# A slug ending in a short word must not be read as a digest, or every game
# whose title ends in a number would look like every other one.
check("a name with no digest offers none",
      launchers.rom_digest("/x/launchers/sonic-3.sh"), "")
check("nor does something that is not hex",
      launchers.rom_digest("/x/launchers/game-zzzzzzzz.sh"), "")
check("nor an empty name", launchers.rom_digest(""), "")
# Two different ROMs are two different games however alike they are named.
check("a different ROM gets a different digest",
      launchers.rom_digest(launchers.launcher_path("tobudx", ROM + ".bak"))
      != launchers.rom_digest(BEFORE), True)


section("so the shortcut is found under either name")

# Restored at the end. The whole suite shares one module, so a stub left in
# place here answers every later file's questions about Steam too -- which is
# how this file broke the mispointed-entry checks two sections away in another.
_real_ours = steam_shortcuts.ours
_shortcuts = [{"app_id": 4242, "title": "tobudx", "exe": BEFORE,
               "launcher": os.path.basename(BEFORE), "launcher_exists": True}]
steam_shortcuts.ours = lambda: list(_shortcuts)

check("the exact launcher is found, as it always was",
      run(plugin.shortcut_for_launcher(BEFORE))["app_id"], 4242)
# The case that made a duplicate.
check("and so is the renamed one, by the ROM it runs",
      run(plugin.shortcut_for_launcher(AFTER))["app_id"], 4242)

# The guard against being too clever: another game must never match.
_other = launchers.launcher_path("Something Else", "/home/deck/deckyemu/roms/game-boy/other.gb")
check("a different game matches nothing",
      run(plugin.shortcut_for_launcher(_other))["app_id"], 0)

# An exact match is still the better answer when both are present, because it is
# the shortcut actually asked for.
_shortcuts.append({"app_id": 777, "title": "Tobu Tobu Girl", "exe": AFTER,
                   "launcher": os.path.basename(AFTER), "launcher_exists": True})
check("with both there, the exact one wins",
      run(plugin.shortcut_for_launcher(AFTER))["app_id"], 777)
check("whichever order they are in",
      run(plugin.shortcut_for_launcher(BEFORE))["app_id"], 4242)

steam_shortcuts.ours = _real_ours
plugin.loop.close()


if __name__ == "__main__":
    summary()
