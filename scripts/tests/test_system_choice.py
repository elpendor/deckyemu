#!/usr/bin/env python3
"""Which system a file names, for the cores that cover more than one.

    python scripts/tests/test_system_choice.py

The bug this exists to prevent, measured on a real device: three Mega Drive
ROMs filed under Game Gear, with Game Gear cover art, on a Game Gear shelf.
Genesis Plus GX declares six systems and libretro lists them alphabetically, so
"the core's system" is Game Gear -- and nothing else was looking at the file.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section  # noqa: E402

import platforms  # noqa: E402

section("the system a file extension names")

# The real thing, in the order libretro declares it. The order is the bug:
# alphabetical, so the system the core is *named* after is fourth.
GENESIS_PLUS_GX = [
    "Sega - Game Gear",
    "Sega - Master System - Mark III",
    "Sega - Mega-CD - Sega CD",
    "Sega - Mega Drive - Genesis",
    "Sega - PICO",
    "Sega - SG-1000",
]

check("the core's first database is not the system it is named for",
      GENESIS_PLUS_GX[0], "Sega - Game Gear")
check("a .md cartridge is a Mega Drive one",
      platforms.system_for_extension(GENESIS_PLUS_GX, "md"),
      "Sega - Mega Drive - Genesis")
check("and a .gg cartridge is a Game Gear one",
      platforms.system_for_extension(GENESIS_PLUS_GX, "gg"), "Sega - Game Gear")
check("and .sms is the Master System",
      platforms.system_for_extension(GENESIS_PLUS_GX, "sms"),
      "Sega - Master System - Mark III")

# The guard that lets the table be a plain dict rather than a per-core one: the
# answer has to be a system the core actually claims. `.md` means Mega Drive to
# everyone, and DuckStation reads no Mega Drive cartridges.
check("a system the core does not claim is not offered",
      platforms.system_for_extension(["Sony - PlayStation"], "md"), "")
check("nor is one for an extension nothing here maps",
      platforms.system_for_extension(GENESIS_PLUS_GX, "xyz"), "")
check("a core with no databases answers nothing",
      platforms.system_for_extension([], "md"), "")

# Written by whoever names the file, and read back from `probe_rom`, which
# lowercases -- but a table lookup that depends on that is one refactor from
# being wrong in a way nothing would notice until a game was filed.
check("the extension is matched however it is written",
      platforms.system_for_extension(GENESIS_PLUS_GX, ".MD"),
      "Sega - Mega Drive - Genesis")

# A disc image names a medium, not a system: Mega-CD, Saturn, PlayStation,
# GameCube and PSP all arrive as one. Answering would be a guess, and a guess
# is what this replaces -- so these keep the old behaviour, which is the core's
# first database.
for disc in ("cue", "chd", "iso", "m3u"):
    check("a .%s says nothing about the system" % disc,
          platforms.system_for_extension(GENESIS_PLUS_GX, disc), "")

section("the same question for the other cores that cover two systems")

# Every one of these was filed by the artwork lookup guessing, and every one of
# them would have gone to `databases[0]` when it found nothing.
check("gambatte's .gb is a Game Boy game",
      platforms.system_for_extension(
          ["Nintendo - Game Boy", "Nintendo - Game Boy Color"], "gb"),
      "Nintendo - Game Boy")
check("and its .gbc is a Game Boy Color one",
      platforms.system_for_extension(
          ["Nintendo - Game Boy", "Nintendo - Game Boy Color"], "gbc"),
      "Nintendo - Game Boy Color")
check("Dolphin's .gcm is a GameCube game",
      platforms.system_for_extension(
          ["Nintendo - GameCube", "Nintendo - Wii"], "gcm"),
      "Nintendo - GameCube")
check("and its .wbfs is a Wii one -- the case that named this rule",
      platforms.system_for_extension(
          ["Nintendo - GameCube", "Nintendo - Wii"], "wbfs"),
      "Nintendo - Wii")
check("a WonderSwan Color game is not a WonderSwan one",
      platforms.system_for_extension(
          ["Bandai - WonderSwan", "Bandai - WonderSwan Color"], "wsc"),
      "Bandai - WonderSwan Color")

section("every mapping names a system some core declares")

# The table is only useful for names libretro actually uses: a typo produces an
# entry that can never match, and it would never be noticed -- the guard makes
# it silently inert. Checked against the short-name table, which is the same
# vocabulary.
_unknown = sorted(
    {
        database
        for database in platforms.EXTENSION_SYSTEMS.values()
        if database not in platforms.SHORT_NAMES
    }
)
check("no mapping points at a database name nothing else knows", _unknown, [])
